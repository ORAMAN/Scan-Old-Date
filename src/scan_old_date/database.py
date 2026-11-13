from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


class ScanDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL,
                scanned_at TEXT NOT NULL,
                detected_date TEXT,
                confidence REAL,
                raw_text TEXT,
                methods TEXT,
                status TEXT NOT NULL,
                details TEXT
            )"""
        )
        self.connection.commit()

    def add_result(
        self, path: str, detected_date: str | None, confidence: float | None,
        raw_text: str, methods: str, status: str, details: str = ""
    ) -> None:
        self.connection.execute(
            """INSERT INTO scans
            (path, scanned_at, detected_date, confidence, raw_text, methods, status, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                path, datetime.now().isoformat(timespec="seconds"), detected_date,
                confidence, raw_text, methods, status, details,
            ),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
