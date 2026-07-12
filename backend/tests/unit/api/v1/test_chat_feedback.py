"""Unit tests for POST /sessions/{id}/messages/{id}/feedback.

Regression cover for the bug where every error branch used ``return problem(...)``
instead of ``raise`` — since ``problem()`` returns an ``HTTPException``, returning
it against ``response_model=_FeedbackResponse`` made FastAPI serialize the
exception and 500 on every non-happy path (bad rating / not-found / forbidden).
These pin the correct 422 / 404 / 403 / 200 contract.
"""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.middleware.error_handler import register_exception_handlers  # noqa: E402
from src.api.v1.chat import router  # noqa: E402
from src.core.database import get_db  # noqa: E402
from src.core.deps import get_current_user  # noqa: E402
from src.models.user import User, UserRole  # noqa: E402

SESSION_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
MESSAGE_ID = uuid.UUID("00000000-0000-0000-0000-000000000020")
USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
URL = f"/chat/sessions/{SESSION_ID}/messages/{MESSAGE_ID}/feedback"


def _user(user_id: uuid.UUID = USER_ID, role: UserRole = UserRole.user) -> User:
    u = MagicMock(spec=User)
    u.id = user_id
    u.role = role
    u.is_active = True
    return u


def _message() -> MagicMock:
    m = MagicMock()
    m.id = MESSAGE_ID
    m.feedback_rating = None
    m.feedback_comment = None
    return m


def _session(user_id: uuid.UUID = USER_ID) -> MagicMock:
    s = MagicMock()
    s.id = SESSION_ID
    s.user_id = user_id
    return s


def _client(db: AsyncMock, user: User) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/chat")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def db() -> AsyncMock:
    d = AsyncMock()
    d.commit = AsyncMock()
    return d


class TestFeedbackContract:
    def test_invalid_rating_returns_422(self, db: AsyncMock) -> None:
        client = _client(db, _user())
        resp = client.post(URL, json={"rating": 0})
        assert resp.status_code == 422
        db.scalar.assert_not_called()  # rejected before any DB access

    def test_message_not_found_returns_404(self, db: AsyncMock) -> None:
        db.scalar = AsyncMock(side_effect=[None])
        client = _client(db, _user())
        resp = client.post(URL, json={"rating": 1})
        assert resp.status_code == 404

    def test_session_not_found_returns_404(self, db: AsyncMock) -> None:
        db.scalar = AsyncMock(side_effect=[_message(), None])
        client = _client(db, _user())
        resp = client.post(URL, json={"rating": -1})
        assert resp.status_code == 404

    def test_non_owner_non_admin_returns_403(self, db: AsyncMock) -> None:
        db.scalar = AsyncMock(side_effect=[_message(), _session(user_id=OTHER_USER_ID)])
        client = _client(db, _user())  # owns nothing; session belongs to OTHER_USER
        resp = client.post(URL, json={"rating": 1})
        assert resp.status_code == 403
        db.commit.assert_not_called()  # no write on the rejected path

    def test_owner_happy_path_returns_200(self, db: AsyncMock) -> None:
        msg = _message()
        db.scalar = AsyncMock(side_effect=[msg, _session(user_id=USER_ID)])
        client = _client(db, _user())
        resp = client.post(URL, json={"rating": 1, "comment": "  helpful  "})
        assert resp.status_code == 200
        body = resp.json()
        assert body["rating"] == 1
        assert body["comment"] == "helpful"  # trimmed
        assert msg.feedback_rating == 1
        db.commit.assert_awaited_once()

    def test_admin_can_feedback_any_session(self, db: AsyncMock) -> None:
        db.scalar = AsyncMock(side_effect=[_message(), _session(user_id=OTHER_USER_ID)])
        client = _client(db, _user(role=UserRole.admin))
        resp = client.post(URL, json={"rating": 1})
        assert resp.status_code == 200
