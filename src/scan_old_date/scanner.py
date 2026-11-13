from __future__ import annotations

from pathlib import Path
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
                existing = read_exif_date(
                    path, self.config["metadata"].get("exiftool_path", "exiftool")
                )
                if existing and self.config["scan"].get("skip_existing_exif_date", True):
                    result = RecognitionResult(str(path), [], [existing], ["exif"], [])
                    status, confidence = "existing-exif", None
                    db.add_result(str(path), existing, confidence, existing, "exif", status)
                else:
                    result = self.recognizer.recognize(path)
                    selected = result.candidates[0] if result.candidates else None
                    confidence = selected.confidence if selected else None
                    status = "review" if selected else "not-found"
                    db.add_result(
                        str(path),
                        selected.value.isoformat() if selected else None,
                        confidence,
                        " | ".join(result.raw_text),
                        ",".join(result.methods),
                        status,
                        "; ".join(result.errors),
                    )
                results.append(result)
                if on_result:
                    on_result(result, status, confidence)
        finally:
            db.close()
        return results
