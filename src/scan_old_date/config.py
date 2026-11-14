from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "scan": {
        "recursive": True,
        "extensions": [".jpg", ".jpeg", ".tif", ".tiff", ".png", ".webp", ".bmp"],
        "skip_existing_exif_date": True,
        "min_year": 1950,
        "max_year": 2035,
        "default_time": "12:00:00",
    },
    "recognition": {
        "auto_accept_threshold": 0.90,
        "review_threshold": 0.55,
        "max_candidate_regions": 12,
        "use_color_candidates": True,
        "use_corner_candidates": True,
    },
    "tesseract": {"command": "", "languages": "eng", "page_segmentation_mode": 11},
    "yolo": {"enabled": False, "weights": "models/date-stamp-detector.pt", "confidence": 0.25},
    "ollama": {
        "enabled": True,
        "base_url": "http://127.0.0.1:11434",
        "model": "gemma4:12b",
        "timeout_seconds": 45,
    },
    "metadata": {
        "write_exif": True,
        "set_file_times": True,
        "backup_before_write": True,
        "backup_directory": ".scan-old-date-backups",
        "overwrite_existing": False,
        "exiftool_path": "exiftool",
    },
    "database": {"path": "data/scan_old_date.sqlite3"},
}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    config_path = Path(path) if path else Path("config/settings.yaml")
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as stream:
            loaded = yaml.safe_load(stream) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Invalid configuration format in {config_path}: expected a YAML mapping.")
        _merge(config, loaded)
    return config


def save_config(config: dict[str, Any], path: str | Path | None = None) -> Path:
    """Persist the complete application configuration as UTF-8 YAML."""
    config_path = Path(path) if path else Path("config/settings.yaml")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8", newline="\n") as stream:
        yaml.safe_dump(
            config,
            stream,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    return config_path


def _merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value
