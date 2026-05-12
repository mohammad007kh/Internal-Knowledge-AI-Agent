"""Unit tests for the redesigned ``/api/v1/analytics`` aggregation endpoints.

Covers the seven v2 routes end-to-end via FastAPI ``TestClient`` with the
:class:`AnalyticsRepository` replaced by a mock (no live DB needed).  We
assert, per endpoint:

  * happy path — response shape matches the Pydantic schema, with seeded
    values flowing through;
  * the ``range`` query param is forwarded to the repo as the right window
    (``timedelta``) — and bad tokens are rejected with 422;
  * gap-fill produces a *continuous* daily series (the repo is responsible,
    but the route must pass it through unmangled);
  * AdminOnly is enforced — non-admin → 403, unauthenticated → 401.

In addition there are pure-function tests for the repo's range mapping and
day-series gap-fill helper, which need no app at all.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# Required env vars must be set before importing src modules.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware.error_handler import register_exception_handlers
from src.api.v1.analytics import AdminOnly, _analytics_repo
from src.api.v1.analytics import router as analytics_router
from src.core.exceptions import ForbiddenError, UnauthorizedError
from src.models.user import User, UserRole
from src.repositories.analytics_repository import (
    RANGE_TO_DELTA,
    AnalyticsRepository,
    resolve_range,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_user(role: UserRole = UserRole.admin) -> User:
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.email = "admin@example.com"
    user.role = role
    user.is_active = True
    return user


def _make_repo() -> MagicMock:
    """Mock AnalyticsRepository with every method stubbed to a sane default."""
    repo = MagicMock(spec=AnalyticsRepository)
    repo.chat_messages_kpi = AsyncMock(return_value={"count": 12, "previous_count": 10})
    repo.feedback_kpi = AsyncMock(
        return_value={"answered": 8, "rated": 5, "up": 4, "down": 1}
    )
    repo.sources_kpi = AsyncMock(
        return_value={
            "active": 6,
            "failed_connections": 1,
            "by_connection_status": [
                {"status": "healthy", "count": 5},
                {"status": "failed", "count": 1},
            ],
        }
    )
    repo.sync_kpi = AsyncMock(return_value={"total": 10, "success": 9, "failed": 1})
    repo.schema_studies_kpi = AsyncMock(
        return_value={
            "ready": 2,
            "failed": 1,
            "stale": 0,
            "by_state": [{"key": "READY", "count": 2}, {"key": "COLUMNS_FAILED", "count": 1}],
        }
    )
    repo.privileged_actions_today = AsyncMock(return_value=3)
    repo.chat_volume_daily = AsyncMock(
        return_value=[
            {"date": date(2026, 5, 10), "count": 0},
            {"date": date(2026, 5, 11), "count": 5},
            {"date": date(2026, 5, 12), "count": 3},
        ]
    )
    repo.feedback_trend_daily = AsyncMock(
        return_value=[
            {"date": date(2026, 5, 11), "answered": 4, "up": 2, "down": 1},
            {"date": date(2026, 5, 12), "answered": 0, "up": 0, "down": 0},
        ]
    )
    repo.sync_activity_daily = AsyncMock(
        return_value=[
            {"date": date(2026, 5, 11), "success": 2, "failed": 0, "documents": 12, "chunks": 40},
            {"date": date(2026, 5, 12), "success": 0, "failed": 1, "documents": 0, "chunks": 0},
        ]
    )
    repo.source_health = AsyncMock(
        return_value={
            "by_type": [{"type": "web_url", "count": 3}, {"type": "database", "count": 2}],
            "by_connection_status": [{"status": "healthy", "count": 4}],
            "by_status": [{"status": "active", "count": 5}],
        }
    )
    repo.schema_studies_breakdown = AsyncMock(
        return_value={
            "by_schema_status": [{"status": "READY", "count": 2}, {"status": "FAILED", "count": 1}],
            "recent_failures": [
                {
                    "source_id": uuid4(),
                    "source_name": "Prod DB",
                    "last_error_phase": "COLUMNS",
                    "last_error_message": "permission denied",
                    "finished_at": datetime(2026, 5, 11, 9, 0, tzinfo=UTC),
                }
            ],
        }
    )
    repo.needs_attention = AsyncMock(
        return_value=[
            {"source_id": uuid4(), "name": "Prod DB", "kind": "connection", "detail": "timeout"},
            {"source_id": uuid4(), "name": "Wiki", "kind": "sync", "detail": "404"},
        ]
    )
    return repo


@pytest.fixture()
def admin_client():
    """TestClient: admin bypassed, AnalyticsRepository replaced by a mock."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(analytics_router)

    admin = _make_user(UserRole.admin)
    repo = _make_repo()
    app.dependency_overrides[AdminOnly] = lambda: admin
    app.dependency_overrides[_analytics_repo] = lambda: repo

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc, repo


