from __future__ import annotations

from pathlib import Path
import re
from typing import Callable, Iterator

from .database import ScanDatabase
from .metadata import read_exif_date
from .ocr import HybridRecognizer, RecognitionResult


class PhotoScanner:
    def __init__(self, config: dict):
        self.config = config
        self.recognizer = HybridRecognizer(config)

    def iter_images(self, root: str | Path) -> Iterator[Path]:
        root = Path(root)
        extensions = {item.lower() for item in self.config["scan"]["extensions"]}
        excluded_names = {
            self.config["metadata"].get("backup_directory", ".scan-old-date-backups"),
            ".git",
            ".venv",
            "__pycache__",
        }
        iterator = root.rglob("*") if self.config["scan"].get("recursive", True) else root.glob("*")
        for path in iterator:
            if any(part in excluded_names for part in path.parts):
                continue
            if path.is_file() and path.suffix.lower() in extensions:
                yield path

    def scan(
        self,
        root: str | Path,
        on_result: Callable[[RecognitionResult, str, float | None], None] | None = None,
    ) -> list[RecognitionResult]:
        results: list[RecognitionResult] = []
        db = ScanDatabase(self.config["database"]["path"])
        try:
            for path in self.iter_images(root):
                # EXIF is retained for comparison only. It must never short-circuit
                # visual recognition because legacy metadata can be wrong.
                existing_exif = read_exif_date(
                    path, self.config["metadata"].get("exiftool_path", "exiftool")
                )
                result = self.recognizer.recognize(path)
                result.existing_exif_date = existing_exif

                selected = result.candidates[0] if result.candidates else None
                confidence = selected.confidence if selected else None
                partial_pattern = re.compile(
                    r"(?<!\d)(?:19|20)\d{2}[./_-](?:0?[1-9]|1[0-2])(?:[./_-])?",
                    re.IGNORECASE,
                )
                has_partial_stamp = any(
                    partial_pattern.search(text) for text in result.raw_text
                )
                status = (
                    "review"
                    if selected
                    else ("partial" if has_partial_stamp else "not-found")
                )

                details = list(result.errors)
                if existing_exif:
                    details.append(f"Existing EXIF date (reference only): {existing_exif}")

                db.add_result(
                    str(path),
                    selected.value.isoformat() if selected else None,
                    confidence,
                    " | ".join(result.raw_text),
                    ",".join(result.methods),
                    status,
                    "; ".join(details),
                )
                results.append(result)
                if on_result:
                    on_result(result, status, confidence)
        finally:
            db.close()
        return results
