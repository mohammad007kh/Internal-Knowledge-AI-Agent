"""One-time bootstrap of the first admin account from env vars (FR-024).

Called during FastAPI lifespan (after migrations).  If
``BOOTSTRAP_ADMIN_EMAIL`` / ``BOOTSTRAP_ADMIN_PASSWORD`` are unset, the
function silently returns so that the application can start without them.
"""

import logging

from sqlalchemy import func, select

from src.core.config import settings
from src.core.database import AsyncSessionLocal as async_session_factory
from src.models.user import User, UserRole
from src.services.password_service import PasswordService

logger = logging.getLogger(__name__)


async def bootstrap_admin() -> None:
    """Create the very first admin user if the ``users`` table is empty.

    * Reads credentials from ``settings.BOOTSTRAP_ADMIN_EMAIL`` and
      ``settings.BOOTSTRAP_ADMIN_PASSWORD``.
    * Skips (with a warning) when either value is ``None`` or empty.
    * Skips (with an info log) when at least one user already exists.
    * Validates the password against ``PasswordService.validate_password_policy``
      and raises ``ValueError`` at startup if the password is too weak.
    * Wraps the insert in a DB transaction — rolls back on any error.
    """
    email = settings.BOOTSTRAP_ADMIN_EMAIL
    password = settings.BOOTSTRAP_ADMIN_PASSWORD

    if not email or not password:
        logger.warning(
            "BOOTSTRAP_ADMIN_EMAIL or BOOTSTRAP_ADMIN_PASSWORD not set "
            "— skipping admin bootstrap."
        )
        return

    # Fail-fast if the password violates policy (before touching the DB).
    try:
        PasswordService.validate_password_policy(password)
    except (ValueError,) as exc:
        logger.error(
            "Bootstrap admin password does not meet policy: %s. "
            "Fix BOOTSTRAP_ADMIN_PASSWORD and restart.",
            exc,
        )
        raise

    async with async_session_factory() as session:
        async with session.begin():
            count_result = await session.execute(
                select(func.count()).select_from(User)
            )
            user_count = count_result.scalar_one()

            if user_count > 0:
                logger.info(
                    "Bootstrap skipped — %d user(s) already exist.",
                    user_count,
                )
                return

            hashed = PasswordService.hash_password(password)
            admin = User(
                email=email,
                hashed_password=hashed,
                full_name="Admin",
                role=UserRole.admin,
                is_active=True,
                must_change_password=True,
            )
            session.add(admin)

        logger.info("Bootstrap admin created: %s", email)