@pytest.fixture()
def forbidden_client():
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(analytics_router)

    def _forbidden() -> User:
        raise ForbiddenError("Requires role: admin")

    app.dependency_overrides[AdminOnly] = _forbidden
    app.dependency_overrides[_analytics_repo] = lambda: _make_repo()

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


@pytest.fixture()
def unauth_client():
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(analytics_router)

    def _unauth() -> User:
        raise UnauthorizedError("No Bearer token provided")

    app.dependency_overrides[AdminOnly] = _unauth
    app.dependency_overrides[_analytics_repo] = lambda: _make_repo()

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


# ---------------------------------------------------------------------------
# Repo pure helpers
# ---------------------------------------------------------------------------


class TestRangeMapping:
    @pytest.mark.parametrize(
        ("token", "expected"),
        [
            ("24h", timedelta(hours=24)),
            ("7d", timedelta(days=7)),
            ("30d", timedelta(days=30)),
            ("90d", timedelta(days=90)),
        ],
    )
    def test_known_tokens(self, token: str, expected: timedelta) -> None:
        assert resolve_range(token) == expected

    def test_unknown_token_defaults_to_7d(self) -> None:
        assert resolve_range("bogus") == RANGE_TO_DELTA["7d"]

    def test_day_series_is_inclusive_and_continuous(self) -> None:
        from src.repositories.analytics_repository import _day_series

        since = datetime(2026, 5, 10, 14, 30, tzinfo=UTC)
        until = datetime(2026, 5, 13, 1, 0, tzinfo=UTC)
        series = _day_series(since, until)
        assert series == [
            date(2026, 5, 10),
            date(2026, 5, 11),
            date(2026, 5, 12),
            date(2026, 5, 13),
        ]
        # Strictly increasing, no gaps.
        for a, b in zip(series, series[1:]):
            assert (b - a).days == 1


# ---------------------------------------------------------------------------
# /analytics/overview
# ---------------------------------------------------------------------------


