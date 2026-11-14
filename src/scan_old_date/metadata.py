from __future__ import annotations

import os
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path

from PIL import Image

from .external_tools import resolve_exiftool


def read_exif_date(path: str | Path, exiftool: str = "exiftool") -> str | None:
    executable = resolve_exiftool(exiftool)
    if executable:
        try:
            result = subprocess.run(
                [executable, "-s3", "-DateTimeOriginal", "-CreateDate", str(path)],
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

    try:
        with Image.open(path) as image:
            exif = image.getexif()
            for tag_id in (36867, 306, 36868):
                value = exif.get(tag_id)
                if value:
                    return str(value)
    except Exception:
        pass
    return None


def apply_date(
    path: str | Path,
    photo_date: date,
    config: dict,
) -> dict[str, str | bool]:
    path = Path(path)
    metadata_cfg = config["metadata"]
    exiftool_setting = metadata_cfg.get("exiftool_path", "exiftool")
    exiftool = resolve_exiftool(exiftool_setting)
    write_exif = metadata_cfg.get("write_exif", True)

    if write_exif and not exiftool:
        raise RuntimeError(
            "ExifTool не найден. Укажите путь к exiftool.exe или папку его установки "
            "в настройках приложения."
        )
    if write_exif and not metadata_cfg.get("overwrite_existing", False):
        existing = read_exif_date(path, exiftool_setting)
        if existing:
            raise RuntimeError(
                f"В файле уже есть дата EXIF ({existing}); перезапись запрещена настройкой."
            )

    default_time = config.get("scan", {}).get("default_time", "12:00:00")
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
    if write_exif:
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
        os.utime(path, (stat.st_atime, stamp.timestamp()))
        file_time_set = True

    return {
        "exif_written": exif_written,
        "file_time_set": file_time_set,
        "backup_path": backup_path,
        "exif_value": exif_value,
    }
