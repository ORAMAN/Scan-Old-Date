from scan_old_date.config import load_config, save_config


def test_save_and_reload_external_tool_paths(tmp_path):
    config_path = tmp_path / "config" / "settings.yaml"
    config = load_config(config_path)
    config["metadata"]["exiftool_path"] = r"C:\Tools\ExifTool"
    config["tesseract"]["command"] = r"C:\Program Files\Tesseract-OCR"

    saved_path = save_config(config, config_path)

    assert saved_path == config_path
    loaded = load_config(config_path)
    assert loaded["metadata"]["exiftool_path"] == r"C:\Tools\ExifTool"
    assert loaded["tesseract"]["command"] == r"C:\Program Files\Tesseract-OCR"
