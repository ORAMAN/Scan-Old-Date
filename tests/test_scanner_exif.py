from datetime import date

from scan_old_date.date_parser import ParsedDate
from scan_old_date.ocr import RecognitionResult
import scan_old_date.scanner as scanner_module


def _config(tmp_path):
    return {
        "scan": {
            "extensions": [".jpg"],
            "recursive": True,
            # Legacy true value must no longer suppress visual recognition.
            "skip_existing_exif_date": True,
        },
        "metadata": {
            "exiftool_path": "exiftool",
            "backup_directory": ".scan-old-date-backups",
        },
        "database": {"path": str(tmp_path / "scan.sqlite3")},
    }


def test_existing_exif_date_does_not_skip_stamp_recognition(tmp_path, monkeypatch):
    root = tmp_path / "photos"
    root.mkdir()
    photo = root / "old-photo.jpg"
    photo.write_bytes(b"placeholder")

    expected_stamp_date = date(1998, 7, 21)
    recognized = RecognitionResult(
        str(photo),
        [ParsedDate(expected_stamp_date, 0.94, "21.07.1998", False)],
        ["21.07.1998"],
        ["tesseract"],
        [],
    )

    class FakeRecognizer:
        def __init__(self, config):
            self.called = False

        def recognize(self, path):
            self.called = True
            return recognized

    monkeypatch.setattr(scanner_module, "read_exif_date", lambda *args: "2012:01:02 03:04:05")
    monkeypatch.setattr(scanner_module, "HybridRecognizer", FakeRecognizer)

    statuses = []
    results = scanner_module.PhotoScanner(_config(tmp_path)).scan(
        root,
        lambda result, status, confidence: statuses.append((status, confidence)),
    )

    assert len(results) == 1
    assert results[0].candidates[0].value == expected_stamp_date
    assert results[0].existing_exif_date == "2012:01:02 03:04:05"
    assert statuses[0][0] == "review"
    assert statuses[0][1] == 0.94


def test_existing_exif_date_is_not_used_when_stamp_is_not_found(tmp_path, monkeypatch):
    root = tmp_path / "photos"
    root.mkdir()
    photo = root / "no-stamp.jpg"
    photo.write_bytes(b"placeholder")

    class FakeRecognizer:
        def __init__(self, config):
            pass

        def recognize(self, path):
            return RecognitionResult(str(path), [], [], [], [])

    monkeypatch.setattr(scanner_module, "read_exif_date", lambda *args: "2005:06:07 08:09:10")
    monkeypatch.setattr(scanner_module, "HybridRecognizer", FakeRecognizer)

    statuses = []
    results = scanner_module.PhotoScanner(_config(tmp_path)).scan(
        root,
        lambda result, status, confidence: statuses.append(status),
    )

    assert results[0].candidates == []
    assert results[0].existing_exif_date == "2005:06:07 08:09:10"
    assert statuses == ["not-found"]
