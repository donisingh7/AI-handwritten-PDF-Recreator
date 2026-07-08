from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps


class CheapCleanupService:
    def clean_page_to_a4(
        self,
        source_image_path: Path | str,
        output_image_path: Path | str,
        final_width: int,
        final_height: int,
    ) -> Path:
        source_path = Path(source_image_path)
        output_path = Path(output_image_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with Image.open(source_path) as source_image:
                image = ImageOps.exif_transpose(source_image).convert("RGB")
            cleaned = self._clean_scan(image)
            cleaned = self._crop_safe_borders(cleaned)
            canvas = self._fit_to_a4_canvas(cleaned, final_width, final_height)
            canvas.save(output_path, format="PNG", dpi=(300, 300), optimize=True)
        except Exception:
            self._fallback_fit_to_a4(source_path, output_path, final_width, final_height)
        return output_path

    def _clean_scan(self, image: Image.Image) -> Image.Image:
        rgb = np.asarray(image, dtype=np.uint8)

        # Estimate slow-changing paper/shadow color, then divide it out. This
        # keeps handwriting colors but pushes grey paper and shadows toward white.
        normalized_channels: list[np.ndarray] = []
        for channel_index in range(3):
            channel = rgb[:, :, channel_index]
            background = cv2.GaussianBlur(channel, (0, 0), sigmaX=25, sigmaY=25)
            normalized = cv2.divide(channel, background, scale=255)
            normalized_channels.append(normalized)
        normalized_rgb = cv2.merge(normalized_channels)

        hsv = cv2.cvtColor(normalized_rgb, cv2.COLOR_RGB2HSV)
        gray = cv2.cvtColor(normalized_rgb, cv2.COLOR_RGB2GRAY)
        saturation = hsv[:, :, 1]

        # Ink is usually dark and/or saturated. Use this mask to avoid erasing
        # handwriting, diagrams, and blue/black pen strokes during whitening.
        ink_mask = (gray < 205) | ((saturation > 45) & (gray < 235))

        cleaned = normalized_rgb.copy()

        # Turn paper-like pixels white. Light ruled lines and margin lines are
        # often pale and low-saturation, so they fade here without touching ink.
        paper_mask = (~ink_mask) & ((gray > 188) | ((gray > 165) & (saturation < 36)))
        cleaned[paper_mask] = [255, 255, 255]

        # Remove isolated scan specks while leaving connected handwriting intact.
        cleaned = self._remove_small_components(cleaned, ink_mask)

        # Light denoising smooths scan grain but avoids thresholding away strokes.
        denoised = cv2.fastNlMeansDenoisingColored(cleaned, None, 4, 4, 7, 21)
        denoised[ink_mask] = cleaned[ink_mask]
        return Image.fromarray(denoised, mode="RGB")

    def _remove_small_components(self, image: np.ndarray, ink_mask: np.ndarray) -> np.ndarray:
        output = image.copy()
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(ink_mask.astype(np.uint8), 8)
        for component_index in range(1, component_count):
            area = stats[component_index, cv2.CC_STAT_AREA]
            width = stats[component_index, cv2.CC_STAT_WIDTH]
            height = stats[component_index, cv2.CC_STAT_HEIGHT]
            if area <= 10 and width <= 5 and height <= 5:
                output[labels == component_index] = [255, 255, 255]
        return output

    def _crop_safe_borders(self, image: Image.Image) -> Image.Image:
        arr = np.asarray(image, dtype=np.uint8)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        content_mask = gray < 245
        ys, xs = np.where(content_mask)
        if xs.size == 0 or ys.size == 0:
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
            return image
        return image.crop((left, top, right + 1, bottom + 1))

    def _fit_to_a4_canvas(self, image: Image.Image, final_width: int, final_height: int) -> Image.Image:
        margin_x = int(final_width * 0.025)
        margin_y = int(final_height * 0.025)
        max_size = (final_width - margin_x * 2, final_height - margin_y * 2)

        fitted = ImageOps.contain(image.convert("RGB"), max_size, method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (final_width, final_height), "white")
        x = (final_width - fitted.width) // 2
        y = (final_height - fitted.height) // 2
        canvas.paste(fitted, (x, y))
        return canvas

    def _fallback_fit_to_a4(
        self,
        source_image_path: Path,
        output_image_path: Path,
        final_width: int,
        final_height: int,
    ) -> None:
        with Image.open(source_image_path) as source_image:
            image = ImageOps.exif_transpose(source_image).convert("RGB")
        canvas = self._fit_to_a4_canvas(image, final_width, final_height)
        canvas.save(output_image_path, format="PNG", dpi=(300, 300), optimize=True)