class TestOverview:
    def test_happy_path_bundles_six_kpis(self, admin_client) -> None:
        tc, repo = admin_client
        resp = tc.get("/analytics/overview", params={"range": "7d"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["range"] == "7d"
        # chat-messages delta = (12 - 10) / 10 * 100 = 20.0
        assert body["chat_messages"] == {
            "count": 12,
            "previous_count": 10,
            "delta_pct": 20.0,
        }
        # feedback up_rate = 4 / 5 = 0.8
        assert body["feedback"]["up_rate"] == 0.8
        assert body["feedback"]["answered"] == 8
        assert body["sources"]["active"] == 6
        assert body["sources"]["failed_connections"] == 1
        # sync success_rate = 9 / 10 = 0.9
        assert body["sync"]["success_rate"] == 0.9
        assert body["schema_studies"]["ready"] == 2
        assert body["schema_studies"]["failed"] == 1
        assert body["privileged_actions_today"] == 3
        # window forwarded as 7d
        repo.chat_messages_kpi.assert_awaited_once_with(timedelta(days=7))

    def test_default_range_is_7d(self, admin_client) -> None:
        tc, repo = admin_client
        resp = tc.get("/analytics/overview")
        assert resp.status_code == 200
        assert resp.json()["range"] == "7d"
        repo.sync_kpi.assert_awaited_once_with(timedelta(days=7))

    def test_range_param_forwarded_as_window(self, admin_client) -> None:
        tc, repo = admin_client
        resp = tc.get("/analytics/overview", params={"range": "90d"})
        assert resp.status_code == 200
        repo.chat_messages_kpi.assert_awaited_once_with(timedelta(days=90))

    def test_zero_denominators_yield_null_rates(self, admin_client) -> None:
        tc, repo = admin_client
        repo.chat_messages_kpi.return_value = {"count": 0, "previous_count": 0}
        repo.feedback_kpi.return_value = {"answered": 0, "rated": 0, "up": 0, "down": 0}
        repo.sync_kpi.return_value = {"total": 0, "success": 0, "failed": 0}
        resp = tc.get("/analytics/overview")
        assert resp.status_code == 200
        body = resp.json()
        assert body["chat_messages"]["delta_pct"] is None
        assert body["feedback"]["up_rate"] is None
        assert body["sync"]["success_rate"] is None

    def test_bad_range_token_returns_422(self, admin_client) -> None:
        tc, _repo = admin_client
        resp = tc.get("/analytics/overview", params={"range": "1y"})
        assert resp.status_code == 422

    def test_non_admin_403(self, forbidden_client) -> None:
        assert forbidden_client.get("/analytics/overview").status_code == 403

    def test_unauthenticated_401(self, unauth_client) -> None:
        assert unauth_client.get("/analytics/overview").status_code == 401


# ---------------------------------------------------------------------------
# Time-series endpoints
# ---------------------------------------------------------------------------


class TestChatVolume:
    def test_happy_path_continuous_series(self, admin_client) -> None:
        tc, repo = admin_client
        resp = tc.get("/analytics/chat-volume", params={"range": "30d"})
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert [r["count"] for r in rows] == [0, 5, 3]
        # day strings parse and are consecutive (gap-fill contract).
        dates = [date.fromisoformat(r["date"]) for r in rows]
        for a, b in zip(dates, dates[1:]):
            assert (b - a).days == 1
        repo.chat_volume_daily.assert_awaited_once_with(timedelta(days=30))

    def test_default_range_30d(self, admin_client) -> None:
        tc, repo = admin_client
        assert tc.get("/analytics/chat-volume").status_code == 200
        repo.chat_volume_daily.assert_awaited_once_with(timedelta(days=30))

    def test_bad_range_422(self, admin_client) -> None:
        tc, _repo = admin_client
        assert tc.get("/analytics/chat-volume", params={"range": "x"}).status_code == 422

    def test_non_admin_403(self, forbidden_client) -> None:
        assert forbidden_client.get("/analytics/chat-volume").status_code == 403

    def test_unauthenticated_401(self, unauth_client) -> None:
        assert unauth_client.get("/analytics/chat-volume").status_code == 401


class TestFeedbackTrend:
    def test_happy_path(self, admin_client) -> None:
        tc, repo = admin_client
        resp = tc.get("/analytics/feedback-trend", params={"range": "24h"})
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert rows[0] == {"date": "2026-05-11", "answered": 4, "up": 2, "down": 1}
        assert rows[1]["answered"] == 0
        repo.feedback_trend_daily.assert_awaited_once_with(timedelta(hours=24))

    def test_non_admin_403(self, forbidden_client) -> None:
        assert forbidden_client.get("/analytics/feedback-trend").status_code == 403


class TestSyncActivity:
    def test_happy_path(self, admin_client) -> None:
        tc, repo = admin_client
        resp = tc.get("/analytics/sync-activity", params={"range": "7d"})
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert rows[0] == {
            "date": "2026-05-11",
            "success": 2,
            "failed": 0,
            "documents": 12,
            "chunks": 40,
        }
        repo.sync_activity_daily.assert_awaited_once_with(timedelta(days=7))

    def test_non_admin_403(self, forbidden_client) -> None:
        assert forbidden_client.get("/analytics/sync-activity").status_code == 403


# ---------------------------------------------------------------------------
# Snapshot endpoints (no range param)
# ---------------------------------------------------------------------------


class TestSourceHealth:
    def test_happy_path(self, admin_client) -> None:
        tc, _repo = admin_client
        resp = tc.get("/analytics/source-health")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert {"type": "web_url", "count": 3} in body["by_type"]
        assert body["by_connection_status"] == [{"status": "healthy", "count": 4}]
        assert body["by_status"] == [{"status": "active", "count": 5}]

    def test_ignores_range_param(self, admin_client) -> None:
        tc, _repo = admin_client
        # extra ?range= is harmless — not a declared param, FastAPI ignores it.
        assert tc.get("/analytics/source-health", params={"range": "90d"}).status_code == 200

    def test_non_admin_403(self, forbidden_client) -> None:
        assert forbidden_client.get("/analytics/source-health").status_code == 403

    def test_unauthenticated_401(self, unauth_client) -> None:
        assert unauth_client.get("/analytics/source-health").status_code == 401


class TestSchemaStudies:
    def test_happy_path(self, admin_client) -> None:
        tc, _repo = admin_client
        resp = tc.get("/analytics/schema-studies")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert {"status": "READY", "count": 2} in body["by_schema_status"]
        assert len(body["recent_failures"]) == 1
        rf = body["recent_failures"][0]
        assert rf["source_name"] == "Prod DB"
        assert rf["last_error_phase"] == "COLUMNS"

    def test_non_admin_403(self, forbidden_client) -> None:
        assert forbidden_client.get("/analytics/schema-studies").status_code == 403


class TestNeedsAttention:
    def test_happy_path(self, admin_client) -> None:
        tc, repo = admin_client
        resp = tc.get("/analytics/needs-attention")
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert len(rows) == 2
        assert {r["kind"] for r in rows} == {"connection", "sync"}
        repo.needs_attention.assert_awaited_once_with(limit=8)

    def test_empty_is_valid(self, admin_client) -> None:
        tc, repo = admin_client
        repo.needs_attention.return_value = []
        resp = tc.get("/analytics/needs-attention")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_non_admin_403(self, forbidden_client) -> None:
        assert forbidden_client.get("/analytics/needs-attention").status_code == 403

    def test_unauthenticated_401(self, unauth_client) -> None:
        assert unauth_client.get("/analytics/needs-attention").status_code == 401
