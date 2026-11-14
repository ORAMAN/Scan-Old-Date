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


def test_default_config_path_is_absolute_and_independent_of_working_directory(
    tmp_path, monkeypatch
):
    from scan_old_date.config import default_config_path

    monkeypatch.chdir(tmp_path)

    path = default_config_path()

    assert path.is_absolute()
    assert path.name == "settings.yaml"
    assert path.parent.name == "config"
