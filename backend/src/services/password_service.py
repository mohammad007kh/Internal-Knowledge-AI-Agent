"""Password hashing and policy validation service.

Stub created by T-020 (bootstrap admin).  Will be fully implemented in T-022.
"""

import re

import bcrypt


class PasswordService:
    """Centralised password operations — hash, verify, and policy checks.

    This is the **only** place in the codebase where passwords are hashed or
    validated.  No other module should call bcrypt / passlib directly.
    """

    @staticmethod
    def hash_password(password: str) -> str:
        """Return a bcrypt hash of *password*."""
        return bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        """Return ``True`` if *plain* matches *hashed*."""
        return bcrypt.checkpw(
            plain.encode("utf-8"), hashed.encode("utf-8")
        )

    @staticmethod
    def validate_password_policy(password: str) -> None:
        """Raise ``ValueError`` if *password* does not meet policy (FR-034).

        Policy: min 8 chars, ≥1 uppercase, ≥1 lowercase, ≥1 digit.
        """
        errors: list[str] = []
        if len(password) < 8:
            errors.append("at least 8 characters")
        if not re.search(r"[A-Z]", password):
            errors.append("at least one uppercase letter")
        if not re.search(r"[a-z]", password):
            errors.append("at least one lowercase letter")
        if not re.search(r"\d", password):
            errors.append("at least one digit")
        if errors:
            raise ValueError(
                f"Password policy violation: {', '.join(errors)}"
            )
