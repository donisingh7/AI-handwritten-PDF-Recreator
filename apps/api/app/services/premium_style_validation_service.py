from dataclasses import dataclass
from pathlib import Path
import logging

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PremiumStyleScores:
    background_whiteness_score: float
    horizontal_line_score: float
    vertical_line_score: float
    nonwhite_artefact_ratio: float
    black_ink_ratio: float
    blue_ink_ratio: float


@dataclass(frozen=True)
class PremiumStyleValidationResult:
    passed: bool
    warnings: list[str]
    scores: PremiumStyleScores


class PremiumStyleValidationService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        cv2.setNumThreads(1)

    def validate(self, image_path: Path) -> PremiumStyleValidationResult:
        with Image.open(image_path) as image:
            rgb = np.asarray(ImageOps.exif_transpose(image).convert("RGB"), dtype=np.uint8)

        scores = self._score(rgb)
        warnings: list[str] = []
        if scores.background_whiteness_score < self.settings.premium_background_whiteness_threshold:
            warnings.append("background_not_white_enough")
        if scores.horizontal_line_score > self.settings.premium_max_horizontal_line_score_value:
            warnings.append("residual_horizontal_lines")
        if scores.vertical_line_score > self.settings.premium_max_vertical_line_score_value:
            warnings.append("residual_vertical_lines")
        if scores.nonwhite_artefact_ratio > self.settings.premium_max_nonwhite_artefact_ratio:
            warnings.append("excess_nonwhite_artefacts")
        if scores.black_ink_ratio < 0.00003:
            warnings.append("black_heading_ink_low")
        if scores.blue_ink_ratio < 0.00003:
            warnings.append("blue_body_ink_low")

        passed = not warnings if self.settings.premium_style_validation_enabled else True
        logger.info(
            (
                "premium style validation passed=%s background_whiteness=%.4f horizontal_line_score=%.4f "
                "vertical_line_score=%.4f nonwhite_artefact_ratio=%.4f black_ink_ratio=%.6f blue_ink_ratio=%.6f warnings=%s"
            ),
            passed,
            scores.background_whiteness_score,
            scores.horizontal_line_score,
            scores.vertical_line_score,
            scores.nonwhite_artefact_ratio,
            scores.black_ink_ratio,
            scores.blue_ink_ratio,
            ",".join(warnings) if warnings else "-",
        )
        return PremiumStyleValidationResult(passed=passed, warnings=warnings, scores=scores)

    def _score(self, rgb: np.ndarray) -> PremiumStyleScores:
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        saturation = hsv[:, :, 1]
        blue_ink = (hsv[:, :, 0] >= 85) & (hsv[:, :, 0] <= 135) & (saturation > 35) & (gray < 245)
        black_ink = gray < 145
        ink_mask = cv2.dilate((blue_ink | black_ink).astype(np.uint8), np.ones((2, 2), dtype=np.uint8), iterations=1).astype(bool)

        background_mask = ~ink_mask
        white_background = background_mask & (gray > 248) & (saturation < 18)
        background_whiteness = float(white_background.sum() / max(1, background_mask.sum()))

        artefact_mask = background_mask & (gray < 248)
        nonwhite_artefact_ratio = float(artefact_mask.sum() / max(1, rgb.shape[0] * rgb.shape[1]))

        faint = background_mask & (gray > 155) & (gray < 245) & (saturation < 70)
        height, width = gray.shape
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(55, width // 12), 1))
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(55, height // 12)))
        horizontal = cv2.morphologyEx(faint.astype(np.uint8), cv2.MORPH_OPEN, horizontal_kernel).astype(bool)
        vertical = cv2.morphologyEx(faint.astype(np.uint8), cv2.MORPH_OPEN, vertical_kernel).astype(bool)

        total_pixels = max(1, rgb.shape[0] * rgb.shape[1])
        return PremiumStyleScores(
            background_whiteness_score=background_whiteness,
            horizontal_line_score=float(horizontal.sum() / total_pixels),
            vertical_line_score=float(vertical.sum() / total_pixels),
            nonwhite_artefact_ratio=nonwhite_artefact_ratio,
            black_ink_ratio=float(black_ink.sum() / total_pixels),
            blue_ink_ratio=float(blue_ink.sum() / total_pixels),
        )
