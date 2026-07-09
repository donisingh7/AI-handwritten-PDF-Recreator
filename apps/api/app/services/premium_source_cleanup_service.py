from dataclasses import dataclass
from pathlib import Path
import logging

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PremiumSourceCleanupResult:
    strategy: str
    input_size: tuple[int, int]
    output_size: tuple[int, int]
    changed_pixel_ratio: float


class PremiumSourceCleanupService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        cv2.setNumThreads(1)

    def clean_source(self, source_path: Path, output_path: Path) -> PremiumSourceCleanupResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.settings.premium_source_cleanup_enabled:
            with Image.open(source_path) as image:
                cleaned = ImageOps.exif_transpose(image).convert("RGB")
                cleaned.save(output_path, format="PNG", optimize=True)
                size = cleaned.size
            return PremiumSourceCleanupResult("disabled_copy", size, size, 0.0)

        with Image.open(source_path) as image:
            original = ImageOps.exif_transpose(image).convert("RGB")
        original_size = original.size
        rgb = np.asarray(original, dtype=np.uint8)
        cleaned = rgb.copy()

        if self.settings.premium_source_background_whiten:
            cleaned = self._whiten_background(cleaned)

        ink_mask = self._ink_mask(rgb)
        protected_mask = self._protected_content_mask(rgb, cleaned, ink_mask)

        if self.settings.premium_remove_source_horizontal_lines:
            cleaned = self._remove_long_faint_lines(cleaned, rgb, protected_mask, axis="horizontal")
        if self.settings.premium_remove_source_vertical_lines:
            cleaned = self._remove_long_faint_lines(cleaned, rgb, protected_mask, axis="vertical")
        if self.settings.premium_remove_source_scan_marks:
            cleaned = self._remove_scan_marks(cleaned, protected_mask)

        changed_pixel_ratio = float(np.mean(np.any(np.abs(cleaned.astype(np.int16) - rgb.astype(np.int16)) > 10, axis=2)))
        Image.fromarray(cleaned, mode="RGB").save(output_path, format="PNG", optimize=True)
        logger.info(
            "premium source cleanup strategy=advanced_%s input=%sx%s output=%sx%s changed_pixel_ratio=%.4f",
            self.settings.premium_source_line_removal_strength_normalized,
            original_size[0],
            original_size[1],
            cleaned.shape[1],
            cleaned.shape[0],
            changed_pixel_ratio,
        )
        original.close()
        return PremiumSourceCleanupResult(
            strategy=f"advanced_{self.settings.premium_source_line_removal_strength_normalized}",
            input_size=original_size,
            output_size=(cleaned.shape[1], cleaned.shape[0]),
            changed_pixel_ratio=changed_pixel_ratio,
        )

    def _whiten_background(self, rgb: np.ndarray) -> np.ndarray:
        height, width = rgb.shape[:2]
        kernel_size = max(31, min(91, int(min(height, width) * 0.04)))
        if kernel_size % 2 == 0:
            kernel_size += 1
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
        normalized_channels: list[np.ndarray] = []
        for channel_index in range(3):
            channel = rgb[:, :, channel_index]
            background = cv2.morphologyEx(channel, cv2.MORPH_CLOSE, kernel)
            background = cv2.GaussianBlur(background, (0, 0), sigmaX=kernel_size / 2, sigmaY=kernel_size / 2)
            normalized = cv2.divide(channel, np.maximum(background, 1), scale=255)
            normalized_channels.append(normalized)
        normalized = cv2.merge(normalized_channels)

        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        saturation = hsv[:, :, 1]
        paper_mask = (gray > 150) & (saturation < 55)
        output = cv2.addWeighted(rgb, 0.25, normalized, 0.75, 0)
        output[paper_mask & (gray > 190)] = [255, 255, 255]
        return output.astype(np.uint8)

    def _ink_mask(self, rgb: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        saturation = hsv[:, :, 1]
        mask = (gray < 160) | ((saturation > 45) & (gray < 235))
        return cv2.dilate(mask.astype(np.uint8), np.ones((2, 2), dtype=np.uint8), iterations=1).astype(bool)

    def _protected_content_mask(self, original: np.ndarray, cleaned: np.ndarray, ink_mask: np.ndarray) -> np.ndarray:
        del cleaned
        gray = cv2.cvtColor(original, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 60, 170)
        edge_mask = cv2.dilate(edges, np.ones((2, 2), dtype=np.uint8), iterations=1).astype(bool)
        return ink_mask | ((gray < 145) & edge_mask)

    def _remove_long_faint_lines(self, cleaned: np.ndarray, original: np.ndarray, protected_mask: np.ndarray, axis: str) -> np.ndarray:
        gray = cv2.cvtColor(original, cv2.COLOR_RGB2GRAY)
        hsv = cv2.cvtColor(original, cv2.COLOR_RGB2HSV)
        saturation = hsv[:, :, 1]
        height, width = gray.shape
        strength = self.settings.premium_source_line_removal_strength_normalized
        faint_upper = 245 if strength == "strong" else 238
        faint_lower = 150 if strength == "strong" else 170
        faint_mask = (gray > faint_lower) & (gray < faint_upper) & (saturation < 65) & (~protected_mask)

        if axis == "horizontal":
            kernel_width = max(35, width // (16 if strength == "strong" else 12))
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1))
        else:
            kernel_height = max(35, height // (16 if strength == "strong" else 12))
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_height))

        line_mask = cv2.morphologyEx(faint_mask.astype(np.uint8), cv2.MORPH_OPEN, kernel).astype(bool)
        output = cleaned.copy()
        output[line_mask] = [255, 255, 255]
        return output

    def _remove_scan_marks(self, cleaned: np.ndarray, protected_mask: np.ndarray) -> np.ndarray:
        output = cleaned.copy()
        gray = cv2.cvtColor(output, cv2.COLOR_RGB2GRAY)
        non_content = (gray > 170) & (~protected_mask)
        output[non_content] = np.maximum(output[non_content], [250, 250, 250])
        output[non_content & (gray > 205)] = [255, 255, 255]

        tiny_mask = (gray < 238) & (~protected_mask)
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(tiny_mask.astype(np.uint8), 8)
        for component_index in range(1, component_count):
            area = stats[component_index, cv2.CC_STAT_AREA]
            width = stats[component_index, cv2.CC_STAT_WIDTH]
            height = stats[component_index, cv2.CC_STAT_HEIGHT]
            if area <= 24 and width <= 10 and height <= 10:
                output[labels == component_index] = [255, 255, 255]
        return output
