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
    job_auto_retry_limit: int = 3
    job_stale_seconds: int = 900

    default_processing_mode: str = "premium"

    openai_api_key: Optional[str] = None
    openai_cost_mode: str = "fast"
    openai_image_model: str = "gpt-image-2"
    openai_mini_image_model: Optional[str] = None
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
    cheap_mode_render_dpi: int = 150
    cheap_mode_cleanup_max_width: int = 1654
    cheap_mode_cleanup_max_height: int = 2339
    cheap_mode_enable_advanced_cleanup: bool = True
    cheap_cleanup_preset: str = "strong_print"
    cheap_background_strength: float = 0.85
    cheap_contrast_strength: float = 1.25
    cheap_despeckle_strength: str = "medium"
    cheap_remove_light_lines: bool = True
    cheap_ink_darken: bool = True

    replicate_provider_enabled: bool = False
    replicate_api_token: Optional[str] = None
    replicate_qwen_image_edit_model: str = "qwen/qwen-image-edit"
    replicate_max_retries: int = 8
    replicate_rate_limit_delay_seconds: float = 15.0
    replicate_min_seconds_between_predictions: float = 15.0
    replicate_prediction_timeout_seconds: float = 300.0
    replicate_quality_preset: str = "balanced"
    replicate_source_max_width: int = 1240
    replicate_source_max_height: int = 1754
    replicate_output_format: str = "png"
    replicate_output_quality: int = 95
    replicate_go_fast: bool = False
    replicate_num_inference_steps: int = 50
    replicate_guidance: float = 4.0
    fal_provider_enabled: bool = False
    fal_api_key: Optional[str] = None
    fal_key: Optional[str] = None
    fal_flux_kontext_model: str = "fal-ai/flux-pro/kontext"
    hf_provider_enabled: bool = False
    hf_token: Optional[str] = None
    hf_qwen_image_edit_model: str = "Qwen/Qwen-Image-Edit"

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
    def default_processing_mode_normalized(self) -> str:
        mode = self.default_processing_mode.strip().lower()
        if mode in {"premium", "cheap"}:
            return mode
        return "premium"

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

    @property
    def cheap_cleanup_preset_normalized(self) -> str:
        preset = self.cheap_cleanup_preset.strip().lower()
        if preset in {"light", "strong_print", "high_contrast"}:
            return preset
        return "strong_print"

    @property
    def effective_fal_api_key(self) -> Optional[str]:
        return self.fal_key or self.fal_api_key

    @property
    def replicate_quality_preset_normalized(self) -> str:
        preset = self.replicate_quality_preset.strip().lower()
        if preset in {"fast", "balanced", "high", "print"}:
            return preset
        return "balanced"

    @property
    def effective_replicate_quality_config(self) -> dict[str, int | float | str | bool]:
        preset = self.replicate_quality_preset_normalized
        presets: dict[str, dict[str, int | float | str | bool]] = {
            "fast": {
                "source_max_width": 768,
                "source_max_height": 1088,
                "output_format": "webp",
                "output_quality": 80,
                "go_fast": True,
                "num_inference_steps": 25,
                "guidance": self.replicate_guidance,
            },
            "balanced": {
                "source_max_width": self.replicate_source_max_width,
                "source_max_height": self.replicate_source_max_height,
                "output_format": self.replicate_output_format,
                "output_quality": self.replicate_output_quality,
                "go_fast": self.replicate_go_fast,
                "num_inference_steps": 40,
                "guidance": self.replicate_guidance,
            },
            "high": {
                "source_max_width": 1654,
                "source_max_height": 2339,
                "output_format": "png",
                "output_quality": 100,
                "go_fast": False,
                "num_inference_steps": 50,
                "guidance": self.replicate_guidance,
            },
            "print": {
                "source_max_width": 1860,
                "source_max_height": 2631,
                "output_format": "png",
                "output_quality": 100,
                "go_fast": False,
                "num_inference_steps": 60,
                "guidance": self.replicate_guidance,
            },
        }
        return presets[preset]


@lru_cache
def get_settings() -> Settings:
    return Settings()
