"""Specific failure-mode exceptions for the web-URL connector (FX25).

Every realistic failure surfaces a distinct, user-visible reason.  The sync
orchestrator (``tasks.sync_source``) recognises :class:`WebUrlFetchError` and
stamps ``sync_job.error_message`` with the exception's ``user_message``
verbatim, so the Source-detail UI surfaces the same string an admin will
need to act on it.

These errors are *permanent* by design — retrying a 404, an SSRF block, or
a page with no readable content will not help.  The orchestrator therefore
skips its retry loop when it sees a :class:`WebUrlFetchError`.
"""
from __future__ import annotations

from enum import Enum


class WebUrlFetchReason(str, Enum):
    """Stable identifiers for each failure mode (useful for tests + metrics)."""

    BLOCKED_ADDRESS = "blocked_address"
    DNS_FAILURE = "dns_failure"
    CONNECTION_REFUSED = "connection_refused"
    TIMEOUT = "timeout"
    HTTP_CLIENT_ERROR = "http_client_error"
    HTTP_AUTH_REQUIRED = "http_auth_required"
    HTTP_SERVER_ERROR = "http_server_error"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    CONTENT_TOO_LARGE = "content_too_large"
    CROSS_DOMAIN_REDIRECT = "cross_domain_redirect"
    EMPTY_CONTENT = "empty_content"
    UNSUPPORTED_CRAWL_MODE = "unsupported_crawl_mode"


class WebUrlFetchError(Exception):
    """Base class for every distinct user-visible web-URL fetch failure.

    Attributes:
        reason: Stable enum identifier of the failure mode.
        user_message: The exact string the Source-detail UI will show.
                      Already sanitised of credentials / request internals.
        permanent: When ``True`` (the default for all subclasses defined
                   here) the sync orchestrator skips its retry loop.
    """

    reason: WebUrlFetchReason
    permanent: bool = True

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


# ---------------------------------------------------------------------------
# Concrete subclasses
# ---------------------------------------------------------------------------


class BlockedAddressError(WebUrlFetchError):
    """SSRF guard rejected the URL (private / loopback / metadata IP)."""

    reason = WebUrlFetchReason.BLOCKED_ADDRESS

    def __init__(self) -> None:
        super().__init__(
            "This URL points at a private/internal address and was blocked "
            "for security reasons."
        )


class DnsResolutionError(WebUrlFetchError):
    """The hostname does not resolve via DNS."""

    reason = WebUrlFetchReason.DNS_FAILURE

    def __init__(self, host: str) -> None:
        super().__init__(
            f"The hostname '{host}' could not be resolved. Check the URL."
        )


class ConnectionRefusedError(WebUrlFetchError):
    """Connection refused / reset / network unreachable."""

    reason = WebUrlFetchReason.CONNECTION_REFUSED

    def __init__(self) -> None:
        super().__init__("The server refused the connection.")


class RequestTimeoutError(WebUrlFetchError):
    """Request exceeded the 15-second total budget."""

    reason = WebUrlFetchReason.TIMEOUT

    def __init__(self, timeout_seconds: float) -> None:
        super().__init__(
            f"The site took longer than {int(timeout_seconds)} seconds to respond."
        )


class HttpClientError(WebUrlFetchError):
    """HTTP 4xx response that is NOT an auth wall (401/403)."""

    reason = WebUrlFetchReason.HTTP_CLIENT_ERROR

    def __init__(self, status: int, reason_phrase: str) -> None:
        phrase = reason_phrase or "Client Error"
        super().__init__(f"The URL returned {status} {phrase}.")


class HttpAuthRequiredError(WebUrlFetchError):
    """HTTP 401 or 403 — page is behind a login wall."""

    reason = WebUrlFetchReason.HTTP_AUTH_REQUIRED

    def __init__(self, status: int) -> None:
        super().__init__(
            f"Authentication required ({status}) — this page is behind a login wall."
        )


class HttpServerError(WebUrlFetchError):
    """HTTP 5xx response."""

    reason = WebUrlFetchReason.HTTP_SERVER_ERROR

    def __init__(self, status: int) -> None:
        super().__init__(
            f"The site is currently returning a server error ({status})."
        )


class UnsupportedContentTypeError(WebUrlFetchError):
    """Response is not text/html (PDF, JSON, image, …)."""

    reason = WebUrlFetchReason.UNSUPPORTED_CONTENT_TYPE

    def __init__(self, content_type: str) -> None:
        ct = content_type.strip() or "an unknown content type"
        hint = ""
        lower = ct.lower()
        if "pdf" in lower:
            hint = " Use a file upload for PDFs."
        elif "json" in lower or "xml" in lower:
            hint = " Use a database source for API endpoints."
        super().__init__(
            f"This URL serves {ct}, not a web page.{hint}"
        )


class ContentTooLargeError(WebUrlFetchError):
    """Response body exceeds the configured size limit."""

    reason = WebUrlFetchReason.CONTENT_TOO_LARGE

    def __init__(self, max_bytes: int) -> None:
        mb = max_bytes // (1024 * 1024)
        super().__init__(
            f"The page is larger than {mb}MB and was not downloaded."
        )


class CrossDomainRedirectError(WebUrlFetchError):
    """Final URL host differs from the originally requested host."""

    reason = WebUrlFetchReason.CROSS_DOMAIN_REDIRECT

    def __init__(self, final_host: str) -> None:
        super().__init__(
            f"The URL redirected to {final_host}. Re-add the source with "
            f"the final URL if intended."
        )


class EmptyContentError(WebUrlFetchError):
    """trafilatura + readability both yielded less than 200 chars."""

    reason = WebUrlFetchReason.EMPTY_CONTENT

    def __init__(self) -> None:
        super().__init__(
            "The page rendered but no readable text could be extracted — "
            "common for JavaScript-only sites, login walls, or paywalls."
        )


class UnsupportedCrawlModeError(WebUrlFetchError):
    """Caller asked for a crawl mode other than ``single``."""

    reason = WebUrlFetchReason.UNSUPPORTED_CRAWL_MODE

    def __init__(self, mode: str) -> None:
        super().__init__(
            f"Unsupported crawl_mode '{mode}'. Only 'single' is supported "
            f"today. Recursive crawling is not yet implemented."
        )
