"""Unit tests for :pymod:`src.services.password_service` (T-022).

Tests cover:

* ``hash_password`` / ``verify_password`` round-trip
* ``validate_password_policy`` — each individual violation
* bcrypt cost-factor = 12
* No false positives on a valid password
"""

import re

import pytest

from src.services.password_service import PasswordService, _BCRYPT_ROUNDS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A password that satisfies every policy rule.
VALID_PASSWORD = "Str0ng!Pass"


# ---------------------------------------------------------------------------
# hash_password / verify_password round-trip
# ---------------------------------------------------------------------------


class TestHashPassword:
    """Tests for ``PasswordService.hash_password``."""

    def test_returns_string(self) -> None:
        result = PasswordService.hash_password(VALID_PASSWORD)
        assert isinstance(result, str)

    def test_returns_bcrypt_hash(self) -> None:
        result = PasswordService.hash_password(VALID_PASSWORD)
        # bcrypt hashes start with $2b$ (or $2a$)
        assert result.startswith(("$2b$", "$2a$"))

    def test_cost_factor_is_12(self) -> None:
        result = PasswordService.hash_password(VALID_PASSWORD)
        # bcrypt embeds the cost as "$2b$12$..."
        assert result.startswith(f"$2b${_BCRYPT_ROUNDS:02d}$")

    def test_different_calls_produce_different_hashes(self) -> None:
        h1 = PasswordService.hash_password(VALID_PASSWORD)
        h2 = PasswordService.hash_password(VALID_PASSWORD)
        assert h1 != h2  # different salts

    def test_hash_length(self) -> None:
        """bcrypt hashes are always 60 characters."""
        result = PasswordService.hash_password(VALID_PASSWORD)
        assert len(result) == 60


class TestVerifyPassword:
    """Tests for ``PasswordService.verify_password``."""

    def test_correct_password_returns_true(self) -> None:
        hashed = PasswordService.hash_password(VALID_PASSWORD)
        assert PasswordService.verify_password(VALID_PASSWORD, hashed) is True

    def test_wrong_password_returns_false(self) -> None:
        hashed = PasswordService.hash_password(VALID_PASSWORD)
        assert PasswordService.verify_password("WrongP@ss1", hashed) is False

    def test_empty_password_returns_false(self) -> None:
        hashed = PasswordService.hash_password(VALID_PASSWORD)
        assert PasswordService.verify_password("", hashed) is False

    def test_round_trip_with_special_characters(self) -> None:
        pwd = "C0mpl€x!P@$$"
        hashed = PasswordService.hash_password(pwd)
        assert PasswordService.verify_password(pwd, hashed) is True


# ---------------------------------------------------------------------------
# validate_password_policy — valid password
# ---------------------------------------------------------------------------


class TestValidatePasswordPolicyValid:
    """Ensure valid passwords pass without raising."""

    def test_valid_password_passes(self) -> None:
        # Should not raise
        PasswordService.validate_password_policy(VALID_PASSWORD)

    def test_exactly_8_characters(self) -> None:
        """Minimum boundary — 8 chars should pass."""
        pwd = "Aa1!xxxx"  # 8 chars, has upper, digit, special
        PasswordService.validate_password_policy(pwd)

    def test_exactly_128_characters(self) -> None:
        """Maximum boundary — 128 chars should pass."""
        # Build a 128-char password that meets all rules
        pwd = "A1!" + "a" * 125  # 128 chars total
        assert len(pwd) == 128
        PasswordService.validate_password_policy(pwd)

    def test_all_special_characters_accepted(self) -> None:
        """Each special character from the allowed set should satisfy the rule."""
        specials = "!@#$%^&*()-_=+[]{}|;:',.<>?/"
        for ch in specials:
            pwd = f"Abcdef1{ch}"
            PasswordService.validate_password_policy(pwd)


# ---------------------------------------------------------------------------
# validate_password_policy — individual violations
# ---------------------------------------------------------------------------


class TestValidatePasswordPolicyViolations:
    """Each test triggers exactly one violation."""

    def test_too_short(self) -> None:
        """Password shorter than 8 characters."""
        with pytest.raises(ValueError, match="at least 8 characters"):
            PasswordService.validate_password_policy("A1!abcd")  # 7 chars

    def test_too_long(self) -> None:
        """Password longer than 128 characters."""
        pwd = "A1!" + "a" * 126  # 129 chars
        assert len(pwd) == 129
        with pytest.raises(ValueError, match="must not exceed 128"):
            PasswordService.validate_password_policy(pwd)

    def test_no_uppercase(self) -> None:
        """Missing uppercase letter."""
        with pytest.raises(ValueError, match="uppercase letter"):
            PasswordService.validate_password_policy("abcdefg1!")

    def test_no_digit(self) -> None:
        """Missing digit."""
        with pytest.raises(ValueError, match="one digit"):
            PasswordService.validate_password_policy("Abcdefgh!")

    def test_no_special_character(self) -> None:
        """Missing special character."""
        with pytest.raises(ValueError, match="special character"):
            PasswordService.validate_password_policy("Abcdefg1")


class TestValidatePasswordPolicyEdgeCases:
    """Edge-case and boundary tests for policy validation."""

    def test_empty_string(self) -> None:
        """Empty string fails on length (first error surfaced)."""
        with pytest.raises(ValueError, match="at least 8 characters"):
            PasswordService.validate_password_policy("")

    def test_only_spaces(self) -> None:
        """Spaces contribute to length but lack other requirements."""
        with pytest.raises(ValueError):
            PasswordService.validate_password_policy("        ")  # 8 spaces

    def test_unicode_characters_count_towards_length(self) -> None:
        """Unicode chars are counted by len() — ensures no byte-length confusion."""
        # 8 chars including unicode, plus ASCII uppercase + digit + special
        pwd = "A1!ääääa"  # 8 chars, A=upper, 1=digit, !=special
        assert len(pwd) == 8
        PasswordService.validate_password_policy(pwd)

    def test_error_is_value_error(self) -> None:
        """Verify the exception type is exactly ValueError."""
        with pytest.raises(ValueError):
            PasswordService.validate_password_policy("short")

    def test_first_error_is_surfaced(self) -> None:
        """When multiple rules fail, only the first error message is raised."""
        # "x" — fails length, uppercase, digit, special
        with pytest.raises(ValueError, match="at least 8 characters"):
            PasswordService.validate_password_policy("x")
