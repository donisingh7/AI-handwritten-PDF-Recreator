from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from app.config import Settings, get_settings


class ImagePostprocessService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def clean_and_fit_to_a4(self, source_path: Path, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source_path) as image:
            cleaned = self._normalize_white_background(image.convert("RGB"))
            cleaned = self._remove_tiny_noise(cleaned)
            canvas = self._fit_to_a4_canvas(cleaned)
            canvas.save(
                output_path,
                format="PNG",
                dpi=(self.settings.final_print_dpi, self.settings.final_print_dpi),
                optimize=True,
            )
        return output_path

    def _normalize_white_background(self, image: Image.Image) -> Image.Image:
        arr = np.asarray(image).copy()
        red = arr[:, :, 0].astype(np.int16)
        green = arr[:, :, 1].astype(np.int16)
        blue = arr[:, :, 2].astype(np.int16)
        brightness = (red + green + blue) / 3
        channel_spread = np.maximum.reduce([red, green, blue]) - np.minimum.reduce([red, green, blue])

        near_white = (brightness > 218) & (channel_spread < 42)
        faded_grey_paper = (brightness > 185) & (channel_spread < 24)
        arr[near_white | faded_grey_paper] = [255, 255, 255]
        return Image.fromarray(arr.astype(np.uint8), mode="RGB")

    def _remove_tiny_noise(self, image: Image.Image) -> Image.Image:
        arr = np.asarray(image).copy()
        ink_mask = np.any(arr < 238, axis=2)
        neighbor_count = np.zeros(ink_mask.shape, dtype=np.uint8)
        for y_offset in (-1, 0, 1):
            for x_offset in (-1, 0, 1):
                if y_offset == 0 and x_offset == 0:
                    continue
                shifted = np.roll(np.roll(ink_mask, y_offset, axis=0), x_offset, axis=1)
                if y_offset == -1:
                    shifted[-1, :] = False
                elif y_offset == 1:
                    shifted[0, :] = False
                if x_offset == -1:
                    shifted[:, -1] = False
                elif x_offset == 1:
                    shifted[:, 0] = False
                neighbor_count += shifted

        isolated_noise = ink_mask & (neighbor_count <= 1)
        arr[isolated_noise] = [255, 255, 255]
        return Image.fromarray(arr.astype(np.uint8), mode="RGB")

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
        return canvas
