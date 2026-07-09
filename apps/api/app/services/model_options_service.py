from dataclasses import dataclass

from app.config import Settings, get_settings
from app.models import ProcessingMode


DEFAULT_PREMIUM_MODEL_OPTION_ID = "openai:gpt-image-2"


@dataclass(frozen=True)
class ModelOption:
    id: str
    provider: str
    model: str
    label: str
    description: str
    mode: str
    enabled: bool
    tier: str
    experimental: bool = False
    disabled_reason: str | None = None

    def as_response(self) -> dict[str, object]:
        return {
            "id": self.id,
            "provider": self.provider,
            "model": self.model,
            "label": self.label,
            "description": self.description,
            "mode": self.mode,
            "enabled": self.enabled,
            "tier": self.tier,
            "experimental": self.experimental,
            "disabledReason": self.disabled_reason,
        }


class ModelOptionsService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def list_options(self) -> list[ModelOption]:
        return [
            self._openai_primary(),
            self._openai_mini(),
            self._replicate_qwen(),
            self._fal_flux_kontext(),
            self._huggingface_qwen(),
            self._nvidia_nim(),
        ]

    def get_option(self, option_id: str | None) -> ModelOption | None:
        normalized_id = option_id or DEFAULT_PREMIUM_MODEL_OPTION_ID
        return next((option for option in self.list_options() if option.id == normalized_id), None)

    def require_enabled_option(self, option_id: str | None) -> ModelOption:
        option = self.get_option(option_id)
        if option is None:
            raise ValueError(f"Unknown premium model option: {option_id}")
        if not option.enabled:
            reason = option.disabled_reason or "The provider is not configured on this backend."
            raise ValueError(f"{option.label} is not available: {reason}")
        return option

    def _openai_primary(self) -> ModelOption:
        return ModelOption(
            id=DEFAULT_PREMIUM_MODEL_OPTION_ID,
            provider="openai",
            model="gpt-image-2",
            label="OpenAI GPT Image 2",
            description="Best quality, higher cost",
            mode=ProcessingMode.PREMIUM,
            enabled=bool(self.settings.openai_api_key),
            tier="highest",
            disabled_reason=None if self.settings.openai_api_key else "OPENAI_API_KEY is not configured.",
        )

    def _openai_mini(self) -> ModelOption:
        configured_model = (self.settings.openai_mini_image_model or "").strip()
        model = configured_model or "gpt-image-1-mini"
        return ModelOption(
            id=f"openai:{model}",
            provider="openai",
            model=model,
            label="OpenAI Mini Image",
            description="Lower cost OpenAI image option, lower quality",
            mode=ProcessingMode.PREMIUM,
            enabled=bool(self.settings.openai_api_key and configured_model),
            tier="lower",
            experimental=True,
            disabled_reason=None
            if self.settings.openai_api_key and configured_model
            else "Set OPENAI_API_KEY and OPENAI_MINI_IMAGE_MODEL to enable this option.",
        )

    def _replicate_qwen(self) -> ModelOption:
        return ModelOption(
            id="replicate:qwen-image-edit",
            provider="replicate",
            model=self.settings.replicate_qwen_image_edit_model,
            label="Qwen Image Edit via Replicate",
            description="Experimental, lower cost",
            mode=ProcessingMode.PREMIUM,
            enabled=bool(self.settings.replicate_api_token),
            tier="experimental",
            experimental=True,
            disabled_reason=None if self.settings.replicate_api_token else "REPLICATE_API_TOKEN is not configured.",
        )

    def _fal_flux_kontext(self) -> ModelOption:
        return ModelOption(
            id="fal:flux-kontext",
            provider="fal",
            model=self.settings.fal_flux_kontext_model,
            label="FLUX Kontext via fal.ai",
            description="Experimental, strong image editing",
            mode=ProcessingMode.PREMIUM,
            enabled=bool(self.settings.effective_fal_api_key),
            tier="experimental",
            experimental=True,
            disabled_reason=None if self.settings.effective_fal_api_key else "FAL_API_KEY or FAL_KEY is not configured.",
        )

    def _huggingface_qwen(self) -> ModelOption:
        return ModelOption(
            id="huggingface:qwen-image-edit",
            provider="huggingface",
            model=self.settings.hf_qwen_image_edit_model,
            label="Hugging Face Qwen",
            description="Experimental",
            mode=ProcessingMode.PREMIUM,
            enabled=bool(self.settings.hf_token),
            tier="experimental",
            experimental=True,
            disabled_reason=None if self.settings.hf_token else "HF_TOKEN is not configured.",
        )

    def _nvidia_nim(self) -> ModelOption:
        configured = bool(self.settings.nvidia_api_key and self.settings.nvidia_base_url and self.settings.nvidia_image_model)
        return ModelOption(
            id="nvidia:nim-image",
            provider="nvidia",
            model=self.settings.nvidia_image_model or "nvidia-image-model",
            label="NVIDIA NIM",
            description="Experimental",
            mode=ProcessingMode.PREMIUM,
            enabled=configured,
            tier="experimental",
            experimental=True,
            disabled_reason=None
            if configured
            else "NVIDIA_API_KEY, NVIDIA_BASE_URL, and NVIDIA_IMAGE_MODEL are required.",
        )
