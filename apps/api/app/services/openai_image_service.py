import base64
import logging
from pathlib import Path

from openai import OpenAI
from PIL import Image

from app.config import Settings, get_settings


logger = logging.getLogger(__name__)


PROMPT_TEMPLATE = """Recreate page {page_no} from the reference image as clean A4 portrait handwriting.
Keep the same content, order, labels, diagrams, spelling, headings, captions, and page layout.
Use pure white paper, blue ballpoint body text, and black pen for headings/underlines/captions.
Do not add, skip, correct, or decorate content. No texture, shadows, borders, stains, watermark, or notebook lines."""


class OpenAIImageService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured; page recreation cannot run.")
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.openai_api_key,
                timeout=self.settings.openai_request_timeout_seconds,
            )
        return self._client

    def build_prompt(self, page_no: int) -> str:
        return PROMPT_TEMPLATE.format(page_no=page_no)

    def recreate_page(self, source_image_path: Path, output_path: Path, page_no: int, model_override: str | None = None) -> Path:
        prompt = self.build_prompt(page_no)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        openai_source_path = self._prepare_source_for_openai(source_image_path, output_path.parent, page_no)
        request_kwargs = {
            "model": model_override or self.settings.openai_image_model,
            "prompt": prompt,
            "size": self.settings.effective_openai_image_size,
            "quality": self.settings.effective_openai_image_quality,
            "output_format": self.settings.effective_openai_image_format,
            "background": "opaque",
            "n": 1,
        }
        if self.settings.effective_openai_image_format.lower() in {"jpeg", "jpg", "webp"}:
            request_kwargs["output_compression"] = self.settings.effective_openai_output_compression

        with openai_source_path.open("rb") as image_file:
            result = self.client.images.edit(
                image=[image_file],
                **request_kwargs,
            )
        self._log_usage(page_no, result)

        image_base64 = result.data[0].b64_json if result.data else None
        if not image_base64:
            raise RuntimeError("OpenAI Image API returned no image data.")

        output_path.write_bytes(base64.b64decode(image_base64))
        return output_path

    def _prepare_source_for_openai(self, source_image_path: Path, output_dir: Path, page_no: int) -> Path:
        max_size = (
            self.settings.effective_openai_source_max_width_px,
            self.settings.effective_openai_source_max_height_px,
        )
        prepared_path = output_dir / f"page_{page_no:03d}_openai_input.png"
        with Image.open(source_image_path) as image:
            original_size = image.size
            prepared = image.convert("RGB")
            prepared.thumbnail(max_size, Image.Resampling.LANCZOS)
            prepared.save(prepared_path, format="PNG", optimize=True)
        logger.info(
            "page %s: OpenAI source image optimized from %sx%s to %sx%s",
            page_no,
            original_size[0],
            original_size[1],
            prepared.width,
            prepared.height,
        )
        return prepared_path

    def _log_usage(self, page_no: int, result: object) -> None:
        usage = getattr(result, "usage", None)
        if usage is None:
            return
        if hasattr(usage, "model_dump"):
            usage_payload = usage.model_dump()
        elif isinstance(usage, dict):
            usage_payload = usage
        else:
            usage_payload = {"usage": str(usage)}
        logger.info("page %s: OpenAI image usage %s", page_no, usage_payload)
