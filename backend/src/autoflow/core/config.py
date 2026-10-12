"""
AutoFlow Core Configuration
Typed settings loaded from environment variables and .env files.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


class AIProvider(StrEnum):
    """Supported AI providers — all use OpenAI-compatible API format."""
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    GROQ = "groq"
    CUSTOM = "custom"


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    The settings are organized into sections:
    - Application
    - Database
    - Redis / Celery
    - AI Provider (abstraction layer)
    - Security
    - CORS
    - Feature Flags
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Application ─────────────────────────────────────
    app_env: AppEnv = AppEnv.DEVELOPMENT
    app_name: str = "AutoFlow"
    app_version: str = "0.1.0"
    app_secret_key: str = "change-me-in-production"
    api_v1_prefix: str = "/api/v1"
    debug: bool = False

    @property
    def is_development(self) -> bool:
        return self.app_env == AppEnv.DEVELOPMENT

    @property
    def is_production(self) -> bool:
        return self.app_env == AppEnv.PRODUCTION

    @property
    def is_testing(self) -> bool:
        return self.app_env == AppEnv.TESTING

    # ─── Database ────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://autoflow:autoflow_dev_password@localhost:5432/autoflow",
        description="Async PostgreSQL connection URL",
    )
    db_pool_size: int = Field(default=10, ge=1, le=50)
    db_max_overflow: int = Field(default=20, ge=0, le=100)
    db_pool_timeout: int = Field(default=30, ge=1)
    db_echo: bool = False  # Set to True to log all SQL queries

    # ─── Redis ───────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ─── AI Provider Abstraction ─────────────────────────
    ai_provider: AIProvider = AIProvider.OLLAMA

    # Ollama (local, privacy-first default)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    # Anthropic (via OpenAI-compatible proxy)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-haiku-20241022"

    # Gemini (via OpenAI-compatible endpoint)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # Groq
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Custom OpenAI-compatible provider
    custom_ai_base_url: str = ""
    custom_ai_api_key: str = ""
    custom_ai_model: str = ""

    # Shared AI settings
    ai_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    ai_max_tokens: int = Field(default=4096, ge=100, le=128000)
    ai_timeout_seconds: int = Field(default=60, ge=5)

    @property
    def resolved_ai_base_url(self) -> str:
        """Return the base URL for the configured AI provider."""
        match self.ai_provider:
            case AIProvider.OLLAMA:
                return f"{self.ollama_base_url}/v1"
            case AIProvider.OPENAI:
                return self.openai_base_url
            case AIProvider.ANTHROPIC:
                # Use Anthropic's OpenAI-compatible endpoint
                return "https://api.anthropic.com/v1"
            case AIProvider.GEMINI:
                return "https://generativelanguage.googleapis.com/v1beta/openai"
            case AIProvider.GROQ:
                return self.groq_base_url
            case AIProvider.CUSTOM:
                return self.custom_ai_base_url
            case _:
                return self.ollama_base_url + "/v1"

    @property
    def resolved_ai_api_key(self) -> str:
        """Return the API key for the configured AI provider."""
        match self.ai_provider:
            case AIProvider.OLLAMA:
                return "ollama"  # Ollama doesn't require a real key
            case AIProvider.OPENAI:
                return self.openai_api_key
            case AIProvider.ANTHROPIC:
                return self.anthropic_api_key
            case AIProvider.GEMINI:
                return self.gemini_api_key
            case AIProvider.GROQ:
                return self.groq_api_key
            case AIProvider.CUSTOM:
                return self.custom_ai_api_key
            case _:
                return "ollama"

    @property
    def resolved_ai_model(self) -> str:
        """Return the model identifier for the configured AI provider."""
        match self.ai_provider:
            case AIProvider.OLLAMA:
                return self.ollama_model
            case AIProvider.OPENAI:
                return self.openai_model
            case AIProvider.ANTHROPIC:
                return self.anthropic_model
            case AIProvider.GEMINI:
                return self.gemini_model
            case AIProvider.GROQ:
                return self.groq_model
            case AIProvider.CUSTOM:
                return self.custom_ai_model
            case _:
                return self.ollama_model

    # ─── Security ────────────────────────────────────────
    credential_encryption_key: str = ""
    extension_api_key: str = "change-me-generate-uuid"

    @field_validator("credential_encryption_key", mode="before")
    @classmethod
    def generate_encryption_key(cls, v: str) -> str:
        """Auto-generate encryption key in development if not set."""
        if not v:
            from cryptography.fernet import Fernet
            return Fernet.generate_key().decode()
        return v

    # ─── CORS ────────────────────────────────────────────
    cors_origins: list[str] = Field(
        default=[
            "http://localhost:5173",
            "http://localhost:3000",
            "http://localhost:8000",
        ]
    )
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]
    cors_origin_regex: str = r"chrome-extension://.*"

    # ─── Feature Flags ───────────────────────────────────
    enable_playwright_execution: bool = True
    enable_ai_intent_extraction: bool = True
    enable_real_time_streaming: bool = True

    # ─── Validation ──────────────────────────────────────
    @model_validator(mode="after")
    def validate_ai_config(self) -> Settings:
        """Warn if required API keys are missing for non-Ollama providers."""
        if self.ai_provider != AIProvider.OLLAMA and not self.resolved_ai_api_key:
            import warnings
            warnings.warn(
                f"AI provider '{self.ai_provider}' requires an API key. "
                "Set the appropriate *_API_KEY environment variable.",
                UserWarning,
                stacklevel=2,
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.
    Use this function everywhere — never instantiate Settings directly.

    Example:
        from autoflow.core.config import get_settings
        settings = get_settings()
    """
    return Settings()
