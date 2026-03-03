"""T-098: Langfuse trace emission tests.

Covers:
* Each pipeline run emits a trace visible in the Langfuse API.
* The trace reports non-zero token usage.
* Two consecutive pipeline runs produce two *distinct* trace IDs.

All tests are guarded by ``RUN_INTEGRATION_TESTS=1`` and skipped
automatically when Langfuse is unreachable.
"""
from __future__ import annotations

import json
import os

import pytest

_INTEGRATION = os.environ.get("RUN_INTEGRATION_TESTS", "0") == "1"

LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "http://localhost:3001")

if _INTEGRATION:
    import httpx

    from src.services.langfuse_verifier import await_trace

    @pytest.fixture(scope="module", autouse=True)
    def check_langfuse_reachable():
        """Skip the entire module when Langfuse is unreachable."""
        try:
            r = httpx.get(f"{LANGFUSE_HOST}/api/public/health", timeout=5)
            if r.status_code != 200:
                pytest.skip("Langfuse health endpoint returned non-200")
        except Exception:
            pytest.skip("Langfuse not reachable — skipping trace tests")

    def _parse_trace_id_from_sse(body: bytes) -> str:
        """Extract ``trace_id`` from the SSE *done* event payload."""
        for line in body.decode().splitlines():
            if line.startswith("data: "):
                try:
                    payload = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if payload.get("event") == "done":
                    return payload["data"]["trace_id"]
        raise ValueError("No 'done' event with trace_id found in SSE stream")

    @pytest.mark.asyncio
    async def test_pipeline_run_emits_langfuse_trace(client, user_token):
        r = await client.post(
            "/api/v1/chat/sessions",
            json={"title": "trace-test"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        r.raise_for_status()
        session_id = r.json()["id"]

        async with client.stream(
            "POST",
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"content": "What is AI?"},
            headers={"Authorization": f"Bearer {user_token}"},
        ) as resp:
            resp.raise_for_status()
            body = await resp.aread()

        trace_id = _parse_trace_id_from_sse(body)
        assert trace_id, "trace_id must be non-empty"

        trace = await await_trace(trace_id, max_wait=30.0)
        assert trace["id"] == trace_id

    @pytest.mark.asyncio
    async def test_trace_has_non_zero_token_usage(client, user_token):
        r = await client.post(
            "/api/v1/chat/sessions",
            json={"title": "token-usage-test"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        r.raise_for_status()
        session_id = r.json()["id"]

        async with client.stream(
            "POST",
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"content": "What is AI?"},
            headers={"Authorization": f"Bearer {user_token}"},
        ) as resp:
            body = await resp.aread()

        trace_id = _parse_trace_id_from_sse(body)
        trace = await await_trace(trace_id, max_wait=30.0)

        usage = trace.get("usage") or {}
        total = usage.get("totalTokens") or trace.get("totalTokens", 0)
        assert total > 0, f"Expected non-zero token usage, got trace={trace!r}"

    @pytest.mark.asyncio
    async def test_each_pipeline_run_creates_distinct_trace(client, user_token):
        r = await client.post(
            "/api/v1/chat/sessions",
            json={"title": "distinct-traces-test"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        r.raise_for_status()
        session_id = r.json()["id"]

        trace_ids: list[str] = []
        for _ in range(2):
            async with client.stream(
                "POST",
                f"/api/v1/chat/sessions/{session_id}/messages",
                json={"content": "Hello"},
                headers={"Authorization": f"Bearer {user_token}"},
            ) as resp:
                body = await resp.aread()
            trace_ids.append(_parse_trace_id_from_sse(body))

        assert trace_ids[0] != trace_ids[1], (
            f"Expected two distinct trace IDs, got {trace_ids}"
        )
