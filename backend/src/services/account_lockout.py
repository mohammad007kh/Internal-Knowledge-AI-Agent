"""Per-email-hash account lockout service.

Layers on top of the per-IP rate limiter (``middleware/rate_limit.py``) to
defeat distributed credential-stuffing botnets that distribute attempts
across many IPs (one attempt per IP bypasses the per-IP rate limit).

The service maintains two Redis keys per email-hash:

* ``lockout:failed:{hash}`` — sorted-set of failure-attempt timestamps.
  Old entries are pruned on every write to keep a sliding window.
* ``lockout:locked:{hash}`` — string key with a TTL.  Existence implies
  the account is locked; the TTL is the remaining lockout time.

Email is hashed (SHA-256, lowercased + trimmed) before being used as a key
so raw email never lands in Redis.

Failure modes
-------------
* If Redis is unreachable and ``LOCKOUT_REQUIRE_REDIS`` is True, the
  ``check`` method raises :class:`RedisUnavailableError` (HTTP 503) so the
  client knows it's a server-side failure (NOT credential-wrong).
* If ``LOCKOUT_REQUIRE_REDIS`` is False, Redis errors are logged and
  silently treated as "not locked" / "no-op" (dev-friendly fail-open).
* ``record_failure`` and ``reset`` always swallow Redis errors — they are
  best-effort writes; the primary login flow must not break because the
  lockout bookkeeping failed.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING

from src.core.exceptions import AccountLockedError, RedisUnavailableError

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.core.config import Settings

logger = logging.getLogger(__name__)


class AccountLockout:
    """Track failed login attempts per email-hash and lock accounts."""

    KEY_FAILED_TEMPLATE = "lockout:failed:{email_hash}"
    KEY_LOCKED_TEMPLATE = "lockout:locked:{email_hash}"

    def __init__(self, redis_client: "Redis | None", settings: "Settings") -> None:
        self._redis = redis_client
        self._max_fails: int = settings.LOCKOUT_MAX_FAILS
        self._window_secs: int = settings.LOCKOUT_WINDOW_SECS
        self._lock_secs: int = settings.LOCKOUT_DURATION_SECS
        self._enabled: bool = settings.LOCKOUT_ENABLED
        self._require_redis: bool = settings.LOCKOUT_REQUIRE_REDIS

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _hash(email: str) -> str:
        """Return the SHA-256 hex digest of *email*, lowercased + trimmed."""
        return hashlib.sha256(email.lower().strip().encode("utf-8")).hexdigest()

    def _failed_key(self, email_hash: str) -> str:
        return self.KEY_FAILED_TEMPLATE.format(email_hash=email_hash)

    def _locked_key(self, email_hash: str) -> str:
        return self.KEY_LOCKED_TEMPLATE.format(email_hash=email_hash)

    def _resolve_redis(self) -> "Redis | None":
        """Return the active Redis client.

        The DI container constructs this service eagerly at app import time,
        but ``redis_client`` in :mod:`src.core.redis` is only populated during
        the lifespan startup hook. We re-resolve from the module on every
        call so the service picks up the live client.
        """
        if self._redis is not None:
            return self._redis
        from src.core import redis as redis_module  # noqa: PLC0415
        return redis_module.redis_client

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    async def check(self, email: str) -> None:
        """Raise :class:`AccountLockedError` if *email* is currently locked.

        On Redis failure:

        * If ``LOCKOUT_REQUIRE_REDIS`` is True, raise
          :class:`RedisUnavailableError` (HTTP 503).
        * Otherwise log a warning and return (treat as not locked).
        """
        if not self._enabled:
            return

        redis = self._resolve_redis()
        if redis is None:
            self._handle_redis_unavailable("check", reason="redis client not initialised")
            return

        email_hash = self._hash(email)
        try:
            ttl = await redis.ttl(self._locked_key(email_hash))
        except Exception as exc:  # noqa: BLE001 - normalise all Redis errors
            self._handle_redis_unavailable("check", reason=str(exc))
            return

        # Redis returns -2 if the key does not exist, -1 if no TTL set.
        if ttl is None or ttl < 0:
            return

        retry_after = int(ttl) if ttl > 0 else self._lock_secs
        raise AccountLockedError(
            "Account temporarily locked due to repeated failed login attempts. "
            f"Try again in {retry_after} seconds.",
            extra={"retry_after_seconds": retry_after},
        )

    async def record_failure(self, email: str) -> None:
        """Record a failed login attempt and lock if threshold reached.

        Implemented atomically with a Redis pipeline:

        1. ``ZADD`` the current timestamp to the failed-attempts sorted-set.
        2. ``ZREMRANGEBYSCORE`` to drop entries older than the window.
        3. ``ZCARD`` to count remaining entries.
        4. ``EXPIRE`` to keep the sorted-set bounded.

        If the count is at or above ``LOCKOUT_MAX_FAILS``, a second call
        (``SET`` with TTL) flips the locked-key on. Splitting the lock-write
        from the pipeline keeps the count check race-free.

        Best-effort: Redis errors are logged but never raised.
        """
        if not self._enabled:
            return

        redis = self._resolve_redis()
        if redis is None:
            logger.warning(
                "AccountLockout.record_failure: redis client not initialised; skipping",
            )
            return

        email_hash = self._hash(email)
        failed_key = self._failed_key(email_hash)
        locked_key = self._locked_key(email_hash)
        now = time.time()
        window_start = now - self._window_secs

        try:
            async with redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(failed_key, 0, window_start)
                pipe.zadd(failed_key, {str(now): now})
                pipe.zcard(failed_key)
                pipe.expire(failed_key, self._window_secs)
                results = await pipe.execute()
            count = int(results[2]) if results and len(results) > 2 else 0

            if count >= self._max_fails:
                await redis.set(locked_key, "1", ex=self._lock_secs)
                logger.warning(
                    "Account locked after %d failures within %ds (email_hash=%s...)",
                    count,
                    self._window_secs,
                    email_hash[:12],
                )
        except Exception as exc:  # noqa: BLE001 - best-effort
            logger.warning(
                "AccountLockout.record_failure: redis error: %s", exc,
            )

    async def reset(self, email: str) -> None:
        """Clear the failure counter and locked-key on successful login.

        Best-effort: Redis errors are logged and ignored.
        """
        if not self._enabled:
            return

        redis = self._resolve_redis()
        if redis is None:
            logger.warning(
                "AccountLockout.reset: redis client not initialised; skipping",
            )
            return

        email_hash = self._hash(email)
        try:
            await redis.delete(
                self._failed_key(email_hash),
                self._locked_key(email_hash),
            )
        except Exception as exc:  # noqa: BLE001 - best-effort
            logger.warning("AccountLockout.reset: redis error: %s", exc)

    # ------------------------------------------------------------------ #
    # Internal                                                            #
    # ------------------------------------------------------------------ #

    def _handle_redis_unavailable(self, op: str, *, reason: str) -> None:
        """Centralised policy for "Redis is down during ``check``".

        In strict mode (``LOCKOUT_REQUIRE_REDIS=True``) this raises so the
        endpoint returns HTTP 503. In lenient mode it logs and returns so
        the login flow continues (treating the account as not-locked).
        """
        if self._require_redis:
            logger.error(
                "AccountLockout.%s: redis unavailable in strict mode: %s",
                op,
                reason,
            )
            raise RedisUnavailableError(
                "Authentication service is temporarily unavailable. "
                "Please retry shortly.",
            )
        logger.warning(
            "AccountLockout.%s: redis unavailable in lenient mode (%s); "
            "treating as not locked",
            op,
            reason,
        )
