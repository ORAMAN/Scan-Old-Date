from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .config import load_config
from .metadata import apply_date
from .scanner import PhotoScanner


class ScanWorker(QThread):
    result_ready = Signal(object, str, object)
    scan_finished = Signal(int)
    scan_error = Signal(str)

    def __init__(self, root: Path, config: dict):
        super().__init__()
        self.root = root
        self.config = config

    def run(self):
        try:
            scanner = PhotoScanner(self.config)
            count = 0

            def publish(result, status, confidence):
                nonlocal count
                count += 1
                self.result_ready.emit(result, status, confidence)

            scanner.scan(self.root, publish)
            self.scan_finished.emit(count)
        except Exception as exc:
            self.scan_error.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scan-Old-Date")
        self.resize(1280, 780)
        self.config = load_config()
        self.row_meta: list[dict] = []
        self.worker: ScanWorker | None = None

        central = QWidget()
        layout = QVBoxLayout(central)
        path_row = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Выберите папку с фотографиями…")
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self.choose_folder)
        path_row.addWidget(self.folder, 1)
        path_row.addWidget(browse)
        layout.addLayout(path_row)

        controls = QHBoxLayout()
        self.dry_run = QCheckBox("Только проверка (Dry Run)")
        self.dry_run.setChecked(True)
        self.dry_run.setToolTip("При включённом режиме файлы не изменяются.")
        self.scan_button = QPushButton("Сканировать")
        self.scan_button.clicked.connect(self.start_scan)
        self.apply_button = QPushButton("Применить выбранные даты")
        self.apply_button.clicked.connect(self.apply_selected)
        controls.addWidget(self.dry_run)
        controls.addStretch(1)
        controls.addWidget(self.scan_button)
        controls.addWidget(self.apply_button)
        layout.addLayout(controls)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Файл", "Дата (редактируется)", "Уверенность", "Статус", "Метод"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self.on_item_changed)
        layout.addWidget(self.table, 1)
        self.status = QLabel(
            "Готово. Сначала выполните Dry Run. Дату можно исправить прямо в таблице."
        )
        layout.addWidget(self.status)
        self.setCentralWidget(central)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Папка с фотографиями")
        if folder:
            self.folder.setText(folder)

    def start_scan(self):
        root = Path(self.folder.text().strip())
        if not root.is_dir():
            QMessageBox.warning(self, "Scan-Old-Date", "Выберите существующую папку.")
            return
        self.table.setRowCount(0)
        self.row_meta.clear()
        self.scan_button.setEnabled(False)
        self.status.setText("Сканирование выполняется…")
        self.worker = ScanWorker(root, self.config)
        self.worker.result_ready.connect(self.add_result)
        self.worker.scan_finished.connect(self.scan_finished)
        self.worker.scan_error.connect(self.scan_error)
        self.worker.start()

    def add_result(self, result, status: str, confidence):
        candidate = result.candidates[0] if result.candidates else None
        existing_date = result.raw_text[0] if status == "existing-exif" and result.raw_text else ""
        if existing_date:
            date_text = existing_date[:10].replace(":", "-")
        else:
            date_text = candidate.value.isoformat() if candidate else ""

        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(result.path))
        date_item = QTableWidgetItem(date_text)
        if status != "existing-exif" or self.config["metadata"].get("overwrite_existing", False):
            date_item.setFlags(date_item.flags() | Qt.ItemFlag.ItemIsEditable)
        else:
            date_item.setFlags(date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 1, date_item)
        self.table.setItem(
            row, 2, QTableWidgetItem(f"{confidence:.2f}" if confidence is not None else "")
        )
        self.table.setItem(row, 3, QTableWidgetItem(status))
        self.table.setItem(row, 4, QTableWidgetItem(", ".join(result.methods)))
        self.row_meta.append({
            "confidence": float(confidence or 0.0),
            "ambiguous": bool(candidate.ambiguous) if candidate else True,
            "manual": False,
            "original_date": date_text,
            "existing_exif": status == "existing-exif",
        })

    def scan_finished(self, count: int):
        self.scan_button.setEnabled(True)
        self.status.setText(
            f"Сканирование завершено. Файлов: {count}. "
            "Проверьте распознанные даты и выберите строки для применения."
        )
        self.worker = None

    def scan_error(self, message: str):
        self.scan_button.setEnabled(True)
        self.status.setText("Ошибка сканирования.")
        QMessageBox.critical(self, "Ошибка сканирования", message)
        self.worker = None

    def on_item_changed(self, item):
        if item.column() != 1:
            return
        row = item.row()
        if row < len(self.row_meta):
            meta = self.row_meta[row]
            meta["manual"] = item.text().strip() != meta["original_date"]
            if meta["manual"]:
                self.table.item(row, 3).setText("manual-review")

    def apply_selected(self):
        if self.dry_run.isChecked():
            QMessageBox.information(
                self, "Dry Run", "Снимите флажок Dry Run, чтобы разрешить запись."
            )
            return
        selected = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not selected:
            QMessageBox.information(self, "Scan-Old-Date", "Выберите строки для применения.")
            return
        prepared = []
        for row in selected:
            meta = self.row_meta[row]
            if meta["existing_exif"] and not self.config["metadata"].get("overwrite_existing", False):
                continue
            text = self.table.item(row, 1).text().strip()
            try:
                parsed = date.fromisoformat(text)
            except ValueError:
                self.table.item(row, 3).setText("invalid-date")
                continue
            if not meta["manual"] and (
                meta["ambiguous"]
                or meta["confidence"] < float(self.config["recognition"]["auto_accept_threshold"])
            ):
                self.table.item(row, 3).setText("needs-review")
                continue
            prepared.append((row, self.table.item(row, 0).text(), parsed))

        if not prepared:
            QMessageBox.information(
                self, "Scan-Old-Date",
                "Нет готовых дат. Исправьте дату вручную или проверьте настройки перезаписи EXIF."
            )
            return
        answer = QMessageBox.question(
            self, "Подтверждение",
            f"Записать даты для {len(prepared)} файлов? Перед изменением будут созданы резервные копии.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        done = 0
        for row, path, value in prepared:
            try:
                apply_date(path, value, self.config)
                self.table.item(row, 3).setText("applied")
                done += 1
            except Exception as exc:
                self.table.item(row, 3).setText(f"error: {exc}")
        self.status.setText(f"Применено: {done} из {len(prepared)}")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
