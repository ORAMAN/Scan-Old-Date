import cv2
import numpy as np
from PIL import Image

from scan_old_date.detector import StampDetector


def test_detector_includes_bottom_corners_and_side_strips(tmp_path):
    image = np.full((480, 360, 3), 30, dtype=np.uint8)
    stamp = np.full((190, 36, 3), 0, dtype=np.uint8)
    cv2.putText(
        stamp,
        "2009/06/13",
        (32, 182),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (0, 255, 255),
        1,
        cv2.LINE_AA,
    )
    stamp = cv2.rotate(stamp, cv2.ROTATE_90_COUNTERCLOCKWISE)
    stamp_height, stamp_width = stamp.shape[:2]
    image[285 : 285 + stamp_height, 18 : 18 + stamp_width] = stamp

    path = tmp_path / "vertical-stamp.jpg"
    Image.fromarray(image).save(path, quality=95)

    regions = StampDetector(max_regions=16).detect(path)
    by_label = {region.label: region for region in regions}

    assert "bottom-left" in by_label
    assert "left-edge" in by_label
    assert by_label["bottom-left"].bbox is not None
    assert by_label["left-edge"].bbox is not None

    for region in regions:
        assert region.bbox is not None
        x1, y1, x2, y2 = region.bbox
        assert region.image.shape[1] == x2 - x1
        assert region.image.shape[0] == y2 - y1


def test_detector_keeps_bottom_right_search_area_even_with_colour_noise(tmp_path):
    image = np.zeros((400, 600, 3), dtype=np.uint8)
    # Lots of bright pattern-like pixels should not displace fixed edge regions.
    rng = np.random.default_rng(42)
    image[:, :, :] = rng.integers(0, 255, size=image.shape, dtype=np.uint8)
    cv2.putText(
        image,
        "2009/08/07",
        (320, 380),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    path = tmp_path / "bottom-right-stamp.jpg"
    Image.fromarray(image).save(path, quality=95)

    labels = [region.label for region in StampDetector(max_regions=16).detect(path)]
    assert labels[0] == "bottom-right"
    assert "bottom-left" in labels
