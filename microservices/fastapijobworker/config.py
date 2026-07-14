"""
Configuration — all settings loaded from environment variables.

Usage:
    from config import settings
    print(settings.runpod_api_key)
"""

import os
from typing import Optional


class Settings:
    """
    Flat settings class. In a larger project use Pydantic BaseSettings,
    but for a 6-day build this avoids the extra dependency layer.
    """

    # ── Service ────────────────────────────────────────────────────────────────
    environment: str = os.getenv("ENVIRONMENT", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # ── MySQL ──────────────────────────────────────────────────────────────────
    database_host: str = os.getenv("DATABASE_HOST", "127.0.0.1")
    database_port: int = int(os.getenv("DATABASE_PORT", "3306"))
    database_name: str = os.getenv("DATABASE_NAME", "hairstylesuggest")
    database_user: str = os.getenv("DATABASE_USER", "hairstylesuggest_user")
    database_password: str = os.getenv("DATABASE_PASSWORD", "")

    # ── Job Worker ────────────────────────────────────────────────────────────
    job_poll_interval_seconds: float = float(os.getenv("JOB_POLL_INTERVAL_SECONDS", "3"))
    max_concurrent_jobs: int = int(os.getenv("MAX_CONCURRENT_JOBS", "3"))
    job_max_attempts: int = int(os.getenv("JOB_MAX_ATTEMPTS", "3"))

    # ── RunPod ────────────────────────────────────────────────────────────────
    runpod_api_key: str = os.getenv("RUNPOD_API_KEY", "")
    runpod_endpoint_id: str = os.getenv("RUNPOD_ENDPOINT_ID", "")
    runpod_timeout_seconds: int = int(os.getenv("RUNPOD_TIMEOUT_SECONDS", "300"))
    runpod_poll_interval: float = float(os.getenv("RUNPOD_POLL_INTERVAL", "5"))

    # ── Cloudflare R2 ─────────────────────────────────────────────────────────
    r2_access_key_id: str = os.getenv("R2_ACCESS_KEY_ID", "")
    r2_secret_access_key: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
    r2_bucket_name: str = os.getenv("R2_BUCKET_NAME", "hairstylesuggest-assets")
    r2_endpoint_url: str = os.getenv("R2_ENDPOINT_URL", "")
    cdn_base_url: str = os.getenv("CDN_BASE_URL", "").rstrip("/")

    # ── Strapi Webhook ────────────────────────────────────────────────────────
    # e.g. http://localhost:1337/internal/jobs
    strapi_webhook_url: str = os.getenv("STRAPI_WEBHOOK_URL", "http://localhost:1337/internal/jobs")
    internal_service_key: str = os.getenv("INTERNAL_SERVICE_KEY", "")

    # ── Model Paths (local paths inside Docker image) ─────────────────────────
    bisenet_model_path: str = os.getenv(
        "BISENET_MODEL_PATH", "/models/bisenet_resnet18.pth"
    )
    models_dir: str = os.getenv("MODELS_DIR", "/models")

    def validate(self) -> None:
        """
        Raise ValueError if critical environment variables are missing.
        Called at startup before the worker launches.
        """
        required = {
            "DATABASE_PASSWORD": self.database_password,
            "RUNPOD_API_KEY": self.runpod_api_key,
            "RUNPOD_ENDPOINT_ID": self.runpod_endpoint_id,
            "R2_ACCESS_KEY_ID": self.r2_access_key_id,
            "R2_SECRET_ACCESS_KEY": self.r2_secret_access_key,
            "R2_ENDPOINT_URL": self.r2_endpoint_url,
            "CDN_BASE_URL": self.cdn_base_url,
            "INTERNAL_SERVICE_KEY": self.internal_service_key,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Copy .env.example to .env and fill in all values."
            )


# Singleton
settings = Settings()