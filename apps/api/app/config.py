from functools import lru_cache
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Handwritten PDF Recreator API"
    app_env: str = "development"
    api_base_url: Optional[str] = None
    frontend_url: Optional[str] = None
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg2://postgres:postgres@postgres:5432/handwritten_pdf"
    redis_url: str = "redis://redis:6379/0"
    rq_queue_name: str = "pdf-jobs"

    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "us-east-1"
    s3_bucket: str = Field(default="replace-me-private-bucket")
    s3_endpoint_url: Optional[str] = None
    signed_url_expiry_seconds: int = Field(
        default=900,
        validation_alias=AliasChoices("SIGNED_URL_EXPIRY_SECONDS", "S3_PRESIGNED_EXPIRES_SECONDS"),
    )

    max_pdf_pages: int = 100
    max_upload_mb: int = 200
    pdf_render_dpi: int = 140
    local_work_dir: str = Field(
        default="/tmp/handpdf",
        validation_alias=AliasChoices("TEMP_DIR", "LOCAL_WORK_DIR"),
    )
    worker_concurrency: int = 1
    page_processing_concurrency: int = 1
    max_page_retries: int = 2

    openai_api_key: Optional[str] = None
    openai_cost_mode: str = "fast"
    openai_image_model: str = "gpt-image-2"
    openai_image_size: str = "768x1088"
    openai_image_quality: str = "low"
    openai_image_format: str = "webp"
    openai_output_compression: int = 65
    openai_request_timeout_seconds: float = 180.0
    openai_source_max_width_px: int = 768
    openai_source_max_height_px: int = 1088

    final_a4_width_px: int = 2480
    final_a4_height_px: int = 3508
    final_print_dpi: int = 300

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        if self.frontend_url and self.frontend_url not in origins:
            origins.append(self.frontend_url)
        return origins

    @property
    def effective_openai_image_size(self) -> str:
        if self.openai_cost_mode_normalized == "fast":
            return "768x1088"
        if self.openai_cost_mode_normalized == "balanced":
            return "896x1280"
        return self.openai_image_size

    @property
    def effective_openai_image_quality(self) -> str:
        if self.openai_cost_mode_normalized == "fast":
            return "low"
        if self.openai_cost_mode_normalized == "balanced":
            return "medium"
        return self.openai_image_quality

    @property
    def effective_openai_image_format(self) -> str:
        if self.openai_cost_mode_normalized in {"fast", "balanced"}:
            return "webp"
        return self.openai_image_format

    @property
    def effective_openai_output_compression(self) -> int:
        if self.openai_cost_mode_normalized == "fast":
            return 65
        if self.openai_cost_mode_normalized == "balanced":
            return 75
        return self.openai_output_compression

    @property
    def effective_openai_source_max_width_px(self) -> int:
        if self.openai_cost_mode_normalized == "fast":
            return 768
        if self.openai_cost_mode_normalized == "balanced":
            return 896
        return self.openai_source_max_width_px

    @property
    def effective_openai_source_max_height_px(self) -> int:
        if self.openai_cost_mode_normalized == "fast":
            return 1088
        if self.openai_cost_mode_normalized == "balanced":
            return 1280
        return self.openai_source_max_height_px

    @property
    def openai_cost_mode_normalized(self) -> str:
        mode = self.openai_cost_mode.strip().lower()
        if mode in {"fast", "balanced", "quality", "custom"}:
            return mode
        return "fast"


@lru_cache
def get_settings() -> Settings:
    return Settings()
