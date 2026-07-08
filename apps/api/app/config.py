from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Handwritten PDF Recreator API"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg2://postgres:postgres@postgres:5432/handwritten_pdf"
    redis_url: str = "redis://redis:6379/0"
    rq_queue_name: str = "pdf_jobs"

    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "us-east-1"
    s3_bucket: str = Field(default="replace-me-private-bucket")
    s3_endpoint_url: Optional[str] = None
    s3_presigned_expires_seconds: int = 3600

    max_pdf_pages: int = 100
    max_upload_mb: int = 100
    pdf_render_dpi: int = 200
    local_work_dir: str = "/tmp/handwritten-pdf-jobs"

    openai_api_key: Optional[str] = None
    openai_image_model: str = "gpt-image-2"
    openai_image_size: str = "1024x1536"
    openai_image_quality: str = "high"
    openai_image_format: str = "png"

    final_a4_width_px: int = 2480
    final_a4_height_px: int = 3508
    final_print_dpi: int = 300

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
