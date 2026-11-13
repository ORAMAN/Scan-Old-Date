from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pytesseract
import requests
from PIL import Image

from .date_parser import ParsedDate, parse_date_candidates
from .detector import CandidateRegion, StampDetector


@dataclass
class RecognitionResult:
    path: str
    candidates: list[ParsedDate]
    raw_text: list[str]
    methods: list[str]
    errors: list[str]


class HybridRecognizer:
    def __init__(self, config: dict):
        self.config = config
        self.detector = StampDetector(
            int(config["recognition"].get("max_candidate_regions", 12))
        )
        command = config["tesseract"].get("command", "").strip()
        if command:
            pytesseract.pytesseract.tesseract_cmd = command

    def recognize(self, path: str | Path) -> RecognitionResult:
        raw_text: list[str] = []
        methods: list[str] = []
        errors: list[str] = []
        candidates: list[ParsedDate] = []
        try:
            regions = self.detector.detect(path)
        except Exception as exc:
            return RecognitionResult(str(path), [], [], [], [f"Detector: {exc}"])

        for region in regions:
            try:
                text = self._tesseract(region)
                if text.strip():
                    raw_text.append(text.strip())
                    methods.append("tesseract")
                    candidates.extend(
                        parse_date_candidates(
                            text,
                            int(self.config["scan"]["min_year"]),
                            int(self.config["scan"]["max_year"]),
                        )
                    )
            except Exception as exc:
                errors.append(f"Tesseract: {exc}")

        yolo_cfg = self.config.get("yolo", {})
        if yolo_cfg.get("enabled"):
            try:
                yolo_regions = self._yolo_regions(path, yolo_cfg)
                for region in yolo_regions:
                    text = self._tesseract(region)
                    if text.strip():
                        raw_text.append(text.strip())
                        methods.append("yolo+tesseract")
                        candidates.extend(
                            parse_date_candidates(
                                text,
                                int(self.config["scan"]["min_year"]),
                                int(self.config["scan"]["max_year"]),
                            )
                        )
            except Exception as exc:
                errors.append(f"YOLO: {exc}")

        ollama_cfg = self.config.get("ollama", {})
        if ollama_cfg.get("enabled") and (
            not candidates or max(c.confidence for c in candidates) < 0.82
        ):
            try:
                text = self._ollama_read(path, ollama_cfg)
                if text:
                    raw_text.append(text)
                    methods.append("ollama-vision")
                    candidates.extend(
                        parse_date_candidates(
                            text,
                            int(self.config["scan"]["min_year"]),
                            int(self.config["scan"]["max_year"]),
                        )
                    )
            except Exception as exc:
                errors.append(f"Ollama: {exc}")

        # Prefer candidates supported by more than one OCR region/method.
        counts: dict[object, int] = {}
        for item in candidates:
            counts[item.value] = counts.get(item.value, 0) + 1
        ranked = sorted(
            candidates,
            key=lambda item: (item.confidence + min(0.12, (counts[item.value] - 1) * 0.06)),
            reverse=True,
        )
        return RecognitionResult(str(path), ranked, raw_text, sorted(set(methods)), errors)

    @staticmethod
    def _tesseract(region: CandidateRegion) -> str:
        rgb = region.image
        scale = max(2, min(5, 1200 // max(1, rgb.shape[1])))
        enlarged = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_RGB2GRAY)
        variants = [
            cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
            cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1],
            gray,
        ]
        texts = []
        for image in variants:
            config = (
                f"--oem 3 --psm {int(11)} "
                "-c tessedit_char_whitelist=0123456789./:-_' "
            )
            texts.append(
                pytesseract.image_to_string(
                    Image.fromarray(image),
                    lang="eng",
                    config=config,
                )
            )
        return "\n".join(texts)

    def _yolo_regions(self, path: str | Path, cfg: dict) -> list[CandidateRegion]:
        from ultralytics import YOLO

        weights = Path(cfg["weights"])
        if not weights.exists():
            raise FileNotFoundError(f"YOLO weights not found: {weights}")
        model = YOLO(str(weights))
        result = model(str(path), conf=float(cfg.get("confidence", 0.25)), verbose=False)[0]
        image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
        regions = []
        if result.boxes is not None:
            for box in result.boxes.xyxy.cpu().numpy():
                x1, y1, x2, y2 = map(int, box)
                regions.append(CandidateRegion(image[y1:y2, x1:x2], "yolo", 0.85))
        return regions

    @staticmethod
    def _ollama_read(path: str | Path, cfg: dict) -> str:
        import base64

        image_bytes = Path(path).read_bytes()
        encoded = base64.b64encode(image_bytes).decode("ascii")
        response = requests.post(
            cfg["base_url"].rstrip("/") + "/api/generate",
            json={
                "model": cfg["model"],
                "prompt": (
                    "Inspect this old photograph for a camera-printed date stamp. "
                    "Return only the date text exactly as visible. If no date stamp is visible, "
                    "return NONE. Do not infer a date from the scene."
                ),
                "images": [encoded],
                "stream": False,
            },
            timeout=int(cfg.get("timeout_seconds", 45)),
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
