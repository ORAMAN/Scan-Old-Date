from __future__ import annotations

import os
import shutil
from pathlib import Path


def _resolve_tool(
    value: str | Path | None,
    executable_names: tuple[str, ...],
    path_names: tuple[str, ...],
) -> str | None:
    raw = str(value or "").strip().strip('"').strip("'")
    expanded = os.path.expandvars(os.path.expanduser(raw))

    if expanded:
        candidate = Path(expanded)
        if candidate.is_file():
            return str(candidate.resolve())

        if candidate.is_dir():
            # Common layouts: executable in the selected folder or in its bin subfolder.
            for relative_name in executable_names:
                for base in (candidate, candidate / "bin"):
                    executable = base / relative_name
                    if executable.is_file():
                        return str(executable.resolve())

        # A bare command name may be available through PATH.
        if not candidate.is_absolute() and len(candidate.parts) == 1:
            found = shutil.which(expanded)
            if found:
                return str(Path(found).resolve())
        return None

    for command_name in path_names:
        found = shutil.which(command_name)
        if found:
            return str(Path(found).resolve())
    return None


def resolve_tesseract(value: str | Path | None = "") -> str | None:
    """Resolve a Tesseract executable from an EXE path, install folder, or PATH."""
    return _resolve_tool(
        value,
        executable_names=("tesseract.exe", "tesseract"),
        path_names=("tesseract.exe", "tesseract"),
    )


def resolve_exiftool(value: str | Path | None = "exiftool") -> str | None:
    """Resolve an ExifTool executable from an EXE path, install folder, or PATH."""
    return _resolve_tool(
        value,
        executable_names=("exiftool.exe", "exiftool(-k).exe", "exiftool"),
        path_names=("exiftool.exe", "exiftool"),
    )
