from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables.

    Secrets are deliberately optional so that the deterministic demo can run locally. Real
    document extraction is enabled only when Vertex AI or a Gemini API key is configured.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Cherry Agent"
    environment: str = Field(default="local", validation_alias="CHERRY_ENVIRONMENT")
    public_base_url: str = Field(
        default="http://localhost:8080", validation_alias="CHERRY_PUBLIC_BASE_URL"
    )
    persistence_backend: Literal["memory", "firestore"] = Field(
        default="memory", validation_alias="CHERRY_PERSISTENCE_BACKEND"
    )
    gemini_model: str = Field(default="gemini-3.7-flash", validation_alias="CHERRY_GEMINI_MODEL")
    auto_reconcile_score: int = Field(
        default=90, ge=0, le=100, validation_alias="CHERRY_AUTO_RECONCILE_SCORE"
    )
    approval_amount_gbp: float = Field(
        default=5000.0, ge=0, validation_alias="CHERRY_APPROVAL_AMOUNT_GBP"
    )
    amount_tolerance_percent: float = Field(
        default=2.0, ge=0, le=100, validation_alias="CHERRY_AMOUNT_TOLERANCE_PERCENT"
    )
    max_upload_mb: int = Field(default=50, ge=1, le=50, validation_alias="CHERRY_MAX_UPLOAD_MB")

    google_cloud_project: str | None = Field(default=None, validation_alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_location: str = Field(default="global", validation_alias="GOOGLE_CLOUD_LOCATION")
    google_api_key: SecretStr | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    use_vertex_ai: bool = Field(default=True, validation_alias="GOOGLE_GENAI_USE_VERTEXAI")

    firestore_collection: str = Field(
        default="finance_workflows", validation_alias="CHERRY_FIRESTORE_COLLECTION"
    )
    evidence_bucket: str | None = Field(default=None, validation_alias="CHERRY_EVIDENCE_BUCKET")
    pubsub_topic: str | None = Field(
        default="finance-workflow-events", validation_alias="CHERRY_PUBSUB_TOPIC"
    )

    cherry_money_api_url: str | None = Field(default=None, validation_alias="CHERRY_MONEY_API_URL")
    cherry_money_api_token: SecretStr | None = Field(
        default=None, validation_alias="CHERRY_MONEY_API_TOKEN"
    )

    fundops_studio_api_url: str | None = Field(
        default=None, validation_alias="FUNDOPS_STUDIO_API_URL"
    )
    fundops_studio_audience: str | None = Field(
        default=None, validation_alias="FUNDOPS_STUDIO_AUDIENCE"
    )
    fundops_studio_api_token: SecretStr | None = Field(
        default=None, validation_alias="FUNDOPS_STUDIO_API_TOKEN"
    )
    fundops_studio_timeout_seconds: float = Field(
        default=25.0, ge=1, le=120, validation_alias="FUNDOPS_STUDIO_TIMEOUT_SECONDS"
    )

    @property
    def google_ready(self) -> bool:
        if self.google_api_key and self.google_api_key.get_secret_value().strip():
            return True
        return bool(self.use_vertex_ai and self.google_cloud_project)

    @property
    def cloud_mode(self) -> bool:
        return self.persistence_backend == "firestore" and bool(self.google_cloud_project)

    def configure_google_environment(self) -> None:
        """Populate the environment expected by the Google Gen AI SDK.

        Cloud Run uses Application Default Credentials from its service account. No service
        account key file is required or accepted by this application.
        """

        if self.use_vertex_ai and self.google_cloud_project:
            os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
            os.environ.setdefault("GOOGLE_CLOUD_PROJECT", self.google_cloud_project)
            os.environ.setdefault("GOOGLE_CLOUD_LOCATION", self.google_cloud_location)
        elif self.google_api_key:
            os.environ.setdefault("GOOGLE_API_KEY", self.google_api_key.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.configure_google_environment()
    return settings
