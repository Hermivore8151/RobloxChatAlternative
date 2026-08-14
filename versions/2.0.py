"""
2.0
- Switched to PyQT6
- Fixed a votekick bug
"""
import sys
import threading
import queue
import json
import time
import re
import os
from pathlib import Path

try:
    import httpx
except ImportError as e:
    input(str(e))
    sys.exit(1)

try:
    import websockets.sync.client as ws_sync
    import websockets.exceptions
except ImportError as e:
    input(str(e))
    sys.exit(1)

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTextEdit, QLineEdit, QPushButton, 
                             QLabel, QFrame, QDialog, QFormLayout, QCheckBox, 
                             QFileDialog, QListWidget, QInputDialog)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QPalette, QColor

# region config

CONFIG_FILE = Path.home() / ".roblox_chat_config.json"
TOKEN_FILE_DEFAULT = Path.home() / ".roblox_chat_token"
CHALLENGE_TTL = 60

DEFAULT_CONFIG = {
    "hide_unverified": False,
    "blocked_users": [],
    "log_dir_override": "",
    "token_file_override": "",
    "join_marker": "[flog::output] ! joining game",
    "load_marker": "gamejoinloadtime"
}

def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            merged = DEFAULT_CONFIG.copy()
            merged.update(cfg)
            return merged
    except Exception:
        return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

def get_token_file(config: dict) -> Path:
    override = config.get("token_file_override")
    return Path(override) if override else TOKEN_FILE_DEFAULT

def get_log_dir(config: dict) -> Path:
    override = config.get("log_dir_override")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path.home() / "AppData/Local/Roblox/logs"
    else:
        return Path.home() / ".var/app/org.vinegarhq.Sober/data/sober/sober_logs/"

# region log parsing

_RE_UID  = re.compile(r"userid:(\d+)", re.I)
_RE_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)

