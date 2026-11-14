from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pytesseract
import requests
from PIL import Image

from .date_parser import ParsedDate, parse_date_candidates
from .detector import CandidateRegion, StampDetector
from .external_tools import resolve_tesseract


@dataclass
class RecognitionResult:
    path: str
    candidates: list[ParsedDate]
    raw_text: list[str]
    methods: list[str]
    errors: list[str]
    # Existing metadata is shown only as a reference; it is not a recognition candidate.
    existing_exif_date: str | None = None
    # Lightweight diagnostics for the GUI: rectangles, OCR variants and parsed dates.
    region_diagnostics: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class _OCRRead:
    text: str
    confidence: float
    rotation: int
    variant: str
    psm: int


class HybridRecognizer:
    def __init__(self, config: dict):
        self.config = config
        self.detector = StampDetector(
            int(config["recognition"].get("max_candidate_regions", 16))
        )
        self.yolo_model = None
        self.ollama_available: bool | None = None
        command = config["tesseract"].get("command", "")
        self.tesseract_executable = resolve_tesseract(command)
        if self.tesseract_executable:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_executable

    def recognize(self, path: str | Path) -> RecognitionResult:
        raw_text: list[str] = []
        methods: list[str] = []
        errors: list[str] = []
        candidates: list[ParsedDate] = []
        diagnostics: list[dict] = []
        try:
            regions = self.detector.detect(path)
        except Exception as exc:
            return RecognitionResult(str(path), [], [], [], [f"Detector: {exc}"])

        colour_region_count = sum(
            1 for region in regions if region.label.startswith("yellow-stamp")
        )
        colour_candidate_found = False
        for region_index, region in enumerate(regions):
            region_candidates: list[ParsedDate] = []
            try:
                reads = self._tesseract(region)
                if any(read.text for read in reads):
                    methods.append("tesseract")
                for read in reads:
                    parsed = self._parse(read.text)
                    if not parsed:
                        continue
                    for item in parsed:
                        # The parser validates the calendar date. OCR confidence is
                        # combined additively rather than multiplied, which previously
                        # crushed otherwise correct results from outlined/yellow text.
                        score = min(
                            0.99,
                            item.confidence * 0.68
                            + read.confidence * 0.24
                            + region.score * 0.08,
                        )
                        scored = ParsedDate(
                            item.value,
                            score,
                            item.source_text,
                            item.ambiguous,
                        )
                        candidates.append(scored)
                        region_candidates.append(scored)

                best_read = max(
                    reads,
                    key=lambda item: (
                        bool(self._parse(item.text)),
                        item.confidence,
                    ),
                    default=None,
                )
                if best_read and best_read.text:
                    if best_read.text not in raw_text:
                        raw_text.append(best_read.text)

                diagnostics.append(
                    {
                        "bbox": list(region.bbox) if region.bbox else None,
                        "label": region.label,
                        "detector_score": round(float(region.score), 3),
                        "ocr_text": best_read.text if best_read else "",
                        "ocr_confidence": (
                            round(float(best_read.confidence), 3) if best_read else 0.0
                        ),
                        "rotation": best_read.rotation if best_read else 0,
                        "variant": best_read.variant if best_read else "",
                        "reads": [
                            {
                                "text": item.text,
                                "confidence": round(float(item.confidence), 3),
                                "rotation": item.rotation,
                                "variant": item.variant,
                                "psm": item.psm,
                            }
                            for item in sorted(
                                reads,
                                key=lambda value: (
                                    bool(self._parse(value.text)),
                                    value.confidence,
                                ),
                                reverse=True,
                            )[:3]
                        ],
                        "dates": [
                            {
                                "value": item.value.isoformat(),
                                "confidence": round(float(item.confidence), 3),
                                "ambiguous": bool(item.ambiguous),
                                "source_text": item.source_text,
                            }
                            for item in sorted(
                                region_candidates,
                                key=lambda value: value.confidence,
                                reverse=True,
                            )[:4]
                        ],
                    }
                )
            except Exception as exc:
                errors.append(f"Tesseract ({region.label}): {exc}")
                diagnostics.append(
                    {
                        "bbox": list(region.bbox) if region.bbox else None,
                        "label": region.label,
                        "detector_score": round(float(region.score), 3),
                        "ocr_text": "",
                        "ocr_confidence": 0.0,
                        "rotation": 0,
                        "variant": "",
                        "reads": [],
                        "dates": [],
                        "error": str(exc),
                    }
                )

            if region.label.startswith("yellow-stamp") and region_candidates:
                colour_candidate_found = True

            # A localized colour proposal already found a complete calendar date.
            # Do not OCR the broad corner/edge crops again; retain their boxes in
            # diagnostics so the user can still see which zones were not needed.
            if (
                colour_region_count
                and region_index + 1 == colour_region_count
                and colour_candidate_found
            ):
                for skipped in regions[region_index + 1 :]:
                    diagnostics.append(
                        {
                            "bbox": list(skipped.bbox) if skipped.bbox else None,
                            "label": skipped.label,
                            "detector_score": round(float(skipped.score), 3),
                            "ocr_text": "",
                            "ocr_confidence": 0.0,
                            "rotation": 0,
                            "variant": "not-run",
                            "reads": [],
                            "dates": [],
                            "skipped": True,
                        }
                    )
                break

        yolo_cfg = self.config.get("yolo", {})
        if yolo_cfg.get("enabled"):
            try:
                for region in self._yolo_regions(path, yolo_cfg):
                    for read in self._tesseract(region):
                        parsed = self._parse(read.text)
                        if not parsed:
                            continue
                        methods.append("yolo+tesseract")
                        candidates.extend(self._score_candidates(parsed, read.confidence))
            except Exception as exc:
                errors.append(f"YOLO: {exc}")

        # A repeated OCR read of the same date is one result, not several alternatives.
        best_by_date: dict[object, ParsedDate] = {}
        for item in candidates:
            current = best_by_date.get(item.value)
            if current is None or item.confidence > current.confidence:
                best_by_date[item.value] = item

        ollama_cfg = self.config.get("ollama", {})
        ranked_before_vision = sorted(
            best_by_date.values(),
            key=lambda item: (item.confidence, not item.ambiguous),
            reverse=True,
        )
        if ollama_cfg.get("enabled") and (
            not ranked_before_vision
            or max(item.confidence for item in ranked_before_vision) < 0.82
        ):
            try:
                if self._check_ollama(ollama_cfg):
                    text = self._ollama_read(path, ollama_cfg)
                    if text and text.upper() != "NONE":
                        raw_text.append(text)
                        methods.append("ollama-vision")
                        for item in self._parse(text):
                            vision_candidate = ParsedDate(
                                item.value,
                                min(0.78, item.confidence),
                                item.source_text,
                                item.ambiguous,
                            )
                            current = best_by_date.get(item.value)
                            if current is None or vision_candidate.confidence > current.confidence:
                                best_by_date[item.value] = vision_candidate
                else:
                    errors.append(
                        "Ollama or the configured vision model is unavailable."
                    )
            except Exception as exc:
                errors.append(f"Ollama: {exc}")

        ranked = sorted(
            best_by_date.values(),
            key=lambda item: (item.confidence, not item.ambiguous),
            reverse=True,
        )
        return RecognitionResult(
            str(path),
            ranked,
            raw_text,
            sorted(set(methods)),
            errors,
            region_diagnostics=diagnostics,
        )

    def _parse(self, text: str) -> list[ParsedDate]:
        return parse_date_candidates(
            text,
            int(self.config["scan"]["min_year"]),
            int(self.config["scan"]["max_year"]),
        )

    @staticmethod
    def _score_candidates(
        candidates: list[ParsedDate], ocr_confidence: float
    ) -> list[ParsedDate]:
        return [
            ParsedDate(
                item.value,
                min(0.99, item.confidence * 0.68 + ocr_confidence * 0.24 + 0.08 * 0.60),
                item.source_text,
                item.ambiguous,
            )
            for item in candidates
        ]

    def _tesseract(self, region: CandidateRegion) -> list[_OCRRead]:
        if not self.tesseract_executable:
            configured = str(self.config["tesseract"].get("command", "")).strip()
            hint = f" Указанный путь: {configured}" if configured else ""
            raise FileNotFoundError(
                "Tesseract OCR не найден. Укажите путь к tesseract.exe или папку "
                f"его установки в настройках.{hint}"
            )

        source = region.image
        source_height, source_width = source.shape[:2]
        max_dimension = max(source_height, source_width)
        # Keep glyphs large enough for Tesseract without turning a small crop into
        # a huge mostly-background image.
        scale = max(2, min(4, 1600 // max(1, max_dimension)))

        if region.label == "yellow-stamp-vertical-components":
            rotations = (270, 0)
        elif region.label.startswith("yellow-stamp-horizontal"):
            rotations = (0,)
        elif region.label in {"left-edge", "right-edge"}:
            rotations = (270, 0)
        else:
            rotations = (0,)

        cfg = self.config["tesseract"]
        lang = cfg.get("languages", "eng")
        configured_psm = int(cfg.get("page_segmentation_mode", 6))
        psm_values = list(dict.fromkeys((6, 7, configured_psm)))
        reads: list[_OCRRead] = []

        for angle in rotations:
            if angle == 90:
                oriented = cv2.rotate(source, cv2.ROTATE_90_CLOCKWISE)
            elif angle == 270:
                oriented = cv2.rotate(source, cv2.ROTATE_90_COUNTERCLOCKWISE)
            else:
                oriented = source

            enlarged = cv2.resize(
                oriented,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_CUBIC,
            )
            gray = cv2.cvtColor(enlarged, cv2.COLOR_RGB2GRAY)
            otsu = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )[1]

            hsv = cv2.cvtColor(enlarged, cv2.COLOR_RGB2HSV)
            # Match the same bright-yellow range used by the detector. This
            # isolates the glyph fill from dark outlines and nearby photo details.
            yellow_mask = cv2.inRange(
                hsv,
                np.array([15, 70, 170], dtype=np.uint8),
                np.array([42, 255, 255], dtype=np.uint8),
            )
            yellow_mask = cv2.morphologyEx(
                yellow_mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8)
            )

            variants: list[tuple[str, np.ndarray]] = [
                ("gray", gray),
                ("otsu", otsu),
                ("yellow-mask", yellow_mask),
            ]

            orientation_found_date = False
            for variant_name, image in variants:
                for psm in psm_values:
                    tesseract_config = (
                        f"--oem 3 --psm {psm} "
                        "-c tessedit_char_whitelist="
                        "0123456789:/.-AMPamp"
                    )
                    data = pytesseract.image_to_data(
                        Image.fromarray(image),
                        lang=lang,
                        config=tesseract_config,
                        output_type=pytesseract.Output.DICT,
                        timeout=12,
                    )
                    date_words: list[str] = []
                    date_scores: list[float] = []
                    for word, raw_confidence in zip(
                        data.get("text", []), data.get("conf", [])
                    ):
                        word = word.strip()
                        if not word:
                            continue
                        if not (
                            any(character.isdigit() for character in word)
                            or word.upper() in {"AM", "PM"}
                        ):
                            continue
                        try:
                            score = float(raw_confidence)
                        except (TypeError, ValueError):
                            score = -1.0
                        date_words.append(word)
                        if score >= 0:
                            date_scores.append(score)

                    text = " ".join(date_words)
                    if not text:
                        continue
                    confidence = (
                        sum(date_scores) / len(date_scores) / 100.0
                        if date_scores
                        else 0.30
                    )
                    # Tesseract often reports zero confidence for a complete
                    # single-word outlined camera stamp. A valid calendar date
                    # is stronger evidence than that unusable zero score.
                    if self._parse(text) and confidence < 0.05:
                        confidence = 0.55
                    reads.append(
                        _OCRRead(
                            text,
                            max(0.0, min(1.0, confidence)),
                            angle,
                            variant_name,
                            psm,
                        )
                    )

                    # A calendar-valid date is stronger evidence than OCR's raw
                    # confidence. Stop at the first valid full read for this crop.
                    if self._parse(text):
                        orientation_found_date = True
                        break
                if orientation_found_date:
                    break
            if orientation_found_date:
                break

        unique: dict[tuple[str, int], _OCRRead] = {}
        for read in reads:
            key = (read.text, read.rotation)
            current = unique.get(key)
            if current is None or read.confidence > current.confidence:
                unique[key] = read
        return sorted(
            unique.values(),
            key=lambda item: (
                bool(self._parse(item.text)),
                item.confidence,
            ),
            reverse=True,
        )[:8]

    def _yolo_regions(self, path: str | Path, cfg: dict) -> list[CandidateRegion]:
        from ultralytics import YOLO

        weights = Path(cfg["weights"])
        if not weights.exists():
            raise FileNotFoundError(f"YOLO weights not found: {weights}")
        if self.yolo_model is None:
            self.yolo_model = YOLO(str(weights))
        result = self.yolo_model(
            str(path), conf=float(cfg.get("confidence", 0.25)), verbose=False
        )[0]
        image_bgr = cv2.imread(str(path))
        if image_bgr is None:
            raise ValueError(f"Could not decode image: {path}")
        image = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        regions = []
        if result.boxes is not None:
            for box in result.boxes.xyxy.cpu().numpy():
                x1, y1, x2, y2 = map(int, box)
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(image.shape[1], x2), min(image.shape[0], y2)
                if x2 > x1 and y2 > y1:
                    regions.append(
                        CandidateRegion(
                            image[y1:y2, x1:x2],
                            "yolo",
                            0.85,
                            (x1, y1, x2, y2),
                        )
                    )
        return regions

    def _check_ollama(self, cfg: dict) -> bool:
        if self.ollama_available is not None:
            return self.ollama_available
        try:
            response = requests.get(
                cfg["base_url"].rstrip("/") + "/api/tags",
                timeout=2,
            )
            response.raise_for_status()
            model_names = {
                item.get("name") or item.get("model")
                for item in response.json().get("models", [])
            }
            configured_model = cfg["model"]
            self.ollama_available = (
                configured_model in model_names
                or configured_model.split(":")[0] in model_names
            )
        except requests.RequestException:
            self.ollama_available = False
        return self.ollama_available

    @staticmethod
    def _ollama_read(path: str | Path, cfg: dict) -> str:
        encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        response = requests.post(
            cfg["base_url"].rstrip("/") + "/api/generate",
            json={
                "model": cfg["model"],
                "prompt": (
                    "Inspect this old photograph for a camera-printed date stamp. "
                    "Read only the visible stamp, not the scene or existing metadata. "
                    "Return the date in YYYY-MM-DD format. If the visible date is incomplete "
                    "or no stamp is present, return NONE. Do not guess missing digits."
                ),
                "images": [encoded],
                "stream": False,
            },
            timeout=int(cfg.get("timeout_seconds", 45)),
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
