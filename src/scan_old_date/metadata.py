from __future__ import annotations

import os
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path


def read_exif_date(path: str | Path, exiftool: str = "exiftool") -> str | None:
    try:
        result = subprocess.run(
            [exiftool, "-s3", "-DateTimeOriginal", "-CreateDate", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        for line in result.stdout.splitlines():
            value = line.strip()
            if value and value != "-":
                return value
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def apply_date(
    path: str | Path,
    photo_date: date,
    config: dict,
) -> dict[str, str | bool]:
    path = Path(path)
    metadata_cfg = config["metadata"]
    exiftool = metadata_cfg.get("exiftool_path", "exiftool")
    default_time = metadata_cfg.get("default_time", "12:00:00")
    stamp = datetime.combine(photo_date, datetime.strptime(default_time, "%H:%M:%S").time())
    exif_value = stamp.strftime("%Y:%m:%d %H:%M:%S")
    backup_path = ""

    if metadata_cfg.get("backup_before_write", True):
        backup_dir = path.parent / metadata_cfg.get("backup_directory", ".scan-old-date-backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_dir / path.name
        if backup_file.exists():
            backup_file = backup_dir / f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}"
        shutil.copy2(path, backup_file)
        backup_path = str(backup_file)

    exif_written = False
    if metadata_cfg.get("write_exif", True):
        command = [
            exiftool,
            "-P",
            "-overwrite_original",
            f"-DateTimeOriginal={exif_value}",
            f"-CreateDate={exif_value}",
            f"-ModifyDate={exif_value}",
            str(path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "ExifTool failed")
        exif_written = True

    file_time_set = False
    if metadata_cfg.get("set_file_times", True):
        stat = path.stat()
        timestamp = stamp.timestamp()
        os.utime(path, (stat.st_atime, timestamp))
        file_time_set = True

    return {
        "exif_written": exif_written,
        "file_time_set": file_time_set,
        "backup_path": backup_path,
        "exif_value": exif_value,
    }
