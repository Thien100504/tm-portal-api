"""
Task Manager application configuration.

Uses pydantic-settings to read environment variables from the .env file.
Applies the singleton pattern with lru_cache to avoid re-initializing multiple times.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Main application settings, read from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # Release tag (e.g. v1.1.0) or sha-<commit>, baked into the image by CI
    APP_VERSION: str = "dev"

    # --- Database ---
    DATABASE_URL: str = (
        "postgresql+asyncpg://taskmanager:secret@localhost:5432/taskmanager_db"
    )
    DB_POOL_SIZE: int = 3
    DB_MAX_OVERFLOW: int = 2

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- RabbitMQ ---
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672//"

    # --- JWT / Authentication ---
    SECRET_KEY: str = "super-secret-change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- AI Integration (NVIDIA / OpenAI) ---
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str | None = None
    OPENAI_MODEL_NAME: str = "gpt-4o-mini"
    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    # Empty = the provider default from app/modules/ai/llm.py
    AI_CHAT_MODEL: str = ""
    AI_TASK_MODEL: str = ""
    # Room for the reply; Vietnamese and reasoning models need far more than 512
    AI_MAX_TOKENS: int = 4096

    # --- CORS (GAP-01 fix) ---
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]

    # --- Default admin (GAP-05) ---
    ADMIN_EMAIL: str = "admin@taskmanager.local"
    ADMIN_PASSWORD: str = "Admin@123456"

    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # --- Notification Service (microservice) ---
    NOTIFICATION_SERVICE_URL: str = "http://localhost:8002"
    # Shared secret sent to worker.notify in X-Internal-Token (must match its value)
    INTERNAL_API_TOKEN: str = ""

    # --- Telegram Bot ---
    TELEGRAM_BOT_TOKEN: str = ""

    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Return the synchronous database URL (used by scripts)."""
        return self.DATABASE_URL.replace("+asyncpg", "+psycopg2")


@lru_cache
def get_settings() -> Settings:
    """
    Singleton factory for Settings.

    Uses lru_cache to make sure settings are created only once
    for the whole application lifetime.
    """
    return Settings()
