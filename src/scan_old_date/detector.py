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
    """Find likely date-stamp areas, including vertically printed edge stamps."""

    def __init__(self, max_regions: int = 16):
        self.max_regions = max(8, int(max_regions))

    def detect(self, path: str | Path) -> list[CandidateRegion]:
        with Image.open(path) as pil:
            # Work in the same orientation in which the photograph is displayed.
            rgb = np.asarray(ImageOps.exif_transpose(pil).convert("RGB"))

        height, width = rgb.shape[:2]
        if height < 80 or width < 80:
            return []

        regions: list[CandidateRegion] = []
        for label, box, score in self._base_boxes(width, height):
            region = self._make_region(rgb, label, box, score)
            if region is not None:
                regions.append(region)

        # Yellow/orange camera stamps are common. Join neighbouring glyphs in both
        # directions so horizontal and vertical date lines can become one proposal.
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        yellow_raw = cv2.inRange(
            hsv,
            np.array([10, 55, 115], dtype=np.uint8),
            np.array([52, 255, 255], dtype=np.uint8),
        )
        yellow_orange = cv2.morphologyEx(
            yellow_raw, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)
        )

        horizontal_width = max(11, min(41, width // 65))
        vertical_height = max(11, min(41, height // 65))
        kernels = (
            np.ones((3, horizontal_width), dtype=np.uint8),
            np.ones((vertical_height, 3), dtype=np.uint8),
        )

        colour_proposals: list[CandidateRegion] = []

        # Vertical camera stamps are often made of disconnected glyphs. Rather
        # than merge every yellow object in the scene, cluster small components
        # that share nearly the same X coordinate along an image edge.
        component_count, _, component_stats, component_centres = (
            cv2.connectedComponentsWithStats(yellow_raw, 8)
        )
        glyphs: list[tuple[int, int, int, int, float]] = []
        max_glyph_width = max(14, int(width * 0.055))
        max_glyph_height = max(26, int(height * 0.065))
        for component_index in range(1, component_count):
            gx, gy, gw, gh, area = component_stats[component_index]
            centre_x = float(component_centres[component_index][0])
            near_side = gx < width * 0.20 or gx + gw > width * 0.80
            if (
                near_side
                and gy > height * 0.60
                and 3 <= gw <= max_glyph_width
                and 3 <= gh <= max_glyph_height
                and area >= 6
            ):
                glyphs.append((gx, gy, gw, gh, centre_x))

        glyph_groups: list[list[tuple[int, int, int, int, float]]] = []
        for glyph in sorted(glyphs, key=lambda item: item[4]):
            target = next(
                (
                    group
                    for group in glyph_groups
                    if abs(
                        glyph[4]
                        - sum(item[4] for item in group) / len(group)
                    )
                    <= max(7.0, width * 0.022)
                ),
                None,
            )
            if target is None:
                glyph_groups.append([glyph])
            else:
                target.append(glyph)

        for group in glyph_groups:
            y_min = min(item[1] for item in group)
            y_max = max(item[1] + item[3] for item in group)
            if len(group) < 5 or y_max - y_min < height * 0.12:
                continue
            x_min = min(item[0] for item in group)
            x_max = max(item[0] + item[2] for item in group)
            box = (
                max(0, x_min - 4),
                max(0, y_min - 20),
                min(width, x_max + 11),
                min(height, y_max + 20),
            )
            region = self._make_region(
                rgb, "yellow-stamp-vertical-components", box, 0.90
            )
            if region is not None:
                colour_proposals.append(region)

        for kernel in kernels:
            joined = cv2.morphologyEx(yellow_orange, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(
                joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for contour in contours:
                x, y, box_width, box_height = cv2.boundingRect(contour)
                area = box_width * box_height
                if area < 120:
                    continue
                if box_width > width * 0.68 or box_height > height * 0.38:
                    continue
                if box_width < max(10, width * 0.012) and box_height < max(10, height * 0.012):
                    continue

                # Date stamps are usually printed near an edge. This also rejects
                # many yellow objects and patterns in the centre of the photograph.
                near_edge = (
                    y < height * 0.18
                    or y + box_height > height * 0.72
                    or x < width * 0.20
                    or x + box_width > width * 0.80
                )
                if not near_edge:
                    continue

                aspect = box_width / max(1, box_height)
                if 0.55 < aspect < 2.0:
                    continue

                near_side = (
                    x < width * 0.20 or x + box_width > width * 0.80
                )
                near_top_or_bottom = (
                    y < height * 0.18
                    or y + box_height > height * 0.72
                )
                if not near_side or not near_top_or_bottom:
                    continue
                if aspect >= 2.0 and box_width < width * 0.10:
                    continue

                if aspect < 0.55:
                    # Vertical stamp: keep the narrow glyph column tight. A large
                    # side margin floods OCR with unrelated tablecloth/food pixels.
                    pad_x = max(4, int(box_width * 0.12))
                    pad_y = max(10, int(box_height * 0.10))
                    label = "yellow-stamp-vertical"
                else:
                    pad_x = max(12, int(box_width * 0.10))
                    pad_y = max(8, int(box_height * 0.28))
                    label = "yellow-stamp-horizontal"
                box = (
                    max(0, x - pad_x),
                    max(0, y - pad_y),
                    min(width, x + box_width + pad_x),
                    min(height, y + box_height + pad_y),
                )
                if label == "yellow-stamp-horizontal":
                    proposal_score = (
                        0.95 if y + box_height > height * 0.72 else 0.74
                    )
                else:
                    proposal_score = 0.84
                region = self._make_region(rgb, label, box, proposal_score)
                if region is not None:
                    colour_proposals.append(region)

        # Keep tight colour proposals first, but retain all fixed edge/corner
        # proposals so a busy carpet or clothing pattern cannot crowd them out.
        colour_proposals.sort(
            key=lambda item: self._proposal_quality(item, width, height),
            reverse=True,
        )
        unique_colours: list[CandidateRegion] = []
        for proposal in colour_proposals:
            if any(self._overlap_ratio(proposal.bbox, item.bbox) > 0.55
                   for item in unique_colours):
                continue
            unique_colours.append(proposal)

        # Tight colour proposals are more useful than broad corner crops.
        # Put a small, ranked set first so a clear date can be found without
        # spending OCR time on every large image zone.
        selected_colours = unique_colours[: min(4, max(0, self.max_regions - 1))]
        base_limit = max(0, self.max_regions - len(selected_colours))
        return selected_colours + regions[:base_limit]

    @staticmethod
    def _base_boxes(width: int, height: int):
        """High-priority search areas; bottom corners and side strips come first."""
        return [
            (
                "bottom-right",
                (int(width * 0.42), int(height * 0.58), width, height),
                0.66,
            ),
            (
                "bottom-left",
                (0, int(height * 0.58), int(width * 0.58), height),
                0.66,
            ),
            ("left-edge", (0, 0, int(width * 0.22), height), 0.60),
            ("right-edge", (int(width * 0.78), 0, width, height), 0.60),
            ("top-left", (0, 0, int(width * 0.52), int(height * 0.34)), 0.54),
            (
                "top-right",
                (int(width * 0.48), 0, width, int(height * 0.34)),
                0.54,
            ),
            ("bottom-edge", (0, int(height * 0.78), width, height), 0.52),
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

    @staticmethod
    def _overlap_ratio(
        first: tuple[int, int, int, int] | None,
        second: tuple[int, int, int, int] | None,
    ) -> float:
        if first is None or second is None:
            return 0.0
        ax1, ay1, ax2, ay2 = first
        bx1, by1, bx2, by2 = second
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        area = min((ax2 - ax1) * (ay2 - ay1), (bx2 - bx1) * (by2 - by1))
        return intersection / area if area else 0.0

    @staticmethod
    def _proposal_quality(
        region: CandidateRegion, width: int, height: int
    ) -> float:
        if region.bbox is None:
            return 0.0
        x1, y1, x2, y2 = region.bbox
        crop_area = max(1, (x2 - x1) * (y2 - y1))
        image_area = max(1, width * height)
        # Prefer compact crops without making the detector depend on resolution.
        return region.score + 0.15 * (1.0 - crop_area / image_area)
