import base64
from pathlib import Path

from openai import OpenAI

from app.config import Settings, get_settings


PROMPT_TEMPLATE = """You are recreating page {page_no} of a scanned handwritten practical file.

Use the source page as the reference.

Recreate the same page content, same order, same diagram if present, same labels, same heading flow, and same page structure.

Output requirements:
- Plain pure white A4 portrait paper background.
- No grey patches, no paper texture, no stains, no shadows, no scanner marks, no watermark, no notebook lines, and no page borders.
- Body writing in natural blue ballpoint handwritten style.
- Headings, underlines, page number, date area, and figure captions in black pen style.
- Preserve natural human handwriting variation.
- Preserve visible original spelling mistakes where possible.
- Do not add new content.
- Do not skip diagrams.
- Do not correct content unless clearly unreadable.
- Keep the page printable and clean.
- Only the blue and black handwritten content should remain visible."""


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

    def recreate_page(self, source_image_path: Path, output_path: Path, page_no: int) -> Path:
        prompt = self.build_prompt(page_no)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with source_image_path.open("rb") as image_file:
            result = self.client.images.edit(
                model=self.settings.openai_image_model,
                image=[image_file],
                prompt=prompt,
                size=self.settings.openai_image_size,
                quality=self.settings.openai_image_quality,
                output_format=self.settings.openai_image_format,
                background="opaque",
                n=1,
            )

        image_base64 = result.data[0].b64_json if result.data else None
        if not image_base64:
            raise RuntimeError("OpenAI Image API returned no image data.")

        output_path.write_bytes(base64.b64decode(image_base64))
        return output_path
