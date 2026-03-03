"""Helper used in tests to confirm a Langfuse trace was emitted.

Usage::

    from src.services.langfuse_verifier import await_trace

    trace = await await_trace(trace_id, max_wait=30.0)
    assert trace["id"] == trace_id
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "http://localhost:3001")
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")


async def get_trace_by_id(trace_id: str) -> dict[str, Any] | None:
    """Return the Langfuse trace dict for *trace_id*, or ``None`` if not found."""
    url = f"{LANGFUSE_HOST}/api/public/traces/{trace_id}"
    async with httpx.AsyncClient(
        auth=(LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY), timeout=10
    ) as client:
        r = await client.get(url)
        if r.status_code == 200:
            return r.json()
    return None


async def await_trace(
    trace_id: str,
    max_wait: float = 30.0,
    poll_interval: float = 1.0,
) -> dict[str, Any]:
    """Poll Langfuse until *trace_id* is available, then return it.

    Raises :exc:`TimeoutError` if the trace does not appear within *max_wait*
    seconds.
    """
    deadline = asyncio.get_event_loop().time() + max_wait
    while asyncio.get_event_loop().time() < deadline:
        trace = await get_trace_by_id(trace_id)
        if trace is not None:
            return trace
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"Langfuse trace {trace_id!r} not available after {max_wait}s")
