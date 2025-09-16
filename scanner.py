# scanner.py
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from formats_info import inspect_image
import threading

class ScanEmitter:
    """
    Простейший emitter API: заполняется callback-ами извне.
    Используется для передачи результатов обратно в GUI thread.
    """
    def __init__(self):
        self.on_item = None      # callback(item_dict)
        self.on_progress = None  # callback(processed, total)
        self.on_finished = None  # callback()
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def cancelled(self):
        return self._cancel_event.is_set()

def scan_folder(path: str, emitter: ScanEmitter, max_workers: int = 6):
    """
    Сканирует рекурсивно папку `path` и вызывает emitter.on_item для каждого обработанного файла.
    Поддерживает простую отмену через emitter.cancel().
    """
    exts = {'.jpg', '.jpeg', '.png', '.gif', '.tif', '.tiff', '.bmp', '.pcx'}
    file_list = []
    for root, dirs, files in os.walk(path):
        for f in files:
            _, e = os.path.splitext(f)
            if e.lower() in exts:
                file_list.append(os.path.join(root, f))
    total = len(file_list)
    if emitter.on_progress:
        emitter.on_progress(0, total)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_to_path = {ex.submit(inspect_image, p): p for p in file_list}
        processed = 0
        for future in as_completed(future_to_path):
            if emitter.cancelled():
                break
            p = future_to_path[future]
            try:
                result = future.result()
            except Exception as e:
                result = {"path": p, "error": str(e)}
            processed += 1
            if emitter.on_item:
                emitter.on_item(result)
            if emitter.on_progress:
                emitter.on_progress(processed, total)
    if emitter.on_finished:
        emitter.on_finished()
