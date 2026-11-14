from pathlib import Path

from scan_old_date.external_tools import resolve_exiftool, resolve_tesseract


def _make_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("placeholder", encoding="utf-8")
    return path


def test_resolve_tesseract_from_executable_path(tmp_path):
    executable = _make_file(tmp_path / "tesseract.exe")
    assert resolve_tesseract(executable) == str(executable.resolve())


def test_resolve_tesseract_from_install_folder_bin(tmp_path):
    executable = _make_file(tmp_path / "Tesseract-OCR" / "bin" / "tesseract.exe")
    assert resolve_tesseract(executable.parent.parent) == str(executable.resolve())


def test_resolve_exiftool_from_install_folder(tmp_path):
    executable = _make_file(tmp_path / "ExifTool" / "exiftool.exe")
    assert resolve_exiftool(executable.parent) == str(executable.resolve())


def test_resolve_exiftool_windows_package_name(tmp_path):
    executable = _make_file(tmp_path / "ExifTool" / "bin" / "exiftool(-k).exe")
    assert resolve_exiftool(executable.parent.parent) == str(executable.resolve())
