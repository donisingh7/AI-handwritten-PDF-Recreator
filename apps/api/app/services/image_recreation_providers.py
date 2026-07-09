from abc import ABC, abstractmethod
import base64
import logging
import time
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageOps

from app.config import Settings, get_settings
from app.services.model_options_service import ModelOption

logger = logging.getLogger(__name__)


class ProviderConfigurationError(RuntimeError):
    pass


class ProviderFatalError(RuntimeError):
    pass


class ProviderUnsupportedError(RuntimeError):
    pass


class ImageRecreationProvider(ABC):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @abstractmethod
    def recreate_page(
        self,
        source_image_path: Path,
        prompt: str,
        output_image_path: Path,
        page_no: int,
        model_config: ModelOption,
    ) -> Path:
        raise NotImplementedError


class OpenAIProvider(ImageRecreationProvider):
    def recreate_page(
        self,
        source_image_path: Path,
        prompt: str,
        output_image_path: Path,
        page_no: int,
        model_config: ModelOption,
    ) -> Path:
        del prompt
        if not self.settings.openai_api_key:
            raise ProviderConfigurationError("OPENAI_API_KEY is not configured.")

        from app.services.openai_image_service import OpenAIImageService

        return OpenAIImageService(self.settings).recreate_page(
            source_image_path,
            output_image_path,
            page_no,
            model_override=model_config.model,
        )


