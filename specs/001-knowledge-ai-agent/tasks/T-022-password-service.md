---
id: T-022
title: bcrypt Password Hashing Service + Validation Policy
status: Not Started
created: 2026-02-25
phase: Phase 1 — Auth & User Management
user_story: US3
requirements: [FR-AUTH-1, FR-AUTH-3]
priority: P1
depends_on: [T-021]
blocks: [T-025]
estimated_effort: 1h
---

## Goal

Implement the `PasswordService` that wraps bcrypt hashing and exposes `validate_password_policy()`. This is the **only** place in the entire codebase where passwords are hashed or validated — no other code should call `bcrypt` directly.

---

## Acceptance Criteria

- [ ] `hash_password(plain: str) -> str` returns a bcrypt hash (cost=12)
- [ ] `verify_password(plain: str, hashed: str) -> bool` verifies correctly
- [ ] `validate_password_policy(password: str)` raises `ValidationError` (Pydantic) when:
  - Length < 8
  - Length > 128
  - No uppercase letter
  - No digit
  - No special character from `!@#$%^&*()-_=+[]{}|;:',.<>?/`
- [ ] All password errors return field-level Pydantic validation errors (not raw exceptions)
- [ ] Unit tests: valid password, each individual policy violation, correct hash/verify round-trip

---

## Files to Create

| Path | Purpose |
|------|---------|
| `backend/src/services/password_service.py` | bcrypt wrapper + policy validator |
| `backend/tests/unit/test_password_service.py` | Unit tests |

---

## Implementation

### `backend/src/services/password_service.py`

```python
import re
from passlib.context import CryptContext
from pydantic import field_validator, ValidationError

_SPECIAL_CHARS = r"!@#$%^&*()\-_=+\[\]{}|;:',.<>?/"
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


class PasswordService:

    @staticmethod
    def hash_password(plain: str) -> str:
        return _pwd_context.hash(plain)

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        return _pwd_context.verify(plain, hashed)

    @staticmethod
    def validate_password_policy(password: str) -> None:
        """Raises ValueError with a descriptive message if password fails policy."""
        errors: list[str] = []
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if len(password) > 128:
            errors.append("Password must not exceed 128 characters.")
        if not re.search(r"[A-Z]", password):
            errors.append("Password must contain at least one uppercase letter.")
        if not re.search(r"\d", password):
            errors.append("Password must contain at least one digit.")
        if not re.search(rf"[{_SPECIAL_CHARS}]", password):
            errors.append("Password must contain at least one special character.")
        if errors:
            raise ValueError(errors[0])  # Surface first error; Pydantic re-raises as ValidationError
```

### Integration with Pydantic schemas (usage pattern for T-025)

```python
from pydantic import BaseModel, field_validator
from src.services.password_service import PasswordService

class RegisterRequest(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def policy(cls, v: str) -> str:
        PasswordService.validate_password_policy(v)
        return v
```

---

## 📝 Completion Log

- [ ] Code implemented
- [ ] Unit tests pass (≥100% on password_service.py)
- [ ] Linter passed
- [ ] No direct `bcrypt` / `passlib` imports anywhere outside this file
