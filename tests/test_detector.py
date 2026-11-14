import cv2
import numpy as np
from PIL import Image

from scan_old_date.detector import StampDetector


def _save_rgb(path, image):
    Image.fromarray(image).save(path, quality=95)


def test_detector_creates_tight_region_for_vertical_yellow_stamp(tmp_path):
    image = np.full((480, 360, 3), 30, dtype=np.uint8)
    stamp_line = np.zeros((36, 190, 3), dtype=np.uint8)
    cv2.putText(
        stamp_line,
        "2009/06/13",
        (2, 27),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (255, 255, 0),
        1,
        cv2.LINE_AA,
    )
    stamp = cv2.rotate(stamp_line, cv2.ROTATE_90_COUNTERCLOCKWISE)
    stamp_height, stamp_width = stamp.shape[:2]
    image[285 : 285 + stamp_height, 18 : 18 + stamp_width] = stamp

    path = tmp_path / "vertical-stamp.jpg"
    _save_rgb(path, image)

    regions = StampDetector(max_regions=16).detect(path)

    assert len(regions) == 1
    assert regions[0].label == "yellow-stamp-vertical-components"
    assert regions[0].bbox is not None
    x1, y1, x2, y2 = regions[0].bbox
    assert x1 < 30
    assert x2 - x1 < 55
    assert y1 > 250
    assert y2 > 460
    assert regions[0].image.shape[1] == x2 - x1
    assert regions[0].image.shape[0] == y2 - y1


def test_detector_creates_tight_region_for_horizontal_yellow_stamp(tmp_path):
    image = np.zeros((400, 600, 3), dtype=np.uint8)
    cv2.putText(
        image,
        "2009/08/07",
        (380, 380),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 0),
        2,
        cv2.LINE_AA,
    )
    path = tmp_path / "horizontal-stamp.jpg"
    _save_rgb(path, image)

    regions = StampDetector(max_regions=16).detect(path)

    assert len(regions) == 1
    assert regions[0].label == "yellow-stamp-horizontal-components"
    assert regions[0].bbox is not None
    x1, y1, x2, y2 = regions[0].bbox
    assert x2 > 480
    assert y1 > 300
    assert x2 - x1 < 200


def test_detector_falls_back_to_edge_regions_when_stamp_colour_is_absent(tmp_path):
    image = np.full((400, 600, 3), 100, dtype=np.uint8)
    path = tmp_path / "no-yellow-stamp.jpg"
    _save_rgb(path, image)

    regions = StampDetector(max_regions=16).detect(path)
    labels = [region.label for region in regions]

    assert labels == ["bottom-right", "bottom-left", "right-edge", "left-edge"]
    for region in regions:
        assert region.bbox is not None


def test_detector_ignores_broad_yellow_noise_and_keeps_bounded_regions(tmp_path):
    image = np.full((400, 600, 3), 150, dtype=np.uint8)
    rng = np.random.default_rng(42)
    # Add a yellow/brown decorative patch without a long row or column of glyphs.
    patch = rng.integers(100, 255, size=(150, 150, 3), dtype=np.uint8)
    image[100:250, 420:570] = patch
    path = tmp_path / "yellow-noise.jpg"
    _save_rgb(path, image)

    regions = StampDetector(max_regions=16).detect(path)
    assert len(regions) <= 4
    assert all(region.image.size for region in regions)


def test_detector_marks_short_stamp_cut_off_at_right_edge_as_partial(tmp_path):
    image = np.zeros((480, 457, 3), dtype=np.uint8)
    cv2.putText(
        image,
        "2009/09/13",
        (370, 455),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        (255, 255, 0),
        1,
        cv2.LINE_AA,
    )
    path = tmp_path / "partial-right-edge-stamp.jpg"
    _save_rgb(path, image)

    regions = StampDetector(max_regions=16).detect(path)

    assert len(regions) == 1
    assert regions[0].label == "yellow-stamp-horizontal-partial"
    assert regions[0].bbox is not None
    x1, y1, x2, y2 = regions[0].bbox
    assert x1 > 350
    assert x2 == 457
    assert y1 < 455 < y2
