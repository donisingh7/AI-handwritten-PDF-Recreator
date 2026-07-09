from dataclasses import dataclass
from pathlib import Path
import logging

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PremiumOutputCleanupResult:
    strategy: str
    input_size: tuple[int, int]
    output_size: tuple[int, int]


class PremiumOutputCleanupService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        cv2.setNumThreads(1)

    def clean_and_fit_to_a4(self, source_path: Path, output_path: Path) -> PremiumOutputCleanupResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source_path) as image:
            source = ImageOps.exif_transpose(image).convert("RGB")
        input_size = source.size
        if self.settings.premium_output_cleanup_enabled:
            cleaned = self._clean_output(np.asarray(source, dtype=np.uint8))
            working = Image.fromarray(cleaned, mode="RGB")
        else:
            working = source.copy()
        canvas = self._fit_to_a4_canvas(working)
        canvas.save(output_path, format="PNG", dpi=(self.settings.final_print_dpi, self.settings.final_print_dpi), optimize=True)
        logger.info(
            "premium output cleanup strategy=%s input=%sx%s output=%sx%s",
            "advanced" if self.settings.premium_output_cleanup_enabled else "disabled_normalize",
            input_size[0],
            input_size[1],
            canvas.width,
            canvas.height,
        )
        source.close()
        working.close()
        canvas.close()
        return PremiumOutputCleanupResult(
            strategy="advanced" if self.settings.premium_output_cleanup_enabled else "disabled_normalize",
            input_size=input_size,
            output_size=(self.settings.final_a4_width_px, self.settings.final_a4_height_px),
        )

    def _clean_output(self, rgb: np.ndarray) -> np.ndarray:
        output = rgb.copy()
        hsv = cv2.cvtColor(output, cv2.COLOR_RGB2HSV)
        gray = cv2.cvtColor(output, cv2.COLOR_RGB2GRAY)
        saturation = hsv[:, :, 1]
        blue_ink = (hsv[:, :, 0] >= 85) & (hsv[:, :, 0] <= 135) & (saturation > 35) & (gray < 245)
        black_ink = gray < 145
        ink_mask = cv2.dilate((blue_ink | black_ink).astype(np.uint8), np.ones((2, 2), dtype=np.uint8), iterations=1).astype(bool)

        if self.settings.premium_output_force_white_background:
            near_white = (gray > 190) & (saturation < 65) & (~ink_mask)
            output[near_white] = [255, 255, 255]

        if self.settings.premium_output_remove_residual_lines:
            output = self._remove_residual_lines(output, rgb, ink_mask)

        if self.settings.premium_output_despeckle:
            output = self._despeckle(output, ink_mask)

        if self.settings.premium_output_preserve_blue_black_only:
            output = self._reduce_non_ink_colored_noise(output, ink_mask)

        return output.astype(np.uint8)

    def _remove_residual_lines(self, output: np.ndarray, original: np.ndarray, ink_mask: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(original, cv2.COLOR_RGB2GRAY)
        hsv = cv2.cvtColor(original, cv2.COLOR_RGB2HSV)
        saturation = hsv[:, :, 1]
        faint = (gray > 155) & (gray < 245) & (saturation < 70) & (~ink_mask)
        height, width = gray.shape
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(45, width // 14), 1))
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(45, height // 14)))
        horizontal = cv2.morphologyEx(faint.astype(np.uint8), cv2.MORPH_OPEN, horizontal_kernel).astype(bool)
        vertical = cv2.morphologyEx(faint.astype(np.uint8), cv2.MORPH_OPEN, vertical_kernel).astype(bool)
        cleaned = output.copy()
        cleaned[horizontal | vertical] = [255, 255, 255]
        return cleaned

    def _despeckle(self, output: np.ndarray, ink_mask: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(output, cv2.COLOR_RGB2GRAY)
        noise_mask = (gray < 245) & (~ink_mask)
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(noise_mask.astype(np.uint8), 8)
        cleaned = output.copy()
        for component_index in range(1, component_count):
            area = stats[component_index, cv2.CC_STAT_AREA]
            width = stats[component_index, cv2.CC_STAT_WIDTH]
            height = stats[component_index, cv2.CC_STAT_HEIGHT]
            if area <= 20 and width <= 9 and height <= 9:
                cleaned[labels == component_index] = [255, 255, 255]
        return cleaned

    def _reduce_non_ink_colored_noise(self, output: np.ndarray, ink_mask: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(output, cv2.COLOR_RGB2HSV)
        gray = cv2.cvtColor(output, cv2.COLOR_RGB2GRAY)
        saturation = hsv[:, :, 1]
        colored_noise = (saturation > 20) & (gray > 170) & (~ink_mask)
        cleaned = output.copy()
        cleaned[colored_noise] = [255, 255, 255]
        return cleaned

    def _fit_to_a4_canvas(self, image: Image.Image) -> Image.Image:
        width = self.settings.final_a4_width_px
        height = self.settings.final_a4_height_px
        margin_x = int(width * 0.025)
        margin_y = int(height * 0.025)
        max_size = (width - margin_x * 2, height - margin_y * 2)
        fitted = ImageOps.contain(image, max_size, method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (width, height), "white")
        x = (width - fitted.width) // 2
        y = (height - fitted.height) // 2
        canvas.paste(fitted, (x, y))
        fitted.close()
        return canvas
