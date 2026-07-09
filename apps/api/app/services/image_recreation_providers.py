from abc import ABC, abstractmethod
import base64
import time
from pathlib import Path
from typing import Any

import requests

from app.config import Settings, get_settings
from app.services.model_options_service import ModelOption


class ProviderConfigurationError(RuntimeError):
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

        url = f"https://api.replicate.com/v1/models/{model_config.model}/predictions"
        payload = {
            "input": {
                "image": _data_uri(source_image_path),
                "prompt": prompt,
                "output_format": "png",
            }
        }
        prediction = _json_request(
            "POST",
            url,
            headers={"Authorization": f"Bearer {self.settings.replicate_api_token}"},
            payload=payload,
            timeout=self.settings.openai_request_timeout_seconds,
        )
        result = _poll_replicate_prediction(
            prediction,
            token=self.settings.replicate_api_token,
            timeout_seconds=self.settings.openai_request_timeout_seconds,
        )
        _save_image_reference(_extract_image_reference(result), output_image_path, self.settings.openai_request_timeout_seconds)
        return output_image_path


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


def _poll_replicate_prediction(prediction: dict[str, Any], token: str, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
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
        current = _json_request("GET", get_url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout_seconds)
    raise ProviderUnsupportedError("Replicate prediction timed out before returning an image.")


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


def _safe_http_error(message: str, response: requests.Response) -> str:
    body = response.text[:500] if response.text else ""
    return f"{message}: HTTP {response.status_code} {body}"
