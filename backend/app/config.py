"""Settings from environment (.env in dev). Technical defaults live here too."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:password@localhost:5432/faultline"

    es_url: str = "http://localhost:9200"
    es_api_key: str = ""
    es_ca_cert: str = ""
    es_index_pattern: str = "logs-*"
    es_message_field: str = "message"
    es_service_field: str = "kubernetes.container.name"
    es_host_field: str = "host.name"

    keycloak_url: str = "http://localhost:8080"
    keycloak_issuer: str = "http://localhost:8080/realms/abhi-org"
    keycloak_realm: str = "abhi-org"
    keycloak_client_id: str = "faultline-web"
    keycloak_algorithms: str = "RS256"

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_requests_per_minute: float = 20
    tavily_api_key: str = ""

    dashboard_base_url: str = "http://localhost:4200"
    cors_origins: str = "http://localhost:4200"
    log_level: str = "INFO"

    default_team_name: str = "Platform"
    default_team_dl: str = "platform-team@example.com"

    # Ingestion / preprocessing
    initial_lookback_hours: int = 24
    ingest_lag_minutes: int = 2
    es_page_size: int = 1000
    max_message_chars: int = 4000
    stack_frames_kept: int = 3
    app_package_prefixes: list[str] = Field(default_factory=lambda: ["com.example.", "/app/"])
    internal_host_suffixes: list[str] = Field(default_factory=lambda: [".corp.example.com", ".internal"])

    # Detection (spec 5.6 defaults)
    spike_multiplier: float = 3
    spike_lookback_hours: int = 24
    spike_min_count: int = 20

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sync_database_url(self) -> str:
        """Plain libpq URL for psycopg (LangGraph checkpointer)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Stage 1 code constants (become dashboard settings in Stage 2)
SCAN_LEVELS = ("FATAL", "CRITICAL", "ERROR", "WARN")
SCAN_KEYWORDS = {"Exception": "ERROR", "Traceback": "ERROR"}
