"""Password hashing and policy validation service (T-022).

This is the **only** place in the codebase where passwords are hashed or
validated.  No other module should import ``bcrypt`` directly.
"""

import re

import bcrypt

_SPECIAL_CHARS = r"!@#$%^&*()\-_=+\[\]{}|;:',.<>?/"
"""Regex character-class fragment listing allowed special characters."""

_BCRYPT_ROUNDS = 12
"""Work-factor used for bcrypt hashing (cost = 12)."""


class PasswordService:
    """Centralised password operations — hash, verify, and policy checks.

    This is the **only** place in the codebase where passwords are hashed or
    validated.  No other module should call ``bcrypt`` directly.
    """

    @staticmethod
    def hash_password(password: str) -> str:
        """Return a bcrypt hash of *password* using cost-factor 12."""
        return bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(rounds=_BCRYPT_ROUNDS),
        ).decode("utf-8")

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        """Return ``True`` if *plain* matches *hashed*."""
        return bcrypt.checkpw(
            plain.encode("utf-8"), hashed.encode("utf-8")
        )

    @staticmethod
    def validate_password_policy(password: str) -> None:
        """Raise ``ValueError`` if *password* does not meet policy.

        Policy (FR-AUTH-1 / FR-AUTH-3):

        * Length between 8 and 128 characters (inclusive).
        * At least one uppercase letter.
        * At least one digit.
        * At least one special character from
          ``!@#$%^&*()-_=+[]{}|;:',.<>?/``.

        When used inside a Pydantic ``field_validator``, the ``ValueError``
        is automatically converted to a ``ValidationError`` with a
        field-level error message.
        """
        errors: list[str] = []

        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if len(password) > 128:
            errors.append("Password must not exceed 128 characters.")
        if not re.search(r"[A-Z]", password):
            errors.append(
                "Password must contain at least one uppercase letter."
            )
        if not re.search(r"\d", password):
            errors.append(
                "Password must contain at least one digit."
            )
        if not re.search(rf"[{_SPECIAL_CHARS}]", password):
            errors.append(
                "Password must contain at least one special character."
            )

        if errors:
            raise ValueError(errors[0])
