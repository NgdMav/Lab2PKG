import sys
import csv
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QLabel, QFileDialog, QTableView, QHeaderView, QAbstractItemView,
    QProgressBar, QMessageBox, QFrame, QStyleFactory, QStatusBar
)
from PySide6.QtGui import QStandardItemModel, QStandardItem, QIcon, QPixmap, QImage
from PySide6.QtCore import Qt, Signal, QObject, QSize, QTimer, QSortFilterProxyModel, QRegularExpression
from scanner import ScanEmitter, scan_folder
from PIL import Image
import threading

class SignalForwarder(QObject):
    item_signal = Signal(dict)
    progress_signal = Signal(int, int)
    finished_signal = Signal()

    def __init__(self):
        super().__init__()

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Inspector — File Metadata Scanner")
        self.setFixedSize(1200, 640)
        self._setup_style()
        self._setup_ui()
        self._connect_signals()

        self.scanner_emitter = None
        self.scan_thread = None

    def _setup_style(self):
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        pal = self.palette()
        pal.setColor(self.backgroundRole(), Qt.white)
        self.setPalette(pal)

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        root.addLayout(top)

        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Выберите папку с изображениями...")
        top.addWidget(self.folder_edit, 1)

        btn_browse = QPushButton("Открыть папку")
        btn_browse.clicked.connect(self._browse_folder)
        top.addWidget(btn_browse)

        self.btn_start = QPushButton("Запустить сканирование")
        top.addWidget(self.btn_start)

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setEnabled(False)
        top.addWidget(self.btn_cancel)

        self.btn_export = QPushButton("Экспорт CSV")
        self.btn_export.setEnabled(False)
        top.addWidget(self.btn_export)

        middle = QHBoxLayout()
        root.addLayout(middle, 1)

        # Table + Filters
        # middle = QVBoxLayout()
        root.addLayout(middle, 1)

        # Filter
        filter_layout = QHBoxLayout()
        self.filter_format = QLineEdit()
        self.filter_format.setPlaceholderText("Фильтр: формат (jpg, png...)")
        self.filter_depth = QLineEdit()
        self.filter_depth.setPlaceholderText("Фильтр: глубина (бит)")
        self.filter_error = QLineEdit()
        self.filter_error.setPlaceholderText("Фильтр: ошибка")

        filter_layout.addWidget(self.filter_format)
        filter_layout.addWidget(self.filter_depth)
        filter_layout.addWidget(self.filter_error)
        root.addLayout(filter_layout)

        # Tabel
        self.table = QTableView()
        self.model = QStandardItemModel(0, 8)
        headers = ["Имя файла", "Формат", "Размер (px)", "DPI", "Глубина (bit)", "Сжатие", "Ошибка", "Дополнительно"]
        self.model.setHorizontalHeaderLabels(headers)

        # Proxy filter
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(-1)
        self.table.setModel(self.proxy)

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        middle.addWidget(self.table, 3)

        # Preview & info
        right = QVBoxLayout()
        middle.addLayout(right, 1)
        self.preview_frame = QFrame()
        self.preview_frame.setFrameShape(QFrame.Box)
        self.preview_frame.setFixedSize(320, 240)

        self.preview_label = QLabel("Нет предпросмотра", self.preview_frame)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setGeometry(0, 0, 320, 240)
        self.preview_label.setScaledContents(True)

        right.addWidget(self.preview_frame, alignment=Qt.AlignTop)

        self.meta_label = QLabel("Нет выбранного файла")
        self.meta_label.setWordWrap(True)
        right.addWidget(self.meta_label)

        # Progress + status
        bottom = QHBoxLayout()
        root.addLayout(bottom)
        self.progress = QProgressBar()
        bottom.addWidget(self.progress, 1)
        self.status = QStatusBar()
        bottom.addWidget(self.status, 1)

        # connections
        self.table.selectionModel().selectionChanged.connect(self._on_row_selected)
        self.btn_start.clicked.connect(self._start_scan)
        self.btn_cancel.clicked.connect(self._cancel_scan)
        self.btn_export.clicked.connect(self._export_csv)

    def _connect_signals(self):
        self.forwarder = SignalForwarder()
        self.forwarder.item_signal.connect(self._on_item_received)
        self.forwarder.progress_signal.connect(self._on_progress)
        self.forwarder.finished_signal.connect(self._on_finished)

        self.filter_format.textChanged.connect(lambda text: self._apply_filter())
        self.filter_depth.textChanged.connect(lambda text: self._apply_filter())
        self.filter_error.textChanged.connect(lambda text: self._apply_filter())

    def _browse_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Выберите папку для сканирования")
        if d:
            self.folder_edit.setText(d)

    def _start_scan(self):
        folder = self.folder_edit.text().strip()
        if not folder:
            QMessageBox.warning(self, "Папка не выбрана", "Выберите папку с изображениями.")
            return
        p = Path(folder)
        if not p.exists() or not p.is_dir():
            QMessageBox.warning(self, "Некорректная папка", "Указанная папка не существует.")
            return

        # clear model
        self.model.removeRows(0, self.model.rowCount())
        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_export.setEnabled(False)
        self.status.showMessage("Запуск сканирования...")

        # setup emitter and forward callbacks to Qt signals
        emitter = ScanEmitter()
        self.scanner_emitter = emitter
        emitter.on_item = lambda item: self.forwarder.item_signal.emit(item)
        emitter.on_progress = lambda a, b: self.forwarder.progress_signal.emit(a, b)
        emitter.on_finished = lambda: self.forwarder.finished_signal.emit()

        # run scan in a thread to avoid blocking GUI
        thread = threading.Thread(target=scan_folder, args=(folder, emitter, 8), daemon=True)
        self.scan_thread = thread
        thread.start()

    def _cancel_scan(self):
        if self.scanner_emitter:
            self.scanner_emitter.cancel()
            self.status.showMessage("Отмена запускается...")
            self.btn_cancel.setEnabled(False)

    def _apply_filter(self):
        fmt = self.filter_format.text().strip()
        depth = self.filter_depth.text().strip()
        err = self.filter_error.text().strip()

        regex_parts = []
        if fmt:
            regex_parts.append(f"(?=.*{fmt})")
        if depth:
            regex_parts.append(f"(?=.*{depth})")
        if err:
            regex_parts.append(f"(?=.*{err})")

        if regex_parts:
            regex = "".join(regex_parts)
            self.proxy.setFilterRegularExpression(QRegularExpression(regex, QRegularExpression.CaseInsensitiveOption))
        else:
            self.proxy.setFilterRegularExpression(QRegularExpression())

    def _on_item_received(self, item: dict):
        row = []
        fname = item.get("filename", item.get("path", ""))
        row.append(QStandardItem(fname))
        row.append(QStandardItem(safe_str(item.get("format"))))

        w, h = item.get("width"), item.get("height")
        size_text = f"{safe_str(w)}×{safe_str(h)}" if w and h else ""
        row.append(QStandardItem(size_text))

        dx, dy = item.get("dpi_x"), item.get("dpi_y")
        dpi_text = f"{safe_float(dx)}×{safe_float(dy)}" if dx and dy else ""
        row.append(QStandardItem(dpi_text))

        row.append(QStandardItem(safe_str(item.get("depth"))))
        row.append(QStandardItem(safe_str(item.get("compression"))))
        row.append(QStandardItem(item.get("error", "")))
        # additional summary
        add = item.get("additional", {})
        add_summary = ", ".join(f"{k}:{v}" for k, v in list(add.items())[:3]) if add else ""
        row.append(QStandardItem(add_summary))

        self.model.appendRow(row)
        index = (self.model.rowCount() - 1, 0)
        self.model.item(index[0], 0).setData(item, Qt.UserRole + 1)
        self.btn_export.setEnabled(True)

    def _on_progress(self, processed: int, total: int):
        if total:
            val = int(processed * 100 / total)
            self.progress.setValue(val)
            self.status.showMessage(f"Обработано {processed}/{total}")
        else:
            self.progress.setValue(0)

    def _on_finished(self):
        self.status.showMessage("Сканирование завершено.")
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    def _on_row_selected(self, selected, deselected):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            self.preview_label.setText("Нет предпросмотра")
            self.preview_label.setPixmap(QPixmap())
            self.meta_label.setText("Нет выбранного файла")
            return

        idx = indexes[0].row()
        src_idx = self.proxy.mapToSource(self.proxy.index(idx, 0))
        item = self.model.item(src_idx.row(), 0).data(Qt.UserRole + 1)
        if not item:
            return

        path = item.get("path")
        pix = None  
        try:
            with Image.open(path) as im:
                im.thumbnail((300, 220))
                im_rgba = im.convert("RGBA")
                data = im_rgba.tobytes("raw", "RGBA")
                qimg = QImage(data, im_rgba.width, im_rgba.height, QImage.Format_RGBA8888)
                pix = QPixmap.fromImage(qimg)
        except Exception as e:
            print("Ошибка предпросмотра:", e)

        if pix and not pix.isNull():
            pix = pix.scaled(
                self.preview_label.width(),
                self.preview_label.height(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.preview_label.setPixmap(pix)
            self.preview_label.setText("")
        else:
            self.preview_label.setText("Нет предпросмотра")
            self.preview_label.setPixmap(QPixmap())

        # metadata
        lines = [f"Файл: {item.get('filename')}", f"Формат: {item.get('format')}"]
        w, h = item.get("width"), item.get("height")
        if w and h:
            lines.append(f"Размер: {w} × {h} px")
        dx, dy = item.get("dpi_x"), item.get("dpi_y")
        if dx and dy:
            try:
                dx_val, dy_val = float(dx), float(dy)
                lines.append(f"DPI: {dx_val:.1f} × {dy_val:.1f}")
            except Exception:
                lines.append(f"DPI: {dx} × {dy}")
        lines.append(f"Глубина: {item.get('depth')} бит")
        lines.append(f"Сжатие: {item.get('compression')}")
        if item.get("error"):
            lines.append(f"Ошибка: {item.get('error')}")
        add = item.get("additional", {})
        if add:
            lines.append("Дополнительно:")
            for k, v in add.items():
                lines.append(f"  {k}: {v}")
        self.meta_label.setText("\n".join(lines))


    def _export_csv(self):
        if self.model.rowCount() == 0:
            QMessageBox.information(self, "Нет данных", "Таблица пуста — нечего экспортировать.")
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Сохранить CSV", filter="CSV files (*.csv)")
        if not fn:
            return
        try:
            with open(fn, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                headers = [self.model.headerData(i, Qt.Horizontal) for i in range(self.model.columnCount())]
                writer.writerow(headers)
                for r in range(self.model.rowCount()):
                    row = []
                    for c in range(self.model.columnCount()):
                        it = self.model.item(r, c)
                        row.append(it.text() if it is not None else "")
                    writer.writerow(row)
            QMessageBox.information(self, "Экспорт завершён", f"CSV сохранён: {fn}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить CSV:\n{e}")

def safe_float(val, ndigits=1):
    try:
        return f"{float(val):.{ndigits}f}"
    except Exception:
        return str(val) if val is not None else ""

def safe_str(val):
    try:
        return str(val) if val is not None else ""
    except Exception:
        return ""
           

def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
