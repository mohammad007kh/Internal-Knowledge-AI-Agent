import logging
import os

import yaml  # type: ignore[import-untyped]
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"
    # Auth
    JWT_SECRET_KEY: str
    JWT_REFRESH_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # When the login form sets remember_me=true, the refresh cookie's max-age
    # is extended to this many days instead of REFRESH_TOKEN_EXPIRE_DAYS.
    # The token itself still rotates on every refresh; this only controls
    # how long the browser persists the cookie before the user must
    # re-authenticate from scratch.
    REFRESH_TOKEN_REMEMBER_ME_DAYS: int = 30
    # MinIO
    # MINIO_ENDPOINT is the internal endpoint the backend uses to talk to
    # MinIO (inside the Docker network this is the service name `minio:9000`).
    # MINIO_PUBLIC_ENDPOINT is the host-exposed endpoint the browser uses to
    # follow presigned URLs (e.g. `localhost:9000`).
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_PUBLIC_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_BUCKET: str = "knowledge-agent"
    MINIO_SECURE: bool = False
    COOKIE_SECURE: bool = True
    # Langfuse
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_HOST: str = "http://localhost:3001"
    # Bootstrap admin
    BOOTSTRAP_ADMIN_EMAIL: str | None = None
    BOOTSTRAP_ADMIN_PASSWORD: str | None = None
    # Encryption
    ENCRYPTION_KEY: str
    # OpenAI
    OPENAI_API_KEY: str = ""
    # AI Models v2 — enables AIModel/Embedder-driven pipeline.
    # Defaults to True; gradual-rollout flag is preserved for future deployments.
    AI_MODELS_V2: bool = True
    # Fallback model id used when the AIModelResolver cannot resolve a stage
    # (e.g. guardrail eval before any AIModel/Embedder is provisioned).
    # Configurable so deployments behind self-hosted gateways can override.
    DEFAULT_FALLBACK_MODEL: str = "gpt-4o-mini"
    # Email
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "noreply@knowledge-agent.internal"
    SMTP_USE_TLS: bool = True
    EMAIL_LOG_ONLY: bool = False
    # Logging
    LOG_LEVEL: str = "info"
    # Security / CORS
    FRONTEND_URL: str = "http://localhost:3000"
    ENVIRONMENT: str = "development"
    TRUSTED_PROXY_IPS: list[str] = []
    # Rate limiting (per-IP, sliding window)
    RATE_LIMIT_AUTH_LOGIN_LIMIT: int = 5
    RATE_LIMIT_AUTH_LOGIN_WINDOW: int = 60
    RATE_LIMIT_AUTH_REFRESH_LIMIT: int = 30
    RATE_LIMIT_AUTH_REFRESH_WINDOW: int = 60
    RATE_LIMIT_API_LIMIT: int = 200
    RATE_LIMIT_API_WINDOW: int = 60
    # Account lockout (per-email-hash, sliding window) — layered on top of
    # the per-IP rate limit to defeat distributed credential-stuffing botnets.
    LOCKOUT_ENABLED: bool = True
    # Fail-closed when Redis is unreachable. Defaults to True in production
    # and is auto-relaxed to False when ENVIRONMENT == "development" so local
    # contributors aren't blocked when Redis is down. Override explicitly via
    # env var if the auto behaviour isn't what you want.
    LOCKOUT_REQUIRE_REDIS: bool = True
    LOCKOUT_MAX_FAILS: int = 10
    LOCKOUT_WINDOW_SECS: int = 900       # 15-min sliding window
    LOCKOUT_DURATION_SECS: int = 1800    # 30-min lockout after threshold
    # Pipeline v2 — wires the 4 dead admin slots
    # (clarification_detector, query_analyzer, source_router, text_to_query)
    # plus the optional reflector retry loop. Falls back to v1 (the legacy
    # input_guard → clarify(heuristic) → retrieve → synthesizer → output_guard)
    # when set to False. Toggle is read at pipeline build time so a quick
    # restart rolls back to v1 in <30s.
    PIPELINE_V2_ENABLED: bool = True
    # Reflector self-critic — costly per Constitution; OFF by default.
    PIPELINE_REFLECTOR_ENABLED: bool = False
    PIPELINE_REFLECTOR_MAX_RETRIES: int = 1
    # Clarification gate. The LLM clarifier was over-eager on first-turn
    # questions ("references entities not yet introduced" fires on virtually
    # every fresh query in a RAG system), short-circuiting retrieve_context
    # and forcing the user through "Could you please specify..." round-trips
    # before the bot ever tried to find an answer. OFF by default so retrieve
    # is the gate: if no chunks come back, the synthesizer naturally says so.
    # The node code is kept; admins can re-enable per-environment without
    # redeploying.
    PIPELINE_CLARIFY_ENABLED: bool = False
    # App config (loaded from YAML)
    upload_max_size_bytes: int = 52428800
    upload_supported_formats: list[str] = ["pdf", "docx", "xlsx", "csv", "txt", "md"]

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    @model_validator(mode="after")
    def _relax_lockout_redis_in_dev(self) -> "Settings":
        """In development, default LOCKOUT_REQUIRE_REDIS to False unless the
        operator has explicitly set the env var.

        Pydantic Settings supplies env values via attribute assignment, so we
        only flip the default when the env var is *not* present in the process
        environment. This keeps prod fail-closed while making dev forgiving.
        """
        if (
            self.ENVIRONMENT == "development"
            and "LOCKOUT_REQUIRE_REDIS" not in os.environ
        ):
            object.__setattr__(self, "LOCKOUT_REQUIRE_REDIS", False)
        _logger.info(
            "Account lockout config: enabled=%s require_redis=%s "
            "max_fails=%d window_secs=%d duration_secs=%d",
            self.LOCKOUT_ENABLED,
            self.LOCKOUT_REQUIRE_REDIS,
            self.LOCKOUT_MAX_FAILS,
            self.LOCKOUT_WINDOW_SECS,
            self.LOCKOUT_DURATION_SECS,
        )
        return self

    def model_post_init(self, __context: object) -> None:
        config_path = os.environ.get("APP_CONFIG_PATH", "app_config.yaml")
        if os.path.exists(config_path):
            with open(config_path) as f:
                data = yaml.safe_load(f)
            fu = data.get("file_upload", {})
            if "max_size_bytes" in fu:
                object.__setattr__(self, "upload_max_size_bytes", fu["max_size_bytes"])
            if "supported_formats" in fu:
                object.__setattr__(
                    self, "upload_supported_formats", fu["supported_formats"]
                )


settings = Settings()  # type: ignore[call-arg]
