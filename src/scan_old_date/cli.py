from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
from pathlib import Path

from .config import load_config
from .metadata import apply_date
from .scanner import PhotoScanner


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan old photographs for visible date stamps.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config/settings.yaml"))
    parser.add_argument("--apply", action="store_true", help="Apply high-confidence dates.")
    parser.add_argument("--dry-run", action="store_true", help="Only report; do not modify images.")
    args = parser.parse_args()

    if not args.folder.exists() or not args.folder.is_dir():
        parser.error(f"Folder does not exist: {args.folder}")

    config = load_config(args.config)
    scanner = PhotoScanner(config)
    threshold = float(config["recognition"]["auto_accept_threshold"])

    def report(result, status: str, confidence: float | None) -> None:
        candidate = result.candidates[0] if result.candidates else None
        if status == "existing-exif":
            print(f"[SKIP] {result.path}: existing EXIF date")
        elif candidate:
            state = "AUTO" if confidence is not None and confidence >= threshold and not candidate.ambiguous else "REVIEW"
            print(f"[{state}] {result.path} -> {candidate.value.isoformat()} "
                  f"(confidence={confidence:.2f}; methods={','.join(result.methods)})")
            if args.apply and not args.dry_run and state == "AUTO":
                try:
                    apply_config = deepcopy(config)
                    # Explicit --apply authorizes replacing possibly incorrect EXIF values.
                    apply_config.setdefault("metadata", {})["overwrite_existing"] = True
                    apply_date(result.path, candidate.value, apply_config)
                    print("       stamp date written to metadata and file timestamp updated")
                except Exception as exc:
                    print(f"       ERROR writing metadata: {exc}")
        else:
            print(f"[NONE] {result.path}: date not detected")

    scanner.scan(args.folder, report)


if __name__ == "__main__":
    main()
