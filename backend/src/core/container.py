from typing import Any

from dependency_injector import containers, providers
from openai import AsyncOpenAI

from src.agent.pipeline import build_pipeline
from src.connectors.factory import ConnectorFactory
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.repositories.admin_audit_log_repository import AdminAuditLogRepository
from src.repositories.ai_model_repository import AIModelRepository
from src.repositories.chat_repository import ChatMessageRepository, ChatSessionRepository
from src.repositories.chunk_repository import ChunkRepository
from src.repositories.company_policy_repository import CompanyPolicyRepository
from src.repositories.connector_repository import ConnectorRepository
from src.repositories.document_repository import DocumentRepository
from src.repositories.embedder_repository import EmbedderRepository
from src.repositories.invitation_repository import InvitationRepository
from src.repositories.llm_config_repository import LLMConfigRepository
from src.repositories.refresh_token_repository import RefreshTokenRepository
from src.repositories.source_permission_repository import SourcePermissionRepository
from src.repositories.source_repository import SourceRepository
from src.repositories.sync_job_repository import SyncJobRepository
from src.repositories.guardrail_event_repository import GuardrailEventRepository
from src.repositories.user_repository import UserRepository
from src.services.account_lockout import AccountLockout
from src.services.ai_model_resolver import AIModelResolver
from src.services.auth_service import AuthService
from src.services.chat_session_service import ChatSessionService
from src.services.chunking_service import ChunkingService
from src.services.connector_service import ConnectorService
from src.services.email_service import EmailService
from src.services.embedding_service import EmbeddingService
from src.services.embedding_service_factory import EmbeddingServiceFactory
from src.services.guardrail_service import GuardrailService
from src.services.langfuse_tracing_service import LangfuseTracingService, NullLangfuse
from src.services.password_service import PasswordService
from src.services.source_inspection_service import SourceInspectionService
from src.services.source_naming_service import SourceNamingService
from src.services.source_permission_service import SourcePermissionService
from src.services.source_profiling import SourceProfilerFactory
from src.services.source_profiling.database_profiler import DatabaseSourceProfiler
from src.services.source_profiling.file_profiler import FileSourceProfiler
from src.services.source_service import SourceService
from src.services.storage_service import StorageService
from src.services.sync_job_service import SyncJobService
from src.services.title_generator import TitleGeneratorService
from src.services.user_service import UserService

import logging

_logger = logging.getLogger(__name__)


def _build_source_profiler_factory(
    file_profiler: FileSourceProfiler,
    database_profiler: DatabaseSourceProfiler,
) -> SourceProfilerFactory:
    """Return a ready-to-use :class:`SourceProfilerFactory`.

    Centralised here so the same factory instance is reused across the
    auto-naming pipeline (admin endpoint + Celery task) without each
    caller having to remember which concrete profilers to register.
    """
    factory = SourceProfilerFactory()
    factory.register_profiler(file_profiler)
    factory.register_profiler(database_profiler)
    return factory


