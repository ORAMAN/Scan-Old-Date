from scan_old_date.database import ScanDatabase


def test_scan_database_persists_recognized_time(tmp_path):
    database = ScanDatabase(tmp_path / "scan.sqlite3")
    try:
        database.add_result(
            "photo.jpg",
            "2009-08-07",
            0.94,
            "2009/08/0704:57PM",
            "tesseract",
            "review",
            "",
            "16:57:00",
        )
        stored_time = database.connection.execute(
            "SELECT detected_time FROM scans WHERE path = ?",
            ("photo.jpg",),
        ).fetchone()[0]
        assert stored_time == "16:57:00"
    finally:
        database.close()
