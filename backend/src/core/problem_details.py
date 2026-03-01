"""RFC 7807 ``problem`` helper.

Returns a :class:`fastapi.HTTPException` with a structured JSON body that
follows the Problem Details for HTTP APIs specification (RFC 7807).

Usage::

    raise problem(status=404, title="Not Found", detail="Source 'x' not found.")
"""
from __future__ import annotations

from fastapi import HTTPException


def problem(
    *,
    status: int,
    title: str,
    detail: str,
    type_: str = "about:blank",
    instance: str | None = None,
) -> HTTPException:
    """Build an RFC-7807-compliant :class:`~fastapi.HTTPException`.

    Args:
        status: HTTP status code.
        title: Short, human-readable summary of the problem.
        detail: Human-readable explanation specific to this occurrence.
        type_: URI reference identifying the problem type (default ``about:blank``).
        instance: URI reference identifying the specific occurrence.

    Returns:
        An :class:`~fastapi.HTTPException` whose ``detail`` is the problem body dict.
    """
    body: dict[str, object] = {
        "type": type_,
        "title": title,
        "status": status,
        "detail": detail,
    }
    if instance is not None:
        body["instance"] = instance
    return HTTPException(status_code=status, detail=body)
