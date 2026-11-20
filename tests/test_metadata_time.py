from datetime import date, time

from PIL import Image

import scan_old_date.metadata as metadata_module


def test_apply_date_uses_time_detected_on_camera_stamp(tmp_path, monkeypatch):
    photo = tmp_path / "old-photo.jpg"
    Image.new("RGB", (32, 24), "black").save(photo)

    monkeypatch.setattr(metadata_module, "resolve_exiftool", lambda _path: "exiftool")
    captured = {}

    class Completed:
        returncode = 0
        stdout = "1 image files updated"
        stderr = ""

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return Completed()

    monkeypatch.setattr(metadata_module.subprocess, "run", fake_run)
    config = {
        "scan": {"default_time": "12:00:00"},
        "metadata": {
            "exiftool_path": "exiftool",
            "write_exif": True,
            "overwrite_existing": True,
            "backup_before_write": False,
            "set_file_times": False,
        },
    }

    result = metadata_module.apply_date(
        photo, date(2009, 8, 7), config, time(16, 57, 12)
    )

    assert "-DateTimeOriginal=2009:08:07 16:57:12" in captured["command"]
    assert "-CreateDate=2009:08:07 16:57:12" in captured["command"]
    assert result["exif_value"] == "2009:08:07 16:57:12"
