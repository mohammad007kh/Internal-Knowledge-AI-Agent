from fastapi import APIRouter

from src.api.v1.admin.guardrails import router as admin_guardrails_router
from src.api.v1.admin.llm_settings import router as admin_llm_settings_router
from src.api.v1.admin.policy import router as admin_policy_router
from src.api.v1.analytics import router as analytics_router
from src.api.v1.auth import router as auth_router
from src.api.v1.chat import router as chat_router  # T-076
from src.api.v1.connectors import router as connectors_router
from src.api.v1.ping import router as ping_router

# Future routers imported here (users, sources, chat, etc.)
from src.api.v1.source_permissions import router as source_permissions_router
from src.api.v1.sources import router as sources_router
from src.api.v1.sync_jobs import dedicated_router as sync_jobs_dedicated_router
from src.api.v1.sync_jobs import router as sync_jobs_router
from src.api.v1.users import router as users_router

api_v1_router = APIRouter()

api_v1_router.include_router(ping_router, prefix="/ping", tags=["system"])
api_v1_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_v1_router.include_router(users_router, prefix="/users", tags=["users"])
api_v1_router.include_router(users_router, prefix="/admin/users", tags=["admin-users"])
api_v1_router.include_router(sources_router, prefix="/sources", tags=["sources"])
api_v1_router.include_router(source_permissions_router, prefix="/sources", tags=["source-permissions"])
api_v1_router.include_router(sync_jobs_router, prefix="/sources", tags=["sync-jobs"])
api_v1_router.include_router(sync_jobs_dedicated_router, prefix="/sync-jobs", tags=["sync-jobs"])
api_v1_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_v1_router.include_router(connectors_router, prefix="/connectors", tags=["connectors"])
api_v1_router.include_router(analytics_router, tags=["analytics"])
api_v1_router.include_router(
    admin_llm_settings_router,
    prefix="/admin/llm-settings",
    tags=["admin", "llm-settings"],
)
api_v1_router.include_router(
    admin_policy_router,
    prefix="/admin/policy",
    tags=["admin", "policy"],
)
api_v1_router.include_router(
    admin_guardrails_router,
    prefix="/admin/guardrail-events",
    tags=["admin", "guardrails"],
)
