from dependency_injector import containers, providers

from src.connectors.factory import ConnectorFactory
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.repositories.chunk_repository import ChunkRepository
from src.repositories.document_repository import DocumentRepository
from src.repositories.invitation_repository import InvitationRepository
from src.repositories.refresh_token_repository import RefreshTokenRepository
from src.repositories.source_permission_repository import SourcePermissionRepository
from src.repositories.source_repository import SourceRepository
from src.repositories.sync_job_repository import SyncJobRepository
from src.repositories.user_repository import UserRepository
from src.services.auth_service import AuthService
from src.services.email_service import EmailService
from src.services.password_service import PasswordService
from src.services.source_permission_service import SourcePermissionService
from src.services.source_service import SourceService
from src.services.sync_job_service import SyncJobService
from src.services.user_service import UserService


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(packages=["src.api"])

    config = providers.Object(settings)
    db_session_factory = providers.Factory(lambda: AsyncSessionLocal)

    # ── Repositories ────────────────────────────────────────────────
    user_repo = providers.Factory(UserRepository, session=db_session_factory)
    invitation_repo = providers.Factory(InvitationRepository, session=db_session_factory)
    refresh_token_repo = providers.Factory(
        RefreshTokenRepository, session=db_session_factory,
    )
    source_repo = providers.Factory(SourceRepository, session=db_session_factory)
    document_repo = providers.Factory(DocumentRepository, session=db_session_factory)
    chunk_repo = providers.Factory(ChunkRepository, session=db_session_factory)
    source_permission_repo = providers.Factory(
        SourcePermissionRepository, session=db_session_factory
    )
    sync_job_repo = providers.Factory(SyncJobRepository, session=db_session_factory)

    # ── Services ────────────────────────────────────────────────────
    password_service = providers.Factory(PasswordService)
    email_service = providers.Factory(EmailService)
    user_service = providers.Factory(
        UserService,
        user_repo=user_repo,
        invitation_repo=invitation_repo,
        password_service=password_service,
        refresh_token_repo=refresh_token_repo,
        email_service=email_service,
    )
    auth_service = providers.Factory(
        AuthService,
        user_repo=user_repo,
        refresh_repo=refresh_token_repo,
        user_service=user_service,
        password_service=password_service,
    )
    source_service = providers.Factory(
        SourceService,
        source_repo=source_repo,
        settings=config,
        connector_factory=providers.Singleton(ConnectorFactory),
    )
    source_permission_service = providers.Factory(
        SourcePermissionService,
        source_permission_repo=source_permission_repo,
        source_repo=source_repo,
        user_repo=user_repo,
    )
    sync_job_service = providers.Factory(
        SyncJobService,
        session_factory=db_session_factory,
        sync_job_repo=sync_job_repo,
    )


container = Container()