def _build_langfuse_client(app_settings: Any) -> Any:
    """Return a real Langfuse client when configured, else a NullLangfuse stub.

    Langfuse is optional observability — when the secret/public keys are not
    set we return a :class:`NullLangfuse` that no-ops every call so the chat
    pipeline keeps working without credentials.
    """
    secret_key = getattr(app_settings, "LANGFUSE_SECRET_KEY", "") or ""
    public_key = getattr(app_settings, "LANGFUSE_PUBLIC_KEY", "") or ""
    if not secret_key or not public_key:
        _logger.info("Langfuse credentials not set — using NullLangfuse (no-op)")
        return NullLangfuse()

    try:
        from langfuse import Langfuse  # noqa: PLC0415 - optional dependency
    except Exception:  # noqa: BLE001
        _logger.warning("langfuse import failed — falling back to NullLangfuse", exc_info=True)
        return NullLangfuse()

    host = getattr(app_settings, "LANGFUSE_HOST", "") or None
    try:
        return Langfuse(
            secret_key=secret_key,
            public_key=public_key,
            host=host,
        )
    except Exception:  # noqa: BLE001 - never crash startup over observability
        _logger.warning("Langfuse client init failed — falling back to NullLangfuse", exc_info=True)
        return NullLangfuse()


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(packages=["src.api"])

    config = providers.Object(settings)
    db_session_factory = providers.Factory(AsyncSessionLocal)
    session_factory_provider = providers.Object(AsyncSessionLocal)

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
    chat_session_repo = providers.Factory(ChatSessionRepository, session=db_session_factory)
    chat_message_repo = providers.Factory(ChatMessageRepository, session=db_session_factory)
    connector_repo = providers.Factory(ConnectorRepository, session=db_session_factory)
    company_policy_repo = providers.Factory(CompanyPolicyRepository, session=db_session_factory)
    guardrail_event_repo = providers.Factory(GuardrailEventRepository, session=db_session_factory)
    llm_config_repo = providers.Factory(LLMConfigRepository, session=db_session_factory)
    ai_model_repo = providers.Factory(AIModelRepository, session=db_session_factory)
    embedder_repo = providers.Factory(EmbedderRepository, session=db_session_factory)
    admin_audit_log_repo = providers.Factory(
        AdminAuditLogRepository, session=db_session_factory
    )

    # ── Services ────────────────────────────────────────────────────
    password_service = providers.Factory(PasswordService)
    email_service = providers.Factory(EmailService)
    # AccountLockout is constructed with a None redis_client; the service
    # re-resolves the live client from src.core.redis on every call so it
    # picks up the singleton initialised during the lifespan startup hook.
    account_lockout: providers.Singleton[AccountLockout] = providers.Singleton(
        AccountLockout,
        redis_client=None,
        settings=config,
    )
    user_service = providers.Factory(
        UserService,
        user_repo=user_repo,
        invitation_repo=invitation_repo,
        password_service=password_service,
        refresh_token_repo=refresh_token_repo,
        email_service=email_service,
    )
    # WARNING: Do NOT use Container.auth_service() for any mutating operation
    # on a live request. Each Factory() call below creates a *fresh*
    # AsyncSession per repository, so writes performed via this resolver
    # land in unrelated, never-committed transactions and are silently
    # rolled back when the sessions are GC'd. Use the request-scoped
    # _get_auth_service in src.api.v1.auth instead, which binds every
    # repository to the request's Depends(get_db) session.
    #
    # Retained because tests still reference Container.auth_service for a
    # handful of read-only call sites.
    auth_service = providers.Factory(
        AuthService,
        user_repo=user_repo,
        refresh_repo=refresh_token_repo,
        user_service=user_service,
        password_service=password_service,
        lockout=account_lockout,
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
    chat_session_service = providers.Factory(
        ChatSessionService,
        chat_session_repository=chat_session_repo,
        source_permission_service=source_permission_service,
    )
    sync_job_service = providers.Factory(
        SyncJobService,
        session_factory=session_factory_provider,
        sync_job_repo=sync_job_repo,
    )
    connector_service = providers.Factory(
        ConnectorService,
        repo=connector_repo,
        settings=config,
    )
    chunking_service: providers.Singleton[ChunkingService] = providers.Singleton(
        ChunkingService
    )
    embedding_service: providers.Singleton[EmbeddingService] = providers.Singleton(
        EmbeddingService,
        openai_api_key=config.provided.OPENAI_API_KEY,
    )
    openai_client: providers.Singleton[AsyncOpenAI] = providers.Singleton(
        AsyncOpenAI,
        api_key=config.provided.OPENAI_API_KEY,
    )
    # ── v2 resolver / factory (AI_MODELS_V2) ───────────────────────────
    ai_model_resolver: providers.Singleton[AIModelResolver] = providers.Singleton(
        AIModelResolver,
        session_factory=session_factory_provider,
    )
    embedding_service_factory: providers.Singleton[EmbeddingServiceFactory] = (
        providers.Singleton(
            EmbeddingServiceFactory,
            session_factory=session_factory_provider,
        )
    )
    storage_service: providers.Singleton[StorageService] = providers.Singleton(
        StorageService,
        settings=config,
    )
    source_inspection_service: providers.Singleton[SourceInspectionService] = (
        providers.Singleton(
            SourceInspectionService,
            openai_client=openai_client,
        )
    )
    langfuse: providers.Singleton[Any] = providers.Singleton(
        lambda: _build_langfuse_client(settings)
    )
    # ── Source-auto-naming pipeline (F5/F6/F7) ───────────────────────────
    # FileSourceProfiler covers FILE_UPLOAD + WEB_URL + Confluence +
    # SharePoint (all four feed the same Documents/Chunks tables);
    # DatabaseSourceProfiler reads the studying agent's SchemaStudy.
    file_source_profiler: providers.Singleton[FileSourceProfiler] = providers.Singleton(
        FileSourceProfiler,
        ai_model_resolver=ai_model_resolver,
        langfuse=langfuse,
    )
    database_source_profiler: providers.Singleton[DatabaseSourceProfiler] = (
        providers.Singleton(DatabaseSourceProfiler)
    )
    source_profiler_factory: providers.Singleton[SourceProfilerFactory] = (
        providers.Singleton(
            _build_source_profiler_factory,
            file_source_profiler,
            database_source_profiler,
        )
    )
    source_naming_service: providers.Singleton[SourceNamingService] = providers.Singleton(
        SourceNamingService,
        ai_model_resolver=ai_model_resolver,
        langfuse=langfuse,
    )
    langfuse_tracing_service: providers.Singleton[LangfuseTracingService] = providers.Singleton(
        LangfuseTracingService,
        langfuse=langfuse,
    )
    guardrail_service: providers.Factory[GuardrailService] = providers.Factory(
        GuardrailService,
        policy_repo=company_policy_repo,
        guardrail_event_repo=guardrail_event_repo,
        openai_client=openai_client,
        ai_model_resolver=ai_model_resolver,
    )
    title_generator_service: providers.Factory[TitleGeneratorService] = providers.Factory(
        TitleGeneratorService,
        ai_model_resolver=ai_model_resolver,
    )
    pipeline = providers.Factory(
        build_pipeline,
        db_session=providers.Factory(AsyncSessionLocal),
        chunk_repository=chunk_repo,
        chat_session_repository=chat_session_repo,
        chat_message_repository=chat_message_repo,
        ai_model_resolver=ai_model_resolver,
        embedding_service_factory=embedding_service_factory,
        langfuse=langfuse,
        guardrail_service=guardrail_service,
        # Pipeline v2 needs SourceRepository to look up name/type/description
        # for the source_router and text_to_query nodes.  When omitted the
        # builder falls back to v1 (legacy single-shot) automatically.
        source_repository=source_repo,
    )


container = Container()
