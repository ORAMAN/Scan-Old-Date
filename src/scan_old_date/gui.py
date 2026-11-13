from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .config import load_config
from .metadata import apply_date
from .scanner import PhotoScanner


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scan-Old-Date")
        self.resize(1180, 760)
        self.config = load_config()
        self.rows: list[tuple[str, date, float, bool]] = []

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
        self.apply_button = QPushButton("Применить подтверждённые даты")
        self.apply_button.clicked.connect(self.apply_selected)
        controls.addWidget(self.dry_run)
        controls.addStretch(1)
        controls.addWidget(self.scan_button)
        controls.addWidget(self.apply_button)
        layout.addLayout(controls)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Файл", "Распознано", "Уверенность", "Статус", "Метод"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 1)
        self.status = QLabel("Готово. Сначала выполните Dry Run.")
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
        self.scan_button.setEnabled(False)
        self.table.setRowCount(0)
        self.rows.clear()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            scanner = PhotoScanner(self.config)

            def add_row(result, status, confidence):
                candidate = result.candidates[0] if result.candidates else None
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(result.path))
                self.table.setItem(row, 1, QTableWidgetItem(candidate.value.isoformat() if candidate else ""))
                self.table.setItem(row, 2, QTableWidgetItem(f"{confidence:.2f}" if confidence is not None else ""))
                self.table.setItem(row, 3, QTableWidgetItem(status))
                self.table.setItem(row, 4, QTableWidgetItem(", ".join(result.methods)))
                if candidate:
                    self.rows.append((result.path, candidate.value, candidate.confidence, candidate.ambiguous))
                else:
                    self.rows.append((result.path, date.min, 0.0, True))

            scanner.scan(root, add_row)
            self.status.setText(f"Сканирование завершено. Найдено файлов: {self.table.rowCount()}")
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка сканирования", str(exc))
        finally:
            QApplication.restoreOverrideCursor()
            self.scan_button.setEnabled(True)

    def apply_selected(self):
        if self.dry_run.isChecked():
            QMessageBox.information(self, "Dry Run", "Снимите флажок Dry Run, чтобы разрешить запись.")
            return
        selected = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not selected:
            QMessageBox.information(self, "Scan-Old-Date", "Выберите строки для применения.")
            return
        answer = QMessageBox.question(
            self, "Подтверждение",
            f"Записать даты для {len(selected)} выбранных файлов? Перед изменением будут созданы резервные копии.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        done = 0
        for row in selected:
            path, value, confidence, ambiguous = self.rows[row]
            if value == date.min or ambiguous or confidence < float(self.config["recognition"]["auto_accept_threshold"]):
                continue
            try:
                apply_date(path, value, self.config)
                self.table.item(row, 3).setText("applied")
                done += 1
            except Exception as exc:
                self.table.item(row, 3).setText(f"error: {exc}")
        self.status.setText(f"Применено: {done}")

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
