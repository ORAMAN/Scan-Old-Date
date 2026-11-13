from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


@dataclass
class CandidateRegion:
    image: np.ndarray
    label: str
    score: float


class StampDetector:
    """Generate likely date-stamp crops without assuming a single stamp color."""

    def __init__(self, max_regions: int = 12):
        self.max_regions = max_regions

    def detect(self, path: str | Path) -> list[CandidateRegion]:
        with Image.open(path) as pil:
            rgb = np.asarray(pil.convert("RGB"))
        height, width = rgb.shape[:2]
        if height < 80 or width < 80:
            return []
        regions: list[CandidateRegion] = []
        # Corner crops catch the common consumer-camera stamp locations.
        for label, box in self._corner_boxes(width, height):
            x1, y1, x2, y2 = box
            regions.append(CandidateRegion(rgb[y1:y2, x1:x2], label, 0.48))

        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        # Broad chromatic mask: red, orange, yellow, green, cyan, blue and magenta.
        masks = [
            cv2.inRange(hsv, np.array([0, 70, 100]), np.array([35, 255, 255])),
            cv2.inRange(hsv, np.array([36, 55, 90]), np.array([179, 255, 255])),
        ]
        mask = cv2.bitwise_or(masks[0], masks[1])
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for index in range(1, count):
            x, y, w, h, area = stats[index]
            if area < 8 or w < 3 or h < 3 or w > width * 0.5 or h > height * 0.25:
                continue
            pad_x, pad_y = max(18, w), max(12, h)
            x1, y1 = max(0, x - pad_x), max(0, y - pad_y)
            x2, y2 = min(width, x + w + pad_x), min(height, y + h + pad_y)
            regions.append(CandidateRegion(rgb[y1:y2, x1:x2], "color-component", 0.62))

        # Deduplicate identical/near-identical crops by label and dimensions.
        unique: list[CandidateRegion] = []
        seen: set[tuple[str, int, int]] = set()
        for region in regions:
            key = (region.label, region.image.shape[1] // 20, region.image.shape[0] // 20)
            if key not in seen and region.image.size:
                unique.append(region)
                seen.add(key)
        return unique[: self.max_regions]

    @staticmethod
    def _corner_boxes(width: int, height: int):
        # Crop generous edge bands; OCR can locate the text within the crop.
        x_band, y_band = int(width * 0.48), int(height * 0.30)
        return [
            ("top-left", (0, 0, x_band, y_band)),
            ("top-right", (width - x_band, 0, width, y_band)),
            ("bottom-left", (0, height - y_band, x_band, height)),
            ("bottom-right", (width - x_band, height - y_band, width, height)),
        ]
