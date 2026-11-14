from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps


@dataclass
class CandidateRegion:
    image: np.ndarray
    label: str
    score: float
    # Coordinates are in the EXIF-corrected image coordinate system: x1, y1, x2, y2.
    bbox: tuple[int, int, int, int] | None = None


class StampDetector:
    """Locate compact groups of bright yellow camera-stamp glyphs."""

    def __init__(self, max_regions: int = 12):
        self.max_regions = max(4, int(max_regions))

    def detect(self, path: str | Path) -> list[CandidateRegion]:
        with Image.open(path) as pil:
            rgb = np.asarray(ImageOps.exif_transpose(pil).convert("RGB"))

        height, width = rgb.shape[:2]
        if height < 80 or width < 80:
            return []

        # Camera date stamps in this sample set are bright yellow with a dark outline.
        # A much tighter HSV range avoids the yellow/brown patterns, shop signs and food
        # that flooded the old detector's broad [H=10..52, S=55, V=115] mask.
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        stamp_mask = cv2.inRange(
            hsv,
            np.array([15, 70, 170], dtype=np.uint8),
            np.array([42, 255, 255], dtype=np.uint8),
        )

        components = self._glyph_components(stamp_mask, width, height)
        vertical = self._vertical_groups(components, rgb, width, height)
        if vertical:
            # A vertical stamp is a strong structural signal. Do not also generate
            # horizontal candidates from tableware, clothing and watermarks below it.
            return vertical[: self.max_regions]

        horizontal = self._horizontal_groups(components, rgb, width, height)
        if horizontal:
            return horizontal[: self.max_regions]

        # Colour segmentation can fail for faded, white or red stamps. Only then
        # fall back to a small number of broad edge regions; no large colour blobs.
        regions: list[CandidateRegion] = []
        for label, box, score in self._fallback_boxes(width, height):
            region = self._make_region(rgb, label, box, score)
            if region is not None:
                regions.append(region)
        return regions[: self.max_regions]

    @staticmethod
    def _glyph_components(mask: np.ndarray, width: int, height: int):
        count, _, stats, centres = cv2.connectedComponentsWithStats(mask, 8)
        glyphs = []
        max_glyph_width = max(30, int(width * 0.04))
        max_glyph_height = max(36, int(height * 0.05))

        for index in range(1, count):
            x, y, glyph_width, glyph_height, area = stats[index]
            if (
                area < 8
                or glyph_width < 2
                or glyph_height < 3
                or glyph_width > max_glyph_width
                or glyph_height > max_glyph_height
                or y + glyph_height < height * 0.60
            ):
                continue

            center_x, center_y = centres[index]
            glyphs.append(
                (
                    int(x),
                    int(y),
                    int(glyph_width),
                    int(glyph_height),
                    int(area),
                    float(center_x),
                    float(center_y),
                )
            )
        return glyphs

    @staticmethod
    def _cluster(glyphs, coordinate_index: int, tolerance: float):
        groups = []
        for glyph in sorted(glyphs, key=lambda item: item[coordinate_index]):
            target = next(
                (
                    group
                    for group in groups
                    if abs(
                        glyph[coordinate_index]
                        - sum(item[coordinate_index] for item in group) / len(group)
                    )
                    <= tolerance
                ),
                None,
            )
            if target is None:
                groups.append([glyph])
            else:
                target.append(glyph)
        return groups

    def _vertical_groups(
        self,
        glyphs,
        rgb: np.ndarray,
        width: int,
        height: int,
    ) -> list[CandidateRegion]:
        # Each glyph of a vertical stamp shares an X-axis centre with the next one.
        edge_glyphs = [
            item
            for item in glyphs
            if item[0] < width * 0.16 or item[0] + item[2] > width * 0.84
        ]
        groups = self._cluster(edge_glyphs, 5, max(5.0, width * 0.018))
        proposals: list[CandidateRegion] = []

        for group in groups:
            x1 = min(item[0] for item in group)
            y1 = min(item[1] for item in group)
            x2 = max(item[0] + item[2] for item in group)
            y2 = max(item[1] + item[3] for item in group)
            span_x, span_y = x2 - x1, y2 - y1

            # Require a tall, narrow sequence, not a patterned strip in the background.
            if (
                len(group) < 6
                or span_y < height * 0.12
                or span_y < 4.0 * max(1, span_x)
            ):
                continue

            median_height = float(np.median([item[3] for item in group]))
            pad_left = max(12, int(round(median_height * 2.2)))
            pad_right = max(7, int(round(median_height * 1.2)))
            box = (
                max(0, x1 - pad_left),
                max(0, y1),
                min(width, x2 + pad_right),
                min(height, y2 + 4),
            )
            region = self._make_region(
                rgb, "yellow-stamp-vertical-components", box, 0.96
            )
            if region is not None:
                proposals.append(region)

        proposals.sort(key=lambda item: item.score, reverse=True)
        return proposals

    def _horizontal_groups(
        self,
        glyphs,
        rgb: np.ndarray,
        width: int,
        height: int,
    ) -> list[CandidateRegion]:
        # Horizontal camera stamps are usually printed in the last 18% of the photo.
        bottom_glyphs = [
            item for item in glyphs if item[1] + item[3] > height * 0.82
        ]
        groups = self._cluster(bottom_glyphs, 6, max(4.0, height * 0.012))
        proposals: list[CandidateRegion] = []

        for group in groups:
            x1 = min(item[0] for item in group)
            y1 = min(item[1] for item in group)
            x2 = max(item[0] + item[2] for item in group)
            y2 = max(item[1] + item[3] for item in group)
            span_x, span_y = x2 - x1, y2 - y1

            touches_edge = x1 < width * 0.20 or x2 > width * 0.80
            # Require a line of repeated glyphs. A yellow sign or logo usually
            # has too few components or is not a long, narrow baseline-aligned row.
            if (
                len(group) < 5
                or not touches_edge
                or span_x < width * 0.12
                or span_x < 3.0 * max(1, span_y)
            ):
                continue

            median_height = float(np.median([item[3] for item in group]))
            pad_x = max(7, int(round(median_height * 0.60)))
            pad_y = max(3, int(round(median_height * 0.25)))
            box = (
                max(0, x1 - pad_x),
                max(0, y1 - pad_y),
                min(width, x2 + pad_x),
                min(height, y2 + pad_y),
            )
            region = self._make_region(
                rgb, "yellow-stamp-horizontal-components", box, 0.95
            )
            if region is not None:
                proposals.append(region)

        proposals.sort(
            key=lambda item: (
                item.score,
                item.image.shape[1] / max(1, item.image.shape[0]),
            ),
            reverse=True,
        )
        return proposals

    @staticmethod
    def _fallback_boxes(width: int, height: int):
        return [
            (
                "bottom-right",
                (int(width * 0.48), int(height * 0.76), width, height),
                0.58,
            ),
            (
                "bottom-left",
                (0, int(height * 0.76), int(width * 0.52), height),
                0.58,
            ),
            ("right-edge", (int(width * 0.86), int(height * 0.40), width, height), 0.48),
            ("left-edge", (0, int(height * 0.40), int(width * 0.14), height), 0.48),
        ]

    @staticmethod
    def _make_region(
        rgb: np.ndarray,
        label: str,
        box: tuple[int, int, int, int],
        score: float,
    ) -> CandidateRegion | None:
        x1, y1, x2, y2 = box
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(rgb.shape[1], x2), min(rgb.shape[0], y2)
        if x2 - x1 < 20 or y2 - y1 < 20:
            return None
        return CandidateRegion(rgb[y1:y2, x1:x2], label, score, (x1, y1, x2, y2))
