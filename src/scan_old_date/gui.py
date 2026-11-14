from __future__ import annotations

import sys
from copy import deepcopy
from datetime import date
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from PIL import Image, ImageDraw, ImageOps

from .config import default_config_path, load_config, save_config
from .external_tools import resolve_exiftool, resolve_tesseract
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
        self.config_path = default_config_path()
        self.config = load_config(self.config_path)
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

        tools_group = QGroupBox(
            "Внешние приложения — укажите EXE-файл, папку установки или команду из PATH"
        )
        tools_layout = QGridLayout(tools_group)

        self.exiftool_path_input = QLineEdit(
            str(self.config.get("metadata", {}).get("exiftool_path", "exiftool"))
        )
        self.exiftool_path_input.setPlaceholderText(
            r"Например: C:\Tools\ExifTool или C:\Tools\ExifTool\exiftool.exe"
        )
        self.tesseract_path_input = QLineEdit(
            str(self.config.get("tesseract", {}).get("command", ""))
        )
        self.tesseract_path_input.setPlaceholderText(
            r"Например: C:\Program Files\Tesseract-OCR или tesseract.exe"
        )

        tools_layout.addWidget(QLabel("ExifTool:"), 0, 0)
        tools_layout.addWidget(self.exiftool_path_input, 0, 1)
        exif_file_button = QPushButton("EXE…")
        exif_file_button.clicked.connect(
            lambda: self.choose_tool_file(self.exiftool_path_input, "ExifTool")
        )
        exif_folder_button = QPushButton("Папка…")
        exif_folder_button.clicked.connect(
            lambda: self.choose_tool_folder(self.exiftool_path_input, "ExifTool")
        )
        tools_layout.addWidget(exif_file_button, 0, 2)
        tools_layout.addWidget(exif_folder_button, 0, 3)
        self.exiftool_status = QLabel("Не проверено")
        tools_layout.addWidget(self.exiftool_status, 0, 4)

        tools_layout.addWidget(QLabel("Tesseract OCR:"), 1, 0)
        tools_layout.addWidget(self.tesseract_path_input, 1, 1)
        tess_file_button = QPushButton("EXE…")
        tess_file_button.clicked.connect(
            lambda: self.choose_tool_file(self.tesseract_path_input, "Tesseract OCR")
        )
        tess_folder_button = QPushButton("Папка…")
        tess_folder_button.clicked.connect(
            lambda: self.choose_tool_folder(self.tesseract_path_input, "Tesseract OCR")
        )
        tools_layout.addWidget(tess_file_button, 1, 2)
        tools_layout.addWidget(tess_folder_button, 1, 3)
        self.tesseract_status = QLabel("Не проверено")
        tools_layout.addWidget(self.tesseract_status, 1, 4)

        tools_layout.setColumnStretch(1, 1)
        layout.addWidget(tools_group)

        tool_buttons = QHBoxLayout()
        self.check_tools_button = QPushButton("Проверить пути")
        self.check_tools_button.clicked.connect(self.check_tools)
        self.save_settings_button = QPushButton("Сохранить настройки")
        self.save_settings_button.clicked.connect(lambda: self.save_settings())
        tool_buttons.addWidget(self.check_tools_button)
        tool_buttons.addWidget(self.save_settings_button)
        tool_buttons.addStretch(1)
        layout.addLayout(tool_buttons)

        controls = QHBoxLayout()
        self.dry_run = QCheckBox("Только проверка (Dry Run)")
        self.dry_run.setChecked(True)
        self.dry_run.setToolTip("При включённом режиме файлы не изменяются.")
        self.scan_button = QPushButton("Сканировать")
        self.scan_button.clicked.connect(self.start_scan)
        self.preview_button = QPushButton("Показать рамки штампа")
        self.preview_button.clicked.connect(self.show_selected_preview)
        self.apply_button = QPushButton("Применить выбранные даты")
        self.apply_button.clicked.connect(self.apply_selected)
        controls.addWidget(self.dry_run)
        controls.addWidget(self.preview_button)
        controls.addStretch(1)
        controls.addWidget(self.scan_button)
        controls.addWidget(self.apply_button)
        layout.addLayout(controls)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [
                "Файл",
                "Дата по штампу (редактируется)",
                "Существующая EXIF-дата (справочно)",
                "Уверенность",
                "Статус",
                "Метод",
                "Областей",
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.cellDoubleClicked.connect(self.show_region_preview)
        self.table.setToolTip(
            "Двойной щелчок по строке или кнопка «Показать рамки штампа» "
            "открывает фотографию с прямоугольниками областей OCR."
        )
        layout.addWidget(self.table, 1)
        self.status = QLabel(
            "Готово. Сначала выполните Dry Run. Дата редактируется в формате ГГГГ-ММ-ДД. "
            "Двойной щелчок по строке показывает рамки областей OCR."
        )
        layout.addWidget(self.status)
        self.setCentralWidget(central)

        self.exiftool_path_input.editingFinished.connect(self.refresh_tool_status)
        self.tesseract_path_input.editingFinished.connect(self.refresh_tool_status)
        self.refresh_tool_status()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Папка с фотографиями")
        if folder:
            self.folder.setText(folder)

    def choose_tool_file(self, field: QLineEdit, tool_name: str):
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Выберите исполняемый файл — {tool_name}",
            "",
            "Исполняемые файлы (*.exe);;Все файлы (*)",
        )
        if path:
            field.setText(path)
            self.refresh_tool_status()

    def choose_tool_folder(self, field: QLineEdit, tool_name: str):
        folder = QFileDialog.getExistingDirectory(
            self, f"Выберите папку установки — {tool_name}"
        )
        if folder:
            field.setText(folder)
            self.refresh_tool_status()

    def sync_tool_settings(self):
        self.config.setdefault("metadata", {})["exiftool_path"] = (
            self.exiftool_path_input.text().strip()
        )
        self.config.setdefault("tesseract", {})["command"] = (
            self.tesseract_path_input.text().strip()
        )

    def refresh_tool_status(self):
        self.sync_tool_settings()
        exiftool = resolve_exiftool(self.exiftool_path_input.text())
        tesseract = resolve_tesseract(self.tesseract_path_input.text())

        self.exiftool_status.setText(
            f"Найден: {exiftool}" if exiftool else "Не найден"
        )
        self.tesseract_status.setText(
            f"Найден: {tesseract}" if tesseract else "Не найден"
        )

    def check_tools(self):
        self.refresh_tool_status()
        exiftool = resolve_exiftool(self.exiftool_path_input.text())
        tesseract = resolve_tesseract(self.tesseract_path_input.text())
        details = [
            f"ExifTool: {exiftool or 'НЕ НАЙДЕН'}",
            f"Tesseract OCR: {tesseract or 'НЕ НАЙДЕН'}",
        ]
        QMessageBox.information(self, "Проверка внешних приложений", "\n".join(details))

    def save_settings(self, show_message: bool = True) -> bool:
        self.sync_tool_settings()
        try:
            saved_path = save_config(self.config, self.config_path)
        except Exception as exc:
            QMessageBox.critical(
                self, "Ошибка сохранения настроек",
                f"Не удалось сохранить конфигурацию: {exc}",
            )
            return False

        self.refresh_tool_status()
        if show_message:
            QMessageBox.information(
                self, "Настройки сохранены",
                f"Пути к внешним приложениям сохранены в:\n{saved_path}",
            )
        return True

    def start_scan(self):
        root = Path(self.folder.text().strip())
        if not root.is_dir():
            QMessageBox.warning(self, "Scan-Old-Date", "Выберите существующую папку.")
            return

        if not self.save_settings(show_message=False):
            return

        tesseract = resolve_tesseract(self.tesseract_path_input.text())
        if not tesseract:
            QMessageBox.critical(
                self,
                "Tesseract OCR не найден",
                "Не удалось найти Tesseract OCR. Укажите полный путь к tesseract.exe "
                "или выберите папку установки в верхней части окна. Можно также "
                "установить Tesseract и добавить его в PATH.",
            )
            return

        self.table.setRowCount(0)
        self.row_meta.clear()
        self.scan_button.setEnabled(False)
        self.status.setText("Сканирование выполняется…")
        self.worker = ScanWorker(root, self.config)
        self.worker.result_ready.connect(self.add_result)
        self.worker.scan_finished.connect(self.scan_finished)
        self.worker.scan_error.connect(self.scan_error)
        self.worker.finished.connect(self.worker_thread_finished)
        self.worker.start()

    def add_result(self, result, status: str, confidence):
        # Keep one syntactically valid date in the table. Alternative OCR
        # interpretations are shown in the region preview and the cell tooltip.
        candidate = result.candidates[0] if result.candidates else None
        stamp_date_text = candidate.value.isoformat() if candidate else ""
        alternatives = list(
            dict.fromkeys(item.value.isoformat() for item in result.candidates)
        )
        existing_exif = getattr(result, "existing_exif_date", None) or ""
        regions = getattr(result, "region_diagnostics", []) or []

        row = self.table.rowCount()
        self.table.insertRow(row)
        file_item = QTableWidgetItem(result.path)
        file_item.setToolTip("Двойной щелчок по строке — показать найденные области.")
        self.table.setItem(row, 0, file_item)

        date_item = QTableWidgetItem(stamp_date_text)
        date_item.setFlags(date_item.flags() | Qt.ItemFlag.ItemIsEditable)
        tooltip = (
            "Дата получена из видимого штампа, EXIF не используется как источник даты. "
            "Формат: ГГГГ-ММ-ДД. Исправление значения вручную разрешает его применение."
        )
        if candidate and candidate.ambiguous:
            tooltip += (
                "\nРаспознавание неоднозначно. Возможные значения: "
                + ", ".join(alternatives)
            )
        if alternatives:
            tooltip += "\nДругие варианты OCR: " + ", ".join(alternatives[1:])
        date_item.setToolTip(tooltip)
        self.table.setItem(row, 1, date_item)
        self.table.setItem(row, 2, QTableWidgetItem(existing_exif))
        self.table.setItem(
            row,
            3,
            QTableWidgetItem(
                f"{confidence:.2f}" if confidence is not None else ""
            ),
        )
        self.table.setItem(row, 4, QTableWidgetItem(status))
        self.table.setItem(row, 5, QTableWidgetItem(", ".join(result.methods)))
        self.table.setItem(row, 6, QTableWidgetItem(str(len(regions))))

        self.row_meta.append(
            {
                "confidence": float(confidence or 0.0),
                "ambiguous": bool(candidate.ambiguous) if candidate else True,
                "manual": False,
                "original_date": stamp_date_text,
                "existing_exif": bool(existing_exif),
                "regions": regions,
            }
        )

    def show_selected_preview(self):
        selected = sorted(
            {index.row() for index in self.table.selectionModel().selectedRows()}
        )
        if not selected:
            QMessageBox.information(
                self, "Просмотр областей", "Сначала выберите строку с фотографией."
            )
            return
        self.show_region_preview(selected[0], 0)

    def show_region_preview(self, row: int, column: int = 0):
        if row < 0 or row >= len(self.row_meta):
            return
        path = self.table.item(row, 0).text()
        diagnostics = self.row_meta[row].get("regions", [])

        try:
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                original_width, original_height = image.size
                scale = min(
                    1.0,
                    1180 / max(1, original_width),
                    650 / max(1, original_height),
                )
                display_width = max(1, int(original_width * scale))
                display_height = max(1, int(original_height * scale))
                image = image.resize(
                    (display_width, display_height), Image.Resampling.LANCZOS
                )
        except Exception as exc:
            QMessageBox.critical(
                self, "Просмотр областей", f"Не удалось открыть фотографию:\n{exc}"
            )
            return

        draw = ImageDraw.Draw(image)
        details: list[str] = []
        for index, item in enumerate(diagnostics, start=1):
            bbox = item.get("bbox")
            has_date = bool(item.get("dates"))
            skipped = bool(item.get("skipped"))
            color = (
                (155, 155, 155)
                if skipped
                else ((30, 220, 90) if has_date else (255, 170, 35))
            )
            if bbox and len(bbox) == 4:
                x1, y1, x2, y2 = bbox
                rectangle = (
                    int(x1 * scale),
                    int(y1 * scale),
                    int(x2 * scale),
                    int(y2 * scale),
                )
                draw.rectangle(rectangle, outline=color, width=3)
                label_y = max(0, rectangle[1] - 16)
                draw.text(
                    (rectangle[0] + 2, label_y),
                    f"#{index} {item.get('label', '')}",
                    fill=color,
                    stroke_width=1,
                    stroke_fill=(0, 0, 0),
                )

            x1, y1, x2, y2 = bbox or ("?", "?", "?", "?")
            line = (
                f"#{index} {item.get('label', 'область')} | "
                f"рамка: {x1}, {y1} — {x2}, {y2} | "
                f"OCR: {('пропущен: дата уже найдена' if skipped else (item.get('ocr_text') or 'текст не найден'))} | "
                f"уверенность OCR: {item.get('ocr_confidence', 0)} | "
                f"поворот: {item.get('rotation', 0)}°"
            )
            dates = item.get("dates") or []
            if dates:
                line += " | даты: " + ", ".join(
                    f"{date_item['value']} ({date_item['confidence']:.2f})"
                    for date_item in dates
                )
            if item.get("error"):
                line += " | ошибка: " + str(item["error"])
            details.append(line)

            for read in item.get("reads", []):
                if read.get("text") and read.get("text") != item.get("ocr_text"):
                    details.append(
                        f"   Вариант OCR: {read['text']} "
                        f"(поворот {read['rotation']}°, {read['variant']}, "
                        f"PSM {read['psm']}, conf {read['confidence']:.2f})"
                    )

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Области распознавания — {Path(path).name}")
        dialog.resize(1260, 900)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "Зелёная рамка — в области OCR найдена календарно корректная дата; "
            "оранжевая — проверенный фрагмент не дал полной даты. "
            "Прямоугольник показывает именно фрагмент, переданный OCR, "
            "а не контуры отдельных цифр."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        image_bytes = image.tobytes("raw", "RGB")
        qimage = QImage(
            image_bytes,
            image.width,
            image.height,
            image.width * 3,
            QImage.Format.Format_RGB888,
        ).copy()
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setPixmap(QPixmap.fromImage(qimage))
        layout.addWidget(image_label, 1)

        details_box = QPlainTextEdit()
        details_box.setReadOnly(True)
        details_box.setMaximumHeight(190)
        details_box.setPlainText(
            "\n".join(details) if details else "Детектор не вернул областей."
        )
        layout.addWidget(details_box)
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()

    def scan_finished(self, count: int):
        self.status.setText(
            f"Сканирование завершено. Файлов: {count}. "
            "Проверьте распознанные даты и выберите строки для применения."
        )

    def scan_error(self, message: str):
        self.status.setText("Ошибка сканирования.")
        QMessageBox.critical(self, "Ошибка сканирования", message)

    def worker_thread_finished(self):
        self.scan_button.setEnabled(True)
        self.worker = None

    def on_item_changed(self, item):
        if item.column() != 1:
            return
        row = item.row()
        if row < len(self.row_meta):
            meta = self.row_meta[row]
            meta["manual"] = item.text().strip() != meta["original_date"]
            if meta["manual"]:
                self.table.item(row, 3).setText("manual")
                self.table.item(row, 3).setToolTip(
                    "Дата изменена вручную. Она будет применена после общего подтверждения."
                )
            else:
                self.table.item(row, 3).setText(f"{meta['confidence']:.2f}")
                self.table.item(row, 3).setToolTip("Оценка OCR.")

    def apply_selected(self):
        if self.dry_run.isChecked():
            QMessageBox.information(
                self, "Dry Run", "Снимите флажок Dry Run, чтобы разрешить запись."
            )
            return
        if self.config.get("metadata", {}).get("write_exif", True):
            exiftool = resolve_exiftool(self.exiftool_path_input.text())
            if not exiftool:
                QMessageBox.critical(
                    self,
                    "ExifTool не найден",
                    "Для записи EXIF укажите путь к exiftool.exe или папку установки "
                    "в верхней части окна.",
                )
                return

        selected = sorted(
            {index.row() for index in self.table.selectionModel().selectedRows()}
        )
        if not selected:
            QMessageBox.information(
                self, "Scan-Old-Date", "Выберите строки для применения."
            )
            return

        prepared = []
        requires_confirmation = []
        for row in selected:
            meta = self.row_meta[row]
            text = self.table.item(row, 1).text().strip()
            try:
                parsed = date.fromisoformat(text)
            except ValueError:
                self.table.item(row, 3).setText("invalid-date")
                continue

            item = (row, self.table.item(row, 0).text(), parsed)
            if not meta["manual"] and (
                meta["ambiguous"]
                or meta["confidence"]
                < float(self.config["recognition"]["auto_accept_threshold"])
            ):
                requires_confirmation.append(item)
            else:
                prepared.append(item)

        if requires_confirmation:
            preview_lines = [
                f"• {Path(path).name}: {value.isoformat()}"
                for _, path, value in requires_confirmation[:8]
            ]
            if len(requires_confirmation) > 8:
                preview_lines.append(
                    f"… и ещё {len(requires_confirmation) - 8} файлов"
                )
            answer = QMessageBox.question(
                self,
                "Низкая уверенность распознавания",
                f"У {len(requires_confirmation)} выбранных дат низкая уверенность "
                "или несколько вариантов. Записать именно те значения, которые "
                "сейчас показаны в редактируемом столбце?\n\n"
                + "\n".join(preview_lines)
                + "\n\nПроверьте даты и рамки OCR перед подтверждением.",
            )
            if answer == QMessageBox.StandardButton.Yes:
                prepared.extend(requires_confirmation)

        if not prepared:
            QMessageBox.information(
                self,
                "Scan-Old-Date",
                "Нет дат для записи. Проверьте формат ГГГГ-ММ-ДД, "
                "исправьте дату вручную или подтвердите выбранные значения "
                "с низкой уверенностью.",
            )
            return

        files_with_exif = sum(
            1 for row, _, _ in prepared if self.row_meta[row]["existing_exif"]
        )
        warning = (
            f"\n\nУ {files_with_exif} выбранных файлов уже есть EXIF-дата. "
            "Она будет заменена датой, распознанной по штампу."
            if files_with_exif
            else ""
        )
        answer = QMessageBox.question(
            self,
            "Подтверждение записи",
            f"Записать даты для {len(prepared)} файлов?"
            f"{warning}\n\nПеред изменением будут созданы резервные копии.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        apply_config = deepcopy(self.config)
        # The user's explicit confirmation authorizes replacing possibly incorrect EXIF.
        apply_config.setdefault("metadata", {})["overwrite_existing"] = True
        done = 0
        for row, path, value in prepared:
            try:
                apply_date(path, value, apply_config)
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
