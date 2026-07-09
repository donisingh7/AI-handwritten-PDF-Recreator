from dataclasses import dataclass
from pathlib import Path
import gc
import logging

import cv2
import numpy as np
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheapCleanupResult:
    strategy: str
    input_size: tuple[int, int]
    output_size: tuple[int, int]
    fallback_used: bool
    visual_change_score: float | None = None
    changed_pixel_ratio: float | None = None


@dataclass(frozen=True)
class CheapCleanupOptions:
    preset: str
    background_strength: float
    contrast_strength: float
    despeckle_strength: str
    remove_light_lines: bool
    ink_darken: bool


class CheapCleanupService:
    def __init__(
        self,
        cleanup_max_width: int = 1654,
        cleanup_max_height: int = 2339,
        enable_advanced_cleanup: bool = True,
        preset: str = "strong_print",
        background_strength: float = 0.85,
        contrast_strength: float = 1.25,
        despeckle_strength: str = "medium",
        remove_light_lines: bool = True,
        ink_darken: bool = True,
    ) -> None:
        self.cleanup_max_width = cleanup_max_width
        self.cleanup_max_height = cleanup_max_height
        self.enable_advanced_cleanup = enable_advanced_cleanup
        self.options = self._resolve_options(
            preset=preset,
            background_strength=background_strength,
            contrast_strength=contrast_strength,
            despeckle_strength=despeckle_strength,
            remove_light_lines=remove_light_lines,
            ink_darken=ink_darken,
        )
        cv2.setNumThreads(1)

    def clean_page_to_a4(
        self,
        source_image_path: Path | str,
        output_image_path: Path | str,
        final_width: int,
        final_height: int,
    ) -> CheapCleanupResult:
        source_path = Path(source_image_path)
        output_path = Path(output_image_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        image: Image.Image | None = None
        working_image: Image.Image | None = None
        cleaned: Image.Image | None = None
        cropped: Image.Image | None = None
        canvas: Image.Image | None = None
        input_size = (0, 0)
        try:
            if not self.enable_advanced_cleanup:
                input_size = self._fallback_fit_to_a4(source_path, output_path, final_width, final_height)
                return CheapCleanupResult(
                    strategy="fallback_normalize",
                    input_size=input_size,
                    output_size=(final_width, final_height),
                    fallback_used=True,
                )

            image = self._load_image(source_path)
            input_size = image.size
            working_image = self._resize_for_cleanup(image)
            cleaned, visual_change_score, changed_pixel_ratio = self._clean_scan(working_image)
            cropped = self._crop_safe_borders(cleaned)
            canvas = self._fit_to_a4_canvas(cropped, final_width, final_height)
            canvas.save(output_path, format="PNG", dpi=(300, 300), optimize=True)
            return CheapCleanupResult(
                strategy=f"advanced_{self.options.preset}",
                input_size=input_size,
                output_size=(final_width, final_height),
                fallback_used=False,
                visual_change_score=visual_change_score,
                changed_pixel_ratio=changed_pixel_ratio,
            )
        except Exception as exc:
            logger.warning("Cheap cleanup advanced path failed for %s; using fallback normalize: %s", source_path, exc)
            if input_size == (0, 0):
                input_size = self._image_size_or_zero(source_path)
            self._fallback_fit_to_a4(source_path, output_path, final_width, final_height)
            return CheapCleanupResult(
                strategy="fallback_normalize",
                input_size=input_size,
                output_size=(final_width, final_height),
                fallback_used=True,
            )
        finally:
            self._close_images(image, working_image, cleaned, cropped, canvas)
            del image, working_image, cleaned, cropped, canvas
            gc.collect()

    def _resolve_options(
        self,
        preset: str,
        background_strength: float,
        contrast_strength: float,
        despeckle_strength: str,
        remove_light_lines: bool,
        ink_darken: bool,
    ) -> CheapCleanupOptions:
        normalized_preset = preset.strip().lower()
        if normalized_preset not in {"light", "strong_print", "high_contrast"}:
            normalized_preset = "strong_print"

        background_strength = self._clamp(background_strength, 0.0, 1.0)
        contrast_strength = self._clamp(contrast_strength, 1.0, 1.8)
        normalized_despeckle = despeckle_strength.strip().lower()
        if normalized_despeckle not in {"low", "medium", "high"}:
            normalized_despeckle = "medium"

        if normalized_preset == "light":
            return CheapCleanupOptions(
                preset=normalized_preset,
                background_strength=min(background_strength, 0.55),
                contrast_strength=min(contrast_strength, 1.10),
                despeckle_strength="low",
                remove_light_lines=False,
                ink_darken=False,
            )
        if normalized_preset == "high_contrast":
            return CheapCleanupOptions(
                preset=normalized_preset,
                background_strength=max(background_strength, 0.95),
                contrast_strength=max(contrast_strength, 1.45),
                despeckle_strength="high",
                remove_light_lines=True,
                ink_darken=True,
            )
        return CheapCleanupOptions(
            preset=normalized_preset,
            background_strength=background_strength,
            contrast_strength=contrast_strength,
            despeckle_strength=normalized_despeckle,
            remove_light_lines=remove_light_lines,
            ink_darken=ink_darken,
        )

    def _load_image(self, source_path: Path) -> Image.Image:
        with Image.open(source_path) as source_image:
            return ImageOps.exif_transpose(source_image).convert("RGB")

    def _resize_for_cleanup(self, image: Image.Image) -> Image.Image:
        max_size = (self.cleanup_max_width, self.cleanup_max_height)
        if image.width <= max_size[0] and image.height <= max_size[1]:
            return image.copy()
        return ImageOps.contain(image, max_size, method=Image.Resampling.LANCZOS)

    def _clean_scan(self, image: Image.Image) -> tuple[Image.Image, float, float]:
        rgb = np.asarray(image, dtype=np.uint8)
        normalized_rgb = self._normalize_background(rgb)

        hsv_original = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        gray_original = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        saturation_original = hsv_original[:, :, 1]
        ink_mask = (gray_original < 178) | ((saturation_original > 38) & (gray_original < 238))
        ink_mask = cv2.dilate(ink_mask.astype(np.uint8), np.ones((2, 2), dtype=np.uint8), iterations=1).astype(bool)

        strength = self.options.background_strength
        cleaned = cv2.addWeighted(rgb, 1.0 - strength, normalized_rgb, strength, 0)

        hsv_cleaned = cv2.cvtColor(cleaned, cv2.COLOR_RGB2HSV)
        gray_cleaned = cv2.cvtColor(cleaned, cv2.COLOR_RGB2GRAY)
        saturation_cleaned = hsv_cleaned[:, :, 1]

        paper_mask = (~ink_mask) & ((gray_cleaned > 172) | ((gray_cleaned > 146) & (saturation_cleaned < 42)))
        cleaned = self._blend_pixels_to_white(cleaned, paper_mask, 0.72 + strength * 0.25)

        if self.options.remove_light_lines:
            line_mask = (~ink_mask) & (gray_original > 185) & (gray_original < 245) & (saturation_original < 48)
            cleaned = self._blend_pixels_to_white(cleaned, line_mask, 0.62 if self.options.preset == "strong_print" else 0.78)

        cleaned[ink_mask] = np.minimum(cleaned[ink_mask], normalized_rgb[ink_mask])
        cleaned = self._increase_contrast(cleaned, ink_mask)
        cleaned = self._remove_specks(cleaned, ink_mask)

        if self.options.ink_darken:
            darken_factor = 0.86 if self.options.preset == "strong_print" else 0.78
            ink_values = cleaned[ink_mask].astype(np.float32) * darken_factor
            cleaned[ink_mask] = np.clip(ink_values, 0, 255).astype(np.uint8)

        cleaned = np.clip(cleaned, 0, 255).astype(np.uint8)
        visual_change_score, changed_pixel_ratio = self._visual_change(rgb, cleaned)
        result = Image.fromarray(cleaned, mode="RGB")
        del (
            normalized_rgb,
            hsv_original,
            gray_original,
            saturation_original,
            ink_mask,
            hsv_cleaned,
            gray_cleaned,
            saturation_cleaned,
            paper_mask,
            cleaned,
        )
        return result, visual_change_score, changed_pixel_ratio

    def _normalize_background(self, rgb: np.ndarray) -> np.ndarray:
        height, width = rgb.shape[:2]
        kernel_size = max(25, min(71, int(min(height, width) * 0.035)))
        if kernel_size % 2 == 0:
            kernel_size += 1
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
        normalized_channels: list[np.ndarray] = []
        for channel_index in range(3):
            channel = rgb[:, :, channel_index]
            background = cv2.morphologyEx(channel, cv2.MORPH_CLOSE, kernel)
            background = cv2.GaussianBlur(background, (0, 0), sigmaX=max(12, kernel_size / 2), sigmaY=max(12, kernel_size / 2))
            background = np.maximum(background, 1)
            normalized = cv2.divide(channel, background, scale=255)
            normalized_channels.append(normalized)
        normalized_rgb = cv2.merge(normalized_channels)
        del normalized_channels, kernel
        return normalized_rgb

    def _increase_contrast(self, image: np.ndarray, ink_mask: np.ndarray) -> np.ndarray:
        contrast = self.options.contrast_strength
        if contrast <= 1.01:
            return image
        contrasted = (image.astype(np.float32) - 128.0) * contrast + 128.0
        contrasted = np.clip(contrasted, 0, 255).astype(np.uint8)
        paper_mask = ~ink_mask
        image[paper_mask] = np.maximum(image[paper_mask], contrasted[paper_mask])
        image[ink_mask] = np.minimum(image[ink_mask], contrasted[ink_mask])
        return image

    def _remove_specks(self, image: np.ndarray, ink_mask: np.ndarray) -> np.ndarray:
        max_area_by_strength = {"low": 5, "medium": 14, "high": 26}
        max_area = max_area_by_strength[self.options.despeckle_strength]
        output = image.copy()
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(ink_mask.astype(np.uint8), 8)
        for component_index in range(1, component_count):
            area = stats[component_index, cv2.CC_STAT_AREA]
            width = stats[component_index, cv2.CC_STAT_WIDTH]
            height = stats[component_index, cv2.CC_STAT_HEIGHT]
            if area <= max_area and width <= 7 and height <= 7:
                output[labels == component_index] = [255, 255, 255]

        if self.options.despeckle_strength in {"medium", "high"}:
            median_kernel = 3 if self.options.despeckle_strength == "medium" else 5
            median = cv2.medianBlur(output, median_kernel)
            output[~ink_mask] = median[~ink_mask]
        del labels, stats
        return output

    def _crop_safe_borders(self, image: Image.Image) -> Image.Image:
        arr = np.asarray(image, dtype=np.uint8)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        content_mask = gray < 245
        ys, xs = np.where(content_mask)
        if xs.size == 0 or ys.size == 0:
            del arr, gray, content_mask, ys, xs
            return image

        height, width = gray.shape
        left, right = int(xs.min()), int(xs.max())
        top, bottom = int(ys.min()), int(ys.max())
        pad_x = max(18, int(width * 0.025))
        pad_y = max(18, int(height * 0.025))
        left = max(0, left - pad_x)
        right = min(width - 1, right + pad_x)
        top = max(0, top - pad_y)
        bottom = min(height - 1, bottom + pad_y)

        crop_width = right - left + 1
        crop_height = bottom - top + 1
        if crop_width < width * 0.45 or crop_height < height * 0.45:
            del arr, gray, content_mask, ys, xs
            return image
        cropped = image.crop((left, top, right + 1, bottom + 1))
        del arr, gray, content_mask, ys, xs
        return cropped

    def _fit_to_a4_canvas(self, image: Image.Image, final_width: int, final_height: int) -> Image.Image:
        margin_x = int(final_width * 0.025)
        margin_y = int(final_height * 0.025)
        max_size = (final_width - margin_x * 2, final_height - margin_y * 2)

        rgb_image = image.convert("RGB")
        fitted = ImageOps.contain(rgb_image, max_size, method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (final_width, final_height), "white")
        x = (final_width - fitted.width) // 2
        y = (final_height - fitted.height) // 2
        canvas.paste(fitted, (x, y))
        fitted.close()
        if fitted is not rgb_image:
            rgb_image.close()
        return canvas

    def _fallback_fit_to_a4(
        self,
        source_image_path: Path,
        output_image_path: Path,
        final_width: int,
        final_height: int,
    ) -> tuple[int, int]:
        image: Image.Image | None = None
        canvas: Image.Image | None = None
        image = self._load_image(source_image_path)
        input_size = image.size
        try:
            canvas = self._fit_to_a4_canvas(image, final_width, final_height)
            canvas.save(output_image_path, format="PNG", dpi=(300, 300), optimize=True)
            return input_size
        finally:
            self._close_images(image, canvas)
            del image, canvas
            gc.collect()

    def _image_size_or_zero(self, source_path: Path) -> tuple[int, int]:
        try:
            with Image.open(source_path) as image:
                return image.size
        except Exception:
            return (0, 0)

    def _blend_pixels_to_white(self, image: np.ndarray, mask: np.ndarray, amount: float) -> np.ndarray:
        if not np.any(mask):
            return image
        amount = self._clamp(amount, 0.0, 1.0)
        output = image.copy()
        selected = output[mask].astype(np.float32)
        output[mask] = np.clip(selected + (255.0 - selected) * amount, 0, 255).astype(np.uint8)
        return output

    def _visual_change(self, before: np.ndarray, after: np.ndarray) -> tuple[float, float]:
        diff = np.abs(after.astype(np.int16) - before.astype(np.int16))
        visual_change_score = float(diff.mean() / 255.0)
        changed_pixel_ratio = float(np.mean(np.any(diff > 12, axis=2)))
        return visual_change_score, changed_pixel_ratio

    def _close_images(self, *images: Image.Image | None) -> None:
        for image in images:
            if image is not None:
                image.close()

    def _clamp(self, value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
