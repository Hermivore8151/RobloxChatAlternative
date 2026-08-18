from PyQt6.QtCore import pyqtSignal, QObject
import time, httpx

from config import _save_stored_token

class VerifyWorker(QObject):
    finished = pyqtSignal(bool, str)

    def __init__(self, status_url: str):
        super().__init__()
        self.status_url = status_url  # Full URL, not just session ID

    def run(self):
        while True:
            try:
                resp = httpx.get(self.status_url, timeout=10).json()
            except Exception:
                time.sleep(2)
                continue

            status = resp.get("status")
            if status == "ok":
                token = resp.get("session_token", "")
                _save_stored_token({"token_file_override": ""}, "backend_session_jwt", token)
                self.finished.emit(True, token)
                return
            elif status in ("expired", "error"):
                self.finished.emit(False, "")
                return
            else:  # pending
                time.sleep(2)