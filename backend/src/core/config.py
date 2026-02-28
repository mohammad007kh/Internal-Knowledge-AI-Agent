import os

import yaml  # type: ignore[import-untyped]
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # MinIO
    MINIO_ENDPOINT: str
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
    # App config (loaded from YAML)
    upload_max_size_bytes: int = 52428800
    upload_supported_formats: list[str] = ["pdf", "docx", "xlsx", "csv", "txt", "md"]

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

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