def _load_stored_token(config: dict) -> dict:
    try:
        return json.loads(get_token_file(config).read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_stored_token(config: dict, user_id: int, token: str):
    stored = _load_stored_token(config)
    stored[str(user_id)] = token
    get_token_file(config).write_text(json.dumps(stored), encoding="utf-8")

def find_latest_log(config: dict) -> Path | None:
    log_dir = get_log_dir(config)
    if not log_dir.exists():
        return None
    log_files = [f for f in log_dir.glob("**/*.log") if f.is_file()]
    return max(log_files, key=lambda f: f.stat().st_mtime) if log_files else None

def parse_log_text(text: str, config: dict) -> tuple[str | None, str | None]:
    join_marker = config.get("join_marker", "[flog::output] ! joining game").lower()
    load_marker = config.get("load_marker", "gamejoinloadtime").lower()
    
    user_id = None
    server_id = None
    lines = text.split("\n")

    for i, line in enumerate(lines):
        low = line.lower()

        if join_marker in low:
            m = _RE_UUID.search(line)
            if not m and i + 1 < len(lines) and load_marker not in lines[i + 1].lower():
                m = _RE_UUID.search(lines[i + 1])
            if m:
                server_id = m.group(0).lower()

        if load_marker in low:
            m = _RE_UID.search(line)
            if m:
                user_id = m.group(1)

    return user_id, server_id

def parse_latest_log(config: dict) -> tuple[str | None, str | None]:
    path = find_latest_log(config)
    if path is None:
        return None, None
    try:
        return parse_log_text(path.read_text(errors="replace", encoding="utf-8"), config)
    except Exception:
        return None, None

# client

API_BASE = "https://hermivore.cat"
WS_BASE  = "wss://hermivore.cat"

class ChatClient:
    def __init__(self, server_id: str, user_id: int, config: dict):
        self.config = config
        self.server_id = server_id
        self.user_id = user_id
        self.name: str | None = None
        self.room_id: str | None = None
        self.token: str | None = None
        self.verified = False
        self.verify_code: str | None = None

        self._ws = None
        self._send_queue: queue.Queue = queue.Queue()
        self._recv_queue: queue.Queue = queue.Queue()

        self._running = False
        self._ws_thread: threading.Thread | None = None
        self._send_thread: threading.Thread | None = None
        self._watcher_thread: threading.Thread | None = None

        stored = _load_stored_token(self.config)
        self.client_token = stored.get(str(user_id))

    def connect(self) -> bool:
        data = self._handshake(client_token=self.client_token)
        if data is None:
            return False

        self.verified    = data.get("verified", False)
        self.verify_code = data.get("verify_code")

        if "client_token" in data:
            self.client_token = data["client_token"]
            _save_stored_token(self.config, self.user_id, self.client_token)

        self.name    = data["name"]
        self.room_id = data["room_id"]
        self.token   = data["ws_token"]

        url = (
            f"{WS_BASE}/api/roblox/chat/room/{self.room_id}"
            f"?token={self.token}&user_id={self.user_id}"
            f"&name={self.name}&verified={int(self.verified)}"
        )
        try:
            self._ws = ws_sync.connect(url)
        except Exception as e:
            print(f"WS connect failed: {e}")
            return False

        self._running = True
        self._ws_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._watcher_thread = threading.Thread(target=self._watch_logs, daemon=True)
        self._ws_thread.start()
        self._send_thread.start()
        self._watcher_thread.start()
        return True

    def _reconnect(self, retries: int = 5, backoff: float = 2.0):
        for attempt in range(1, retries + 1):
            time.sleep(backoff * attempt)
            try: self._ws.close()
            except Exception: pass

            data = self._handshake(client_token=self.client_token)
            if data is None or data.get("error"):
                continue

            if "client_token" in data:
                self.client_token = data["client_token"]
                _save_stored_token(self.config, self.user_id, self.client_token)

            self.name      = data["name"]
            self.room_id   = data["room_id"]
            self.token     = data["ws_token"]
            self.verified  = data.get("verified", False)
            self.verify_code = data.get("verify_code")

            try:
                url = (
                    f"{WS_BASE}/api/roblox/chat/room/{self.room_id}"
                    f"?token={self.token}&user_id={self.user_id}"
                    f"&name={self.name}"
                )
                self._ws = ws_sync.connect(url)
            except Exception:
                continue

            self._recv_queue.put({"type": "system", "text": "Reconnected", "ts": time.time()})
            self._recv_loop()
            return

        self._running = False
        self._recv_queue.put({"type": "system", "text": "Disconnected (retries exhausted)", "ts": time.time()})

    def _handshake(self, client_token=None, action=None) -> dict | None:
        body = {"user_id": self.user_id}
        if client_token: body["client_token"] = client_token
        if action: body["action"] = action

        try:
            resp = httpx.post(f"{API_BASE}/api/roblox/chat/{self.server_id}", json=body, timeout=10)
            return resp.json()
        except Exception as e:
            print(f"Handshake failed: {e}")
            return None

    def _watch_logs(self, interval: float = 3.0):
        last_path: Path | None = None
        last_size: int = 0

        while self._running:
            time.sleep(interval)
            path = find_latest_log(self.config)
            if path is None: continue

            try: size = path.stat().st_size
            except OSError: continue

            if path == last_path and size == last_size: continue

            last_path = path
            last_size = size

            try: text = path.read_text(errors="replace", encoding="utf-8")
            except Exception: continue

            new_uid, new_sid = parse_log_text(text, self.config)
            if new_sid is None or new_sid == self.server_id: continue

            print(f"Server change: {self.server_id} → {new_sid}")
            if new_uid and new_uid != str(self.user_id):
                self.user_id = int(new_uid)
                stored = _load_stored_token(self.config)
                self.client_token = stored.get(str(self.user_id))
                print(f"Account change: user_id → {self.user_id}")

            self.server_id = new_sid
            self._recv_queue.put({"type": "clear"})
            self._recv_queue.put({"type": "system", "text": "Switching server…", "ts": time.time()})
            try: self._ws.close()
            except Exception: pass

    def _recv_loop(self):
        while self._running:
            try: raw = self._ws.recv(timeout=60)
            except TimeoutError: continue
            except websockets.exceptions.ConnectionClosed: break
            except Exception: break

            try:
                msg = json.loads(raw)
                self._recv_queue.put(msg)
            except json.JSONDecodeError: continue

        if self._running:
            self._recv_queue.put({"type": "system", "text": "Reconnecting…", "ts": time.time()})
            self._reconnect()

    def _send_loop(self):
        while self._running:
            try: item = self._send_queue.get(timeout=1)
            except queue.Empty: continue
            try:
                if isinstance(item, str): self._ws.send(json.dumps({"type": "text", "text": item}))
                else: self._ws.send(json.dumps(item))
            except Exception: pass

    def send(self, text: str):
        if self._running: self._send_queue.put(text)

    def send_raw(self, payload: dict):
        if self._running: self._send_queue.put(payload)

    def poll(self) -> list[dict]:
        msgs = []
        while not self._recv_queue.empty():
            try: msgs.append(self._recv_queue.get_nowait())
            except queue.Empty: break
        return msgs

    def disconnect(self):
        self._running = False
        if self._ws:
            try: self._ws.close()
            except Exception: pass

# region UI

class VerifyWorker(QObject):
    finished = pyqtSignal(bool)
    def __init__(self, client):
        super().__init__()
        self.client = client
    def run(self):
        data = self.client._handshake(action="verify")
        if data and data.get("client_token"):
            self.client.client_token = data["client_token"]
            self.client.verified = True
            _save_stored_token(self.client.config, self.client.user_id, data["client_token"])
            try: self.client._ws.close()
            except Exception: pass
            self.finished.emit(True)
        else:
            self.finished.emit(False)

class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Settings")
        self.resize(400, 350)
        
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.hide_unverified_cb = QCheckBox("Hide unverified users")
        self.hide_unverified_cb.setChecked(config.get("hide_unverified", False))
        form.addRow(self.hide_unverified_cb)
        
        self.blocked_list = QListWidget()
        self.blocked_list.addItems(config.get("blocked_users", []))
        form.addRow("Blocked Users:", self.blocked_list)
        
        btn_layout = QHBoxLayout()
        self.add_block_btn = QPushButton("Add")
        self.add_block_btn.clicked.connect(self.add_blocked_user)
        self.remove_block_btn = QPushButton("Remove")
        self.remove_block_btn.clicked.connect(self.remove_blocked_user)
        btn_layout.addWidget(self.add_block_btn)
        btn_layout.addWidget(self.remove_block_btn)
        form.addRow("", btn_layout)
        
        self.log_dir_edit = QLineEdit(config.get("log_dir_override", ""))
        self.log_dir_btn = QPushButton("Browse")
        self.log_dir_btn.clicked.connect(self.browse_log_dir)
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(self.log_dir_edit)
        dir_layout.addWidget(self.log_dir_btn)
        form.addRow("Log Dir Override:", dir_layout)
        
        self.token_file_edit = QLineEdit(config.get("token_file_override", ""))
        self.token_file_btn = QPushButton("Browse")
        self.token_file_btn.clicked.connect(self.browse_token_file)
        token_layout = QHBoxLayout()
        token_layout.addWidget(self.token_file_edit)
        token_layout.addWidget(self.token_file_btn)
        form.addRow("Token File Override:", token_layout)
        
        self.join_marker_edit = QLineEdit(config.get("join_marker", "[flog::output] ! joining game"))
        form.addRow("Join Marker:", self.join_marker_edit)
        
        self.load_marker_edit = QLineEdit(config.get("load_marker", "gamejoinloadtime"))
        form.addRow("Load Marker:", self.load_marker_edit)
        
        layout.addLayout(form)
        
        btn_box = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_and_close)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addStretch()
        btn_box.addWidget(save_btn)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)
        
    def add_blocked_user(self):
        name, ok = QInputDialog.getText(self, "Block User", "Enter username or ID:")
        if ok and name.strip():
            self.blocked_list.addItem(name.strip())
            
    def remove_blocked_user(self):
        current = self.blocked_list.currentRow()
        if current >= 0:
            self.blocked_list.takeItem(current)
            
    def browse_log_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Log Directory")
        if dir_path: self.log_dir_edit.setText(dir_path)
            
    def browse_token_file(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Select Token File", "", "JSON Files (*.json)")
        if file_path: self.token_file_edit.setText(file_path)
            
    def save_and_close(self):
        self.config["hide_unverified"] = self.hide_unverified_cb.isChecked()
        self.config["blocked_users"] = [self.blocked_list.item(i).text() for i in range(self.blocked_list.count())]
        self.config["log_dir_override"] = self.log_dir_edit.text().strip()
        self.config["token_file_override"] = self.token_file_edit.text().strip()
        self.config["join_marker"] = self.join_marker_edit.text().strip()
        self.config["load_marker"] = self.load_marker_edit.text().strip()
        save_config(self.config)
        self.accept()

class ChatWindow(QMainWindow):
    def __init__(self, client: ChatClient, config: dict):
        super().__init__()
        self.client = client
        self.config = config
        
        self.setWindowTitle("Roblox Chat Overlay")
        self.resize(580, 450)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        
        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(8, 8, 8, 8)
        self.main_layout.setSpacing(4)
        
        self.banner = QLabel()
        self.banner.setStyleSheet("background-color: #45475a; color: #f9e2af; padding: 4px; font-family: Consolas;")
        self.banner.hide()
        self.main_layout.addWidget(self.banner)
        
        self.vk_frame = QFrame()
        self.vk_frame.setStyleSheet("background-color: #45475a; padding: 4px; font-family: Consolas;")
        self.vk_layout = QVBoxLayout(self.vk_frame)
        self.vk_info = QLabel()
        self.vk_info.setStyleSheet("color: #fab387; font-weight: bold;")
        self.vk_status = QLabel()
        self.vk_status.setStyleSheet("color: #f9e2af;")
        
        vk_btn_layout = QHBoxLayout()
        self.vk_vote_btn = QPushButton("Vote Yes")
        self.vk_vote_btn.setStyleSheet("background-color: #f38ba8; color: #1e1e2e; font-weight: bold;")
        self.vk_timer_label = QLabel()
        self.vk_timer_label.setStyleSheet("color: #a6adc8;")
        vk_btn_layout.addWidget(self.vk_vote_btn)
        vk_btn_layout.addStretch()
        vk_btn_layout.addWidget(self.vk_timer_label)
        
        self.vk_layout.addWidget(self.vk_info)
        self.vk_layout.addWidget(self.vk_status)
        self.vk_layout.addLayout(vk_btn_layout)
        self.vk_frame.hide()
        self.main_layout.addWidget(self.vk_frame)
        
        self.display = QTextEdit()
        self.display.setReadOnly(True)
        self.display.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: Consolas;
                font-size: 10pt;
                border: none;
            }
        """)
        self.main_layout.addWidget(self.display, 1)
        
        input_layout = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setStyleSheet("""
            QLineEdit {
                background-color: #313244;
                color: #cdd6f4;
                font-family: Consolas;
                font-size: 10pt;
                border: none;
                padding: 4px;
            }
        """)
        self.entry.returnPressed.connect(self.on_send)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #89b4fa;
                color: #1e1e2e;
                font-family: Consolas;
                font-weight: bold;
                border: none;
                padding: 4px 8px;
            }
            QPushButton:hover { background-color: #74c7ec; }
        """)
        self.send_btn.clicked.connect(self.on_send)
        
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedWidth(30)
        self.settings_btn.clicked.connect(self.open_settings)
        
        input_layout.addWidget(self.entry, 1)
        input_layout.addWidget(self.send_btn)
        input_layout.addWidget(self.settings_btn)
        self.main_layout.addLayout(input_layout)
        
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_messages)
        self.poll_timer.start(50)
        
        self.banner_timer = QTimer()
        self.banner_timer.timeout.connect(self.tick_banners)
        self.banner_timer.start(1000)
        
        self.apply_theme()
        self.init_banners()

    def apply_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 46))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(205, 214, 244))
        palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 46))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(49, 50, 68))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(205, 214, 244))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(205, 214, 244))
        palette.setColor(QPalette.ColorRole.Text, QColor(205, 214, 244))
        palette.setColor(QPalette.ColorRole.Button, QColor(49, 50, 68))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(205, 214, 244))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(243, 139, 168))
        palette.setColor(QPalette.ColorRole.Link, QColor(137, 180, 250))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(137, 180, 250))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(30, 30, 46))
        QApplication.instance().setPalette(palette)

    def init_banners(self):
        if not self.client.verified and self.client.verify_code:
            self.banner_deadline = time.time() + CHALLENGE_TTL
            self.banner.setText(f"Unverified — add to bio, in order: {self.client.verify_code}")
            self.banner.show()
        else:
            self.banner_deadline = None
            self.banner.hide()
            
        self.vk_deadline = None
        self.vk_target = None

    def tick_banners(self):
        if self.banner.isVisible() and self.banner_deadline:
            remaining = self.banner_deadline - time.time()
            if remaining > 0:
                mins, secs = divmod(int(remaining), 60)
                self.banner.setText(f"Unverified — add to bio, in order: {self.client.verify_code}  ({mins}:{secs:02d})")
            else:
                self.banner.setText("Verifying...")
                self.banner_timer.stop()
                self.verify_thread = QThread()
                self.verify_worker = VerifyWorker(self.client)
                self.verify_worker.moveToThread(self.verify_thread)
                self.verify_thread.started.connect(self.verify_worker.run)
                self.verify_worker.finished.connect(self.on_verify_finished)
                self.verify_thread.start()
                
        if self.vk_frame.isVisible() and self.vk_deadline:
            remaining = self.vk_deadline - time.time()
            if remaining > 0:
                self.vk_timer_label.setText(f"{int(remaining)}s")
            else:
                self.vk_timer_label.setText("0s")
                self.resolve_votekick({"result": "expired", "target": self.vk_target})

    def on_verify_finished(self, success):
        self.verify_thread.quit()
        self.verify_thread.wait()
        self.banner_timer.start()
        
        if success:
            self.banner.setText("Verified ✓ Reconnecting...")
            self.banner.setStyleSheet("background-color: #45475a; color: #a6e3a1; padding: 4px; font-family: Consolas;")
            QTimer.singleShot(3000, self.banner.hide)
        else:
            self.banner.setText("Verification expired — reconnect to try again")
            self.banner.setStyleSheet("background-color: #45475a; color: #f38ba8; padding: 4px; font-family: Consolas;")
            QTimer.singleShot(5000, self.banner.hide)

    def poll_messages(self):
        msgs = self.client.poll()
        for msg in msgs:
            self.handle_message(msg)
            
    def handle_message(self, msg):
        mtype = msg.get("type")
        
        if mtype == "chat":
            sender = msg.get("name", "")
            sender_id = str(msg.get("user_id", ""))
            is_verified = msg.get("verified", False)
            
            if self.config.get("hide_unverified") and not is_verified:
                return
                
            if sender in self.config.get("blocked_users", []) or sender_id in self.config.get("blocked_users", []):
                return
                
            ts = time.strftime("%H:%M", time.localtime(msg.get("ts", 0)))
            verified_badge = " <span style='color:#a6e3a1; font-weight:bold;'>✓</span>" if is_verified else ""
            text = msg.get("text", "").replace("<", "&lt;").replace(">", "&gt;")
            html = f"<span style='color:#a6adc8;'>[{ts}]</span> <span style='color:#89b4fa; font-weight:bold;'>{sender}</span>{verified_badge}: {text}"
            self.display.append(html)
            
        elif mtype == "system":
            text = msg.get("text", "").replace("<", "&lt;").replace(">", "&gt;")
            html = f"<span style='color:#a6adc8; font-style:italic;'>  {text}</span>"
            self.display.append(html)
            
        elif mtype == "error":
            text = msg.get("text", "").replace("<", "&lt;").replace(">", "&gt;")
            html = f"<span style='color:#f38ba8;'>  ⚠ {text}</span>"
            self.display.append(html)
            
        elif mtype == "clear":
            self.display.clear()
            
        elif mtype == "history":
            for m in msg.get("messages", []):
                self.handle_message(m)
                
        elif mtype == "votekick_init":
            self.show_votekick(msg)
            
        elif mtype == "votekick_update":
            self.update_votekick(msg)
            
        elif mtype == "votekick_result":
            self.resolve_votekick(msg)

    def show_votekick(self, msg):
        target = msg.get("target", "?")
        self.vk_target = target.lower()
        self.vk_deadline = msg.get("deadline", time.time() + 60)
        
        initiator = msg.get("initiator", "?")
        reason = msg.get("reason")
        votes = msg.get("votes", 0)
        needed = msg.get("needed", 3)
        
        reason_text = f' for "{reason}"' if reason else ""
        info = f'{initiator} initiated a votekick on {target}{reason_text}'
        instruction = f"Votes: {votes}/{needed}  —  /votekick {target} to vote"
        
        self.vk_info.setText(info)
        self.vk_status.setText(instruction)
        self.vk_vote_btn.setEnabled(True)
        try: self.vk_vote_btn.clicked.disconnect()
        except TypeError: pass
        self.vk_vote_btn.clicked.connect(lambda: self.client.send_raw({
            "type": "votekick_vote", "target_name": target
        }))
        self.vk_frame.show()

    def update_votekick(self, msg):
        votes = msg.get("votes", 0)
        needed = msg.get("needed", 3)
        target = msg.get("target", "?")
        self.vk_status.setText(f"Votes: {votes}/{needed}  —  /votekick {target} to vote")

    def resolve_votekick(self, msg):
        result = msg.get("result")
        target = msg.get("target", "?")
        
        if result == "kicked":
            self.vk_info.setText(f"{target} was votekicked")
            self.vk_info.setStyleSheet("color: #a6e3a1; font-weight: bold;")
        else:
            self.vk_info.setText(f"Votekick on {target} expired")
            self.vk_info.setStyleSheet("color: #a6adc8; font-weight: bold;")
            
        self.vk_status.setText("")
        self.vk_vote_btn.setEnabled(False)
        
        QTimer.singleShot(4000, self.vk_frame.hide)
        self.vk_deadline = None

    def on_send(self):
        text = self.entry.text().strip()
        if not text: return
        self.entry.clear()
        
        if text.lower().startswith("/votekick"):
            self.handle_votekick(text)
            return
            
        if text.lower() == "/clear":
            self.display.clear()
            return
            
        self.client.send(text)
        
    def handle_votekick(self, text):
        parts = text.split(maxsplit=2)
        if len(parts) < 2:
            self.display.append("<span style='color:#f38ba8;'>  ⚠ Usage: /votekick &lt;name&gt; [reason]</span>")
            return
            
        target_name = parts[1]
        reason = parts[2] if len(parts) > 2 else ""
        
        if self.vk_frame.isVisible() and self.vk_target == target_name.lower():
            self.client.send_raw({"type": "votekick_vote", "target_name": target_name})
        else:
            self.client.send_raw({"type": "votekick_init", "target_name": target_name, "reason": reason})

    def open_settings(self):
        dialog = SettingsDialog(self.config, self)
        dialog.exec()

    def closeEvent(self, event):
        self.client.disconnect()
        event.accept()

# region start

if __name__ == "__main__":
    config = load_config()
    user_id, server_id = parse_latest_log(config)

    if server_id is None:
        print("No active Roblox session found. Make sure Roblox is running.")
        input("Press enter to exit.")
        sys.exit(1)

    print(f"Detected user {user_id} in server {server_id}")

    client = ChatClient(server_id, int(user_id), config)
    if not client.connect():
        print("Failed to connect.")
        input("Press enter to exit.")
        sys.exit(1)

    print(f"Connected as {client.name} → room {client.room_id}")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = ChatWindow(client, config)
    window.show()
    sys.exit(app.exec())
