"""Canonical credential / DSN redaction (FR-020).

A single hardened redactor shared by every site that may surface a database
driver exception or connection string in a log line, audit record, or
user-facing error envelope. Driver libraries (asyncpg / SQLAlchemy / pymongo)
freely embed the connection string or DSN fragments
(``scheme://user:pass@host`` URLs, ``password=...`` / ``host=...`` key-value
pairs, bare ``host:port``) in ``str(exc)``. None of those may ever escape — a
scrubbed message is fine, a leaked one is a credential breach. We therefore
over-redact on purpose.

This module is the ONE source of truth. Historically ~8 modules each carried a
private ``_sanitise`` / ``_sanitize_error_message`` copy; several had drifted
to a *leaky* URL regex (``://[^@\\s]+@`` / ``://[^@\\s/]+@``) that stops at the
FIRST ``@`` and therefore leaks the tail of a password that itself contains an
``@`` (a common credential character): ``user:p@ss@host`` would collapse to
``***@ss@host``, exposing ``ss``. Every caller now delegates here so that class
of bug cannot reappear.

Redaction order matters — do NOT reorder:

1. **URL credentials FIRST** — ``://[^/\\s]*@`` is greedy up to the LAST ``@``
   before a ``/`` or whitespace, so an ``@``-containing password is fully
   stripped (``://user:p@ss@host/db`` → ``://***@host/db``, never
   ``://***@ss@host/db``). Collapsing the authority first also prevents the
   bare ``host:port`` pass below from matching a ``host:port`` *inside* the
   authority.
2. **DSN ``key=value`` fragments** — host/db/user/credential keywords.
3. **Bare ``host:port``** — only fires on a colon-separated 2-5 digit port, so
   it will not eat ``"line 12:34"``.
"""

from __future__ import annotations

import re
from typing import Final

#: ``scheme://user:pass@host`` → ``scheme://***@host``. Greedy to the LAST
#: ``@`` before a ``/`` or whitespace so passwords containing ``@`` are fully
#: redacted, e.g. ``://user:p@ss@host/db`` → ``://***@host/db`` (NOT
#: ``://***@ss@host/db``, which would leak ``ss``).
_CRED_URL_RE: Final[re.Pattern[str]] = re.compile(r"://[^/\s]*@")

#: DSN-style ``key=value`` fragments that name host/db/user/credentials.
_DSN_KV_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(host|hostaddr|port|dbname|database|user|username|password|passwd)\s*=\s*"
    r"('[^']*'|\"[^\"]*\"|\S+)",
    re.IGNORECASE,
)

#: A bare ``hostname:port`` (2-5 digit port). Only fires when a colon-separated
#: port is present, so it won't eat ``"line 12:34"``.
_HOST_PORT_RE: Final[re.Pattern[str]] = re.compile(r"\b[\w.-]+:\d{2,5}\b")


def redact_dsn(message: object) -> str:
    """Redact credentials / host / db-name fragments from an error message.

    Order matters (see module docstring): redact URL credentials FIRST so the
    authority is collapsed to ``://***@`` before the bare ``host:port`` pass
    could match a ``host:port`` *inside* that authority; the greedy
    ``://[^/\\s]*@`` also guarantees an ``@``-containing password is fully
    stripped rather than leaking its tail. Then strip DSN ``key=value``
    fragments, then collapse any remaining bare ``host:port``.

    The function is idempotent: ``redact_dsn(redact_dsn(x)) == redact_dsn(x)``.

    Args:
        message: Any object; coerced with ``str()`` before scrubbing so callers
            can pass an exception instance directly.

    Returns:
        The scrubbed text with credential / topology fragments replaced by
        ``://***@``, ``key=<redacted>``, and ``<host>:<port>`` markers.
    """
    text = str(message)
    text = _CRED_URL_RE.sub("://***@", text)
    text = _DSN_KV_RE.sub(lambda m: f"{m.group(1).lower()}=<redacted>", text)
    text = _HOST_PORT_RE.sub("<host>:<port>", text)
    return text