class ReplicateProvider(ImageRecreationProvider):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)
        self._last_prediction_created_at = 0.0
        self._schema_fields_cache: dict[str, set[str] | None] = {}

    def recreate_page(
        self,
        source_image_path: Path,
        prompt: str,
        output_image_path: Path,
        page_no: int,
        model_config: ModelOption,
    ) -> Path:
        del page_no
        if not self.settings.replicate_provider_enabled:
            raise ProviderConfigurationError("REPLICATE_PROVIDER_ENABLED is not true.")
        if not self.settings.replicate_api_token:
            raise ProviderConfigurationError("REPLICATE_API_TOKEN is not configured.")
        if "/" not in model_config.model:
            raise ProviderConfigurationError("REPLICATE_QWEN_IMAGE_EDIT_MODEL must be in owner/model format.")

        quality_config = self.settings.effective_replicate_quality_config
        prepared_source_path = self._prepare_source_for_replicate(source_image_path, output_image_path.parent)
        supported_fields = self._fetch_supported_input_fields(model_config.model)
        request_input = self._build_replicate_input(
            prompt=prompt,
            source_image_path=prepared_source_path,
            quality_config=quality_config,
            supported_fields=supported_fields,
        )

        url = f"https://api.replicate.com/v1/models/{model_config.model}/predictions"
        payload = {"input": request_input}
        self._wait_for_prediction_slot()
        prediction = self._replicate_json_request(
            url,
            payload=payload,
            purpose="prediction_create",
        )
        self._last_prediction_created_at = time.monotonic()
        result = self._poll_replicate_prediction(prediction)
        _save_image_reference(_extract_image_reference(result), output_image_path, self.settings.replicate_prediction_timeout_seconds)
        output_size = _image_size_or_none(output_image_path)
        if output_size:
            logger.info(
                "Replicate output image saved path=%s size=%sx%s",
                output_image_path,
                output_size[0],
                output_size[1],
            )
        return output_image_path

    def _prepare_source_for_replicate(self, source_image_path: Path, output_dir: Path) -> Path:
        quality_config = self.settings.effective_replicate_quality_config
        max_size = (
            int(quality_config["source_max_width"]),
            int(quality_config["source_max_height"]),
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        prepared_path = output_dir / f"{source_image_path.stem}_replicate_input.png"
        with Image.open(source_image_path) as source_image:
            original = ImageOps.exif_transpose(source_image).convert("RGB")
            original_size = original.size
            original.thumbnail(max_size, Image.Resampling.LANCZOS)
            original.save(prepared_path, format="PNG", optimize=True)
        logger.info(
            "Replicate source image prepared preset=%s source=%sx%s prepared=%sx%s",
            self.settings.replicate_quality_preset_normalized,
            original_size[0],
            original_size[1],
            original.width,
            original.height,
        )
        original.close()
        return prepared_path

    def _build_replicate_input(
        self,
        prompt: str,
        source_image_path: Path,
        quality_config: dict[str, int | float | str | bool],
        supported_fields: set[str] | None,
    ) -> dict[str, Any]:
        request_input: dict[str, Any] = {
            "image": _data_uri(source_image_path),
            "prompt": prompt,
        }
        optional_fields: dict[str, Any] = {
            "output_format": str(quality_config["output_format"]),
            "output_quality": int(quality_config["output_quality"]),
            "go_fast": bool(quality_config["go_fast"]),
            "guidance": float(quality_config["guidance"]),
        }
        steps_value = int(quality_config["num_inference_steps"])

        if supported_fields is None:
            for field_name in [*optional_fields.keys(), "num_inference_steps"]:
                logger.info("Replicate model schema unavailable; skipping optional field %s", field_name)
            return request_input

        for field_name, value in optional_fields.items():
            if field_name in supported_fields:
                request_input[field_name] = value
            else:
                logger.info("Replicate model does not support field %s; skipping.", field_name)

        if "num_inference_steps" in supported_fields:
            request_input["num_inference_steps"] = steps_value
        elif "steps" in supported_fields:
            request_input["steps"] = steps_value
        else:
            logger.info("Replicate model does not support field num_inference_steps; skipping.")

        return request_input

    def _fetch_supported_input_fields(self, model_slug: str) -> set[str] | None:
        if model_slug in self._schema_fields_cache:
            return self._schema_fields_cache[model_slug]
        fields: set[str] | None = None
        try:
            model = self._replicate_json_request(
                f"https://api.replicate.com/v1/models/{model_slug}",
                payload=None,
                purpose="model_schema",
                method="GET",
                retry_on_rate_limit=False,
            )
            fields = _extract_replicate_schema_fields(model)
            if fields is None:
                versions = self._replicate_json_request(
                    f"https://api.replicate.com/v1/models/{model_slug}/versions",
                    payload=None,
                    purpose="model_versions_schema",
                    method="GET",
                    retry_on_rate_limit=False,
                )
                latest_version = (versions.get("results") or [None])[0]
                fields = _extract_replicate_schema_fields(latest_version)
        except ProviderFatalError:
            raise
        except Exception as exc:
            logger.warning("Could not inspect Replicate model schema for %s; optional fields will be skipped: %s", model_slug, exc)
        self._schema_fields_cache[model_slug] = fields
        if fields is not None:
            logger.info("Replicate model input schema fields for %s: %s", model_slug, sorted(fields))
        return fields

    def _wait_for_prediction_slot(self) -> None:
        delay = max(0.0, self.settings.replicate_min_seconds_between_predictions)
        if delay <= 0 or self._last_prediction_created_at <= 0:
            return
        elapsed = time.monotonic() - self._last_prediction_created_at
        remaining = delay - elapsed
        if remaining > 0:
            logger.info("Replicate prediction create minimum delay %.1fs; sleeping %.1fs", delay, remaining)
            time.sleep(remaining)

    def _replicate_json_request(
        self,
        url: str,
        payload: dict[str, Any] | None,
        purpose: str,
        method: str = "POST",
        retry_on_rate_limit: bool = True,
    ) -> dict[str, Any]:
        max_retries = max(0, self.settings.replicate_max_retries if retry_on_rate_limit else 0)
        attempts = max_retries + 1
        for attempt in range(1, attempts + 1):
            logger.info("Replicate %s attempt %s/%s", purpose, attempt, attempts)
            response = requests.request(
                method,
                url,
                headers={"Authorization": f"Bearer {self.settings.replicate_api_token}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.settings.replicate_prediction_timeout_seconds,
            )
            if response.status_code < 400:
                return response.json()
            if response.status_code == 402:
                raise ProviderFatalError(
                    "Replicate insufficient credit. Add credit to the Replicate account linked to REPLICATE_API_TOKEN and retry after a few minutes."
                )
            if response.status_code in {401, 403}:
                raise ProviderFatalError(
                    "Replicate authentication or model access failed. Check REPLICATE_API_TOKEN permissions and selected model access."
                )
            if response.status_code == 429 and attempt <= max_retries:
                retry_after = _retry_after_seconds(response)
                fallback_delay = max(0.0, self.settings.replicate_rate_limit_delay_seconds)
                delay = (retry_after if retry_after is not None else fallback_delay) + 2.0
                logger.warning(
                    "Replicate rate limited purpose=%s attempt=%s retry_after=%s sleeping=%.1fs",
                    purpose,
                    attempt,
                    retry_after if retry_after is not None else "-",
                    delay,
                )
                time.sleep(delay)
                continue
            raise ProviderUnsupportedError(_safe_http_error(f"Replicate {purpose} failed", response))
        raise ProviderUnsupportedError(f"Replicate {purpose} failed after {max_retries} retries.")

    def _poll_replicate_prediction(self, prediction: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + self.settings.replicate_prediction_timeout_seconds
        current = prediction
        while time.monotonic() < deadline:
            status = str(current.get("status", "")).lower()
            if status == "succeeded":
                return current
            if status in {"failed", "canceled"}:
                detail = current.get("error") or current.get("logs") or status
                raise ProviderUnsupportedError(f"Replicate prediction did not complete: {detail}")
            get_url = current.get("urls", {}).get("get")
            if not get_url:
                raise ProviderUnsupportedError("Replicate prediction response did not include a polling URL.")
            time.sleep(2)
            current = self._replicate_json_request(
                get_url,
                payload=None,
                purpose="prediction_poll",
                method="GET",
            )
        raise ProviderUnsupportedError("Replicate prediction timed out before returning an image.")


class FalProvider(ImageRecreationProvider):
    def recreate_page(
        self,
        source_image_path: Path,
        prompt: str,
        output_image_path: Path,
        page_no: int,
        model_config: ModelOption,
    ) -> Path:
        del page_no
        if not self.settings.fal_provider_enabled:
            raise ProviderConfigurationError("FAL_PROVIDER_ENABLED is not true.")
        if not self.settings.effective_fal_api_key:
            raise ProviderConfigurationError("FAL_KEY is not configured.")
        url = f"https://queue.fal.run/{model_config.model}"
        payload = {
            "prompt": prompt,
            "image_url": _data_uri(source_image_path),
        }
        queued = _json_request(
            "POST",
            url,
            headers={"Authorization": f"Key {self.settings.effective_fal_api_key}"},
            payload=payload,
            timeout=self.settings.openai_request_timeout_seconds,
        )
        result = _poll_fal_result(
            queued,
            token=self.settings.effective_fal_api_key,
            timeout_seconds=self.settings.openai_request_timeout_seconds,
        )
        _save_image_reference(_extract_image_reference(result), output_image_path, self.settings.openai_request_timeout_seconds)
        return output_image_path


class HuggingFaceProvider(ImageRecreationProvider):
    def recreate_page(
        self,
        source_image_path: Path,
        prompt: str,
        output_image_path: Path,
        page_no: int,
        model_config: ModelOption,
    ) -> Path:
        del page_no
        if not self.settings.hf_provider_enabled:
            raise ProviderConfigurationError("HF_PROVIDER_ENABLED is not true.")
        if not self.settings.hf_token:
            raise ProviderConfigurationError("HF_TOKEN is not configured.")
        url = f"https://api-inference.huggingface.co/models/{model_config.model}"
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.settings.hf_token}"},
            json={
                "inputs": {
                    "image": _data_uri(source_image_path),
                    "prompt": prompt,
                }
            },
            timeout=self.settings.openai_request_timeout_seconds,
        )
        if response.status_code >= 400:
            raise ProviderUnsupportedError(_safe_http_error("Hugging Face image edit request failed", response))
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("image/"):
            output_image_path.parent.mkdir(parents=True, exist_ok=True)
            output_image_path.write_bytes(response.content)
            return output_image_path
        payload = response.json()
        _save_image_reference(_extract_image_reference(payload), output_image_path, self.settings.openai_request_timeout_seconds)
        return output_image_path


def get_image_recreation_provider(model_config: ModelOption, settings: Settings | None = None) -> ImageRecreationProvider:
    resolved_settings = settings or get_settings()
    providers: dict[str, type[ImageRecreationProvider]] = {
        "openai": OpenAIProvider,
        "replicate": ReplicateProvider,
        "fal": FalProvider,
        "huggingface": HuggingFaceProvider,
    }
    provider_cls = providers.get(model_config.provider)
    if provider_cls is None:
        raise ProviderUnsupportedError(f"Unknown image recreation provider: {model_config.provider}")
    return provider_cls(resolved_settings)


def _data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _json_request(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    response = requests.request(
        method,
        url,
        headers={**headers, "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise ProviderUnsupportedError(_safe_http_error(f"{method} {url} failed", response))
    return response.json()


def _extract_replicate_schema_fields(payload: Any) -> set[str] | None:
    if not isinstance(payload, dict):
        return None
    schema = payload.get("openapi_schema")
    if not isinstance(schema, dict):
        latest_version = payload.get("latest_version")
        if isinstance(latest_version, dict):
            schema = latest_version.get("openapi_schema")
    if not isinstance(schema, dict):
        return None
    components = schema.get("components")
    if not isinstance(components, dict):
        return None
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        return None
    input_schema = schemas.get("Input")
    if not isinstance(input_schema, dict):
        return None
    properties = input_schema.get("properties")
    if not isinstance(properties, dict):
        return None
    return set(properties.keys())


def _retry_after_seconds(response: requests.Response) -> float | None:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        retry_after = payload.get("retry_after")
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    header_value = response.headers.get("Retry-After")
    if header_value:
        try:
            return max(0.0, float(header_value))
        except ValueError:
            pass
    return None


def _poll_fal_result(queued: dict[str, Any], token: str, timeout_seconds: float) -> dict[str, Any]:
    if _extract_image_reference_or_none(queued):
        return queued

    status_url = queued.get("status_url")
    response_url = queued.get("response_url")
    if not status_url and not response_url:
        raise ProviderUnsupportedError("fal.ai response did not include status_url or response_url.")

    deadline = time.monotonic() + timeout_seconds
    current = queued
    while time.monotonic() < deadline:
        status_value = str(current.get("status", "")).upper()
        response_url = current.get("response_url") or response_url
        if status_value in {"COMPLETED", "SUCCEEDED", "SUCCESS"} and response_url:
            return _json_request("GET", response_url, headers={"Authorization": f"Key {token}"}, timeout=timeout_seconds)
        if status_value in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            raise ProviderUnsupportedError(f"fal.ai request did not complete: {current}")
        if status_url:
            time.sleep(2)
            current = _json_request("GET", status_url, headers={"Authorization": f"Key {token}"}, timeout=timeout_seconds)
            continue
        break
    raise ProviderUnsupportedError("fal.ai request timed out before returning an image.")


def _extract_image_reference(payload: Any) -> str:
    reference = _extract_image_reference_or_none(payload)
    if not reference:
        raise ProviderUnsupportedError("Provider response did not contain a downloadable image URL or data URI.")
    return reference


def _extract_image_reference_or_none(payload: Any) -> str | None:
    if isinstance(payload, str):
        if payload.startswith("http://") or payload.startswith("https://") or payload.startswith("data:image/"):
            return payload
        return None
    if isinstance(payload, list):
        for item in payload:
            reference = _extract_image_reference_or_none(item)
            if reference:
                return reference
        return None
    if isinstance(payload, dict):
        for key in ("output", "image", "image_url", "url"):
            reference = _extract_image_reference_or_none(payload.get(key))
            if reference:
                return reference
        for key in ("images", "data"):
            reference = _extract_image_reference_or_none(payload.get(key))
            if reference:
                return reference
    return None


def _save_image_reference(reference: str, output_path: Path, timeout_seconds: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if reference.startswith("data:image/"):
        _, encoded = reference.split(",", 1)
        output_path.write_bytes(base64.b64decode(encoded))
        return
    response = requests.get(reference, timeout=timeout_seconds)
    if response.status_code >= 400:
        raise ProviderUnsupportedError(_safe_http_error("Provider image download failed", response))
    output_path.write_bytes(response.content)


def _image_size_or_none(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def _safe_http_error(message: str, response: requests.Response) -> str:
    body = response.text[:500] if response.text else ""
    return f"{message}: HTTP {response.status_code} {body}"
