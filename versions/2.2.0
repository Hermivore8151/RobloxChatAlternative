"""
2.2
- Added compact mode
- Attempt to add resizable
"""
import sys
import threading
import queue
import json
import time
import re
import os
import html
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
                             QHBoxLayout, QLineEdit, QPushButton, QLabel, QFrame, 
                             QDialog, QCheckBox, QFileDialog, QListWidget, 
                             QInputDialog, QScrollArea, QComboBox, QSizePolicy, QSizeGrip)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QFont, QCursor

# region Config

CONFIG_FILE = Path.home() / ".roblox_chat_config.json"
TOKEN_FILE_DEFAULT = Path.home() / ".roblox_chat_token"
CHALLENGE_TTL = 60

THEMES = {
    "Dark Modern": {
        "bg": "#121212", "surface": "#1e1e1e", "surface_alt": "#2a2a2a",
        "text": "#e0e0e0", "subtext": "#888888", "accent": "#bb86fc",
        "error": "#cf6679", "unverified_bg": "#d32f2f", "unverified_text": "#ffffff",
        "border": "#333333"
    },
    "OLED Black": {
        "bg": "#000000", "surface": "#121212", "surface_alt": "#1a1a1a",
        "text": "#ffffff", "subtext": "#666666", "accent": "#03dac6",
        "error": "#cf6679", "unverified_bg": "#b71c1c", "unverified_text": "#ffffff",
        "border": "#222222"
    },
    "Light Modern": {
        "bg": "#f5f5f7", "surface": "#ffffff", "surface_alt": "#e8e8ed",
        "text": "#1d1d1f", "subtext": "#86868b", "accent": "#0071e3",
        "error": "#ff3b30", "unverified_bg": "#ff3b30", "unverified_text": "#ffffff",
        "border": "#d2d2d7"
    },
    "Catppuccin": {
        "bg": "#1e1e2e", "surface": "#313244", "surface_alt": "#45475a",
        "text": "#cdd6f4", "subtext": "#a6adc8", "accent": "#89b4fa",
        "error": "#f38ba8", "unverified_bg": "#f38ba8", "unverified_text": "#1e1e2e",
        "border": "#45475a"
    }
}

DEFAULT_CONFIG = {
    "theme": "Dark Modern",
    "hide_unverified": False,
    "compact_mode": False,
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
    if override: return Path(override)
    if os.name == "nt": return Path.home() / "AppData/Local/Roblox/logs"
    else: return Path.home() / ".var/app/org.vinegarhq.Sober/data/sober/sober_logs/"

# region Parsing

_RE_UID  = re.compile(r"userid:(\d+)", re.I)
_RE_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

def _load_stored_token(config: dict) -> dict:
    try: return json.loads(get_token_file(config).read_text(encoding="utf-8"))
    except Exception: return {}

def _save_stored_token(config: dict, user_id: int, token: str):
    stored = _load_stored_token(config)
    stored[str(user_id)] = token
    get_token_file(config).write_text(json.dumps(stored), encoding="utf-8")

def find_latest_log(config: dict) -> Path | None:
    log_dir = get_log_dir(config)
    if not log_dir.exists(): return None
    log_files = [f for f in log_dir.glob("**/*.log") if f.is_file()]
    return max(log_files, key=lambda f: f.stat().st_mtime) if log_files else None

def parse_log_text(text: str, config: dict) -> tuple[str | None, str | None]:
    join_marker = config.get("join_marker", "[flog::output] ! joining game").lower()
    load_marker = config.get("load_marker", "gamejoinloadtime").lower()
    user_id = server_id = None
    lines = text.split("\n")
    for i, line in enumerate(lines):
        low = line.lower()
        if join_marker in low:
            m = _RE_UUID.search(line)
            if not m and i + 1 < len(lines) and load_marker not in lines[i + 1].lower():
                m = _RE_UUID.search(lines[i + 1])
            if m: server_id = m.group(0).lower()
        if load_marker in low:
            m = _RE_UID.search(line)
            if m: user_id = m.group(1)
    return user_id, server_id

def parse_latest_log(config: dict) -> tuple[str | None, str | None]:
    path = find_latest_log(config)
    if path is None: return None, None
    try: return parse_log_text(path.read_text(errors="replace", encoding="utf-8"), config)
    except Exception: return None, None

# region Client

API_BASE = "https://hermivore.cat"
WS_BASE  = "wss://hermivore.cat"

class ChatClient:
    def __init__(self, server_id: str, user_id: int, config: dict):
        self.config = config
        self.server_id = server_id
        self.user_id = user_id
        self.name = self.room_id = self.token = self.verify_code = None
        self.verified = False
        self._ws = None
        self._send_queue = queue.Queue()
        self._recv_queue = queue.Queue()
        self._running = False
        self._ws_thread = self._send_thread = self._watcher_thread = None
        stored = _load_stored_token(self.config)
        self.client_token = stored.get(str(user_id))

    def connect(self) -> bool:
        data = self._handshake(client_token=self.client_token)
        if data is None: return False
        self.verified = data.get("verified", False)
        self.verify_code = data.get("verify_code")
        if "client_token" in data:
            self.client_token = data["client_token"]
            _save_stored_token(self.config, self.user_id, self.client_token)
        self.name, self.room_id, self.token = data["name"], data["room_id"], data["ws_token"]
        url = f"{WS_BASE}/api/roblox/chat/room/{self.room_id}?token={self.token}&user_id={self.user_id}&name={self.name}&verified={int(self.verified)}"
        try: self._ws = ws_sync.connect(url)
        except Exception as e: return False
        self._running = True
        self._ws_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._watcher_thread = threading.Thread(target=self._watch_logs, daemon=True)
        self._ws_thread.start(), self._send_thread.start(), self._watcher_thread.start()
        return True

    def _reconnect(self, retries: int = 5, backoff: float = 2.0):
        for attempt in range(1, retries + 1):
            time.sleep(backoff * attempt)
            try: self._ws.close()
            except Exception: pass
            data = self._handshake(client_token=self.client_token)
            if data is None or data.get("error"): continue
            if "client_token" in data:
                self.client_token = data["client_token"]
                _save_stored_token(self.config, self.user_id, self.client_token)
            self.name, self.room_id, self.token = data["name"], data["room_id"], data["ws_token"]
            self.verified, self.verify_code = data.get("verified", False), data.get("verify_code")
            try: self._ws = ws_sync.connect(f"{WS_BASE}/api/roblox/chat/room/{self.room_id}?token={self.token}&user_id={self.user_id}&name={self.name}")
            except Exception: continue
            self._recv_queue.put({"type": "system", "text": "Reconnected", "ts": time.time()})
            self._recv_loop()
            return
        self._running = False
        self._recv_queue.put({"type": "system", "text": "Disconnected", "ts": time.time()})

    def _handshake(self, client_token=None, action=None) -> dict | None:
        body = {"user_id": self.user_id}
        if client_token: body["client_token"] = client_token
        if action: body["action"] = action
        try: return httpx.post(f"{API_BASE}/api/roblox/chat/{self.server_id}", json=body, timeout=10).json()
        except Exception: return None

    def _watch_logs(self, interval: float = 3.0):
        last_path = last_size = None
        while self._running:
            time.sleep(interval)
            path = find_latest_log(self.config)
            if path is None: continue
            try: size = path.stat().st_size
            except OSError: continue
            if path == last_path and size == last_size: continue
            last_path, last_size = path, size
            try: text = path.read_text(errors="replace", encoding="utf-8")
            except Exception: continue
            new_uid, new_sid = parse_log_text(text, self.config)
            if new_sid is None or new_sid == self.server_id: continue
            if new_uid and new_uid != str(self.user_id):
                self.user_id = int(new_uid)
                self.client_token = _load_stored_token(self.config).get(str(self.user_id))
            self.server_id = new_sid
            self._recv_queue.put({"type": "clear"})
            self._recv_queue.put({"type": "system", "text": "Switching server…", "ts": time.time()})
            try: self._ws.close()
            except Exception: pass

    def _recv_loop(self):
        while self._running:
            try: raw = self._ws.recv(timeout=60)
            except TimeoutError: continue
            except Exception: break
            try: self._recv_queue.put(json.loads(raw))
            except json.JSONDecodeError: continue
        if self._running:
            self._recv_queue.put({"type": "system", "text": "Reconnecting…", "ts": time.time()})
            self._reconnect()

    def _send_loop(self):
        while self._running:
            try: item = self._send_queue.get(timeout=1)
            except queue.Empty: continue
            try: self._ws.send(json.dumps({"type": "text", "text": item} if isinstance(item, str) else item))
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

# region UI Components

class ChatMessageWidget(QWidget):
    def __init__(self, theme, msg, config):
        super().__init__()
        self.theme = theme
        self.config = config
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        mtype = msg.get("type")
        if mtype == "chat": self.setup_chat(msg)
        elif mtype == "system": self.setup_system(msg)
        elif mtype == "error": self.setup_error(msg)
        else: self.hide()

    def setup_chat(self, msg):
        sender = html.escape(msg.get("name", ""))
        text = html.escape(msg.get("text", ""))
        is_verified = msg.get("verified", False)
        ts = time.strftime("%H:%M", time.localtime(msg.get("ts", 0)))
        
        if self.config.get("compact_mode"):
            if not is_verified:
                name_html = f"<span style='background-color: {self.theme['unverified_bg']}; color: {self.theme['unverified_text']}; padding: 1px 6px; border-radius: 4px; font-weight: bold; font-size: 12px;'>{sender}</span>"
            else:
                name_html = f"<span style='color: {self.theme['accent']}; font-weight: bold; font-size: 12px;'>{sender}</span>"
                
            html_str = (
                f"<span style='color: {self.theme['subtext']}; font-size: 11px;'>[{ts}]</span> "
                f"{name_html} "
                f"<span style='color: {self.theme['text']}; font-size: 13px;'>{text}</span>"
            )
            lbl = QLabel(html_str)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            
            bubble = QFrame()
            bubble.setStyleSheet(f"QFrame {{ background-color: {self.theme['surface']}; border-radius: 8px; }}")
            b_layout = QVBoxLayout(bubble)
            b_layout.setContentsMargins(10, 6, 10, 8)
            b_layout.addWidget(lbl)
            self.main_layout.addWidget(bubble)
        else:
            bubble = QFrame()
            bubble.setStyleSheet(f"QFrame {{ background-color: {self.theme['surface']}; border-radius: 12px; }}")
            bubble_layout = QVBoxLayout(bubble)
            bubble_layout.setContentsMargins(14, 10, 14, 12)
            bubble_layout.setSpacing(6)
            
            header_layout = QHBoxLayout()
            header_layout.setSpacing(8)
            
            time_lbl = QLabel(ts)
            time_lbl.setStyleSheet(f"color: {self.theme['subtext']}; font-size: 11px; background: transparent;")
            
            user_lbl = QLabel(sender)
            if not is_verified:
                user_lbl.setStyleSheet(f"""
                    background-color: {self.theme['unverified_bg']}; 
                    color: {self.theme['unverified_text']}; 
                    padding: 2px 8px; border-radius: 6px; 
                    font-weight: bold; font-size: 12px;
                """)
            else:
                user_lbl.setStyleSheet(f"color: {self.theme['accent']}; font-weight: bold; font-size: 12px; background: transparent;")
                
            header_layout.addWidget(time_lbl)
            header_layout.addWidget(user_lbl)
            header_layout.addStretch()
            
            text_lbl = QLabel(text)
            text_lbl.setWordWrap(True)
            text_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text_lbl.setStyleSheet(f"color: {self.theme['text']}; font-size: 13px; background: transparent;")
            
            bubble_layout.addLayout(header_layout)
            bubble_layout.addWidget(text_lbl)
            self.main_layout.addWidget(bubble)
        
    def setup_system(self, msg):
        lbl = QLabel(html.escape(msg.get("text", "")))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {self.theme['subtext']}; font-style: italic; font-size: 11px; padding: 4px; background: transparent;")
        self.main_layout.addWidget(lbl)
        
    def setup_error(self, msg):
        bubble = QFrame()
        bubble.setStyleSheet(f"QFrame {{ background-color: rgba(255, 50, 50, 0.1); border: 1px solid {self.theme['error']}; border-radius: 8px; }}")
        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(10, 6, 10, 6)
        lbl = QLabel(f"⚠ {html.escape(msg.get('text', ''))}")
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {self.theme['error']}; font-size: 12px; background: transparent;")
        layout.addWidget(lbl)
        self.main_layout.addWidget(bubble)

class ChatScrollArea(QScrollArea):
    def __init__(self, theme):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(f"""
            QScrollArea {{ border: none; background-color: {theme['bg']}; }}
            QScrollBar:vertical {{ border: none; background: {theme['bg']}; width: 10px; margin: 0px; }}
            QScrollBar::handle:vertical {{ background: {theme['surface_alt']}; min-height: 20px; border-radius: 5px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        """)
        self.container = QWidget()
        self.container.setStyleSheet(f"background-color: {theme['bg']};")
        self.container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(8)
        self.layout.addStretch(1) # Pushes messages to bottom
        self.setWidget(self.container)
        
    def add_message(self, msg, theme, config):
        mtype = msg.get("type")
        if mtype == "chat":
            sender = msg.get("name", "")
            sender_id = str(msg.get("user_id", ""))
            is_verified = msg.get("verified", False)
            if config.get("hide_unverified") and not is_verified: return
            if sender in config.get("blocked_users", []) or sender_id in config.get("blocked_users", []): return
                
        widget = ChatMessageWidget(theme, msg, config)
        self.layout.addWidget(widget)
        QTimer.singleShot(10, self.scroll_to_bottom)
        
    def clear_messages(self):
        while self.layout.count() > 1:
            item = self.layout.takeAt(1)
            if item.widget(): item.widget().deleteLater()
                
    def scroll_to_bottom(self):
        vbar = self.verticalScrollBar()
        vbar.setValue(vbar.maximum())

class VerifyBanner(QFrame):
    def __init__(self, theme):
        super().__init__()
        self.setStyleSheet(f"QFrame {{ background-color: {theme['surface_alt']}; border-radius: 10px; }} QLabel {{ color: {theme['accent']}; font-weight: bold; background: transparent; font-size: 12px; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        self.lbl = QLabel()
        layout.addWidget(self.lbl)

class VotekickWidget(QFrame):
    vote_clicked = pyqtSignal(str)
    def __init__(self, theme):
        super().__init__()
        self.target = ""
        self.deadline = 0
        self.setStyleSheet(f"""
            QFrame {{ background-color: {theme['surface']}; border: 1px solid {theme['border']}; border-radius: 12px; }}
            QLabel {{ background: transparent; }}
            QPushButton {{ background-color: {theme['error']}; color: white; border: none; border-radius: 6px; padding: 6px 16px; font-weight: bold; font-size: 12px; }}
            QPushButton:hover {{ opacity: 0.9; }} QPushButton:disabled {{ background-color: {theme['subtext']}; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        
        self.info_lbl = QLabel()
        self.info_lbl.setStyleSheet(f"color: {theme['text']}; font-weight: bold; font-size: 13px;")
        self.info_lbl.setWordWrap(True)
        
        self.status_lbl = QLabel()
        self.status_lbl.setStyleSheet(f"color: {theme['subtext']}; font-size: 12px;")
        self.status_lbl.setWordWrap(True)
        
        btn_layout = QHBoxLayout()
        self.vote_btn = QPushButton("Vote to Kick")
        self.vote_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.vote_btn.clicked.connect(self.on_vote)
        self.timer_lbl = QLabel()
        self.timer_lbl.setStyleSheet(f"color: {theme['accent']}; font-weight: bold; font-size: 14px;")
        
        btn_layout.addWidget(self.vote_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.timer_lbl)
        
        layout.addWidget(self.info_lbl)
        layout.addWidget(self.status_lbl)
        layout.addLayout(btn_layout)
        
    def on_vote(self): self.vote_clicked.emit(self.target)

class TitleBar(QWidget):
    def __init__(self, parent_window, theme):
        super().__init__()
        self.parent_window = parent_window
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        
        title_lbl = QLabel("Roblox Chat")
        title_lbl.setStyleSheet(f"color: {theme['text']}; font-weight: bold; font-size: 14px; background: transparent;")
        
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(f"QPushButton {{ background-color: transparent; color: {theme['subtext']}; border: none; font-weight: bold; font-size: 16px; }} QPushButton:hover {{ color: {theme['error']}; }}")
        close_btn.clicked.connect(parent_window.close)
        
        layout.addWidget(title_lbl)
        layout.addStretch()
        layout.addWidget(close_btn)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, 'drag_pos'):
            self.parent_window.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

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
    def __init__(self, config, themes, parent=None):
        super().__init__(parent)
        self.config = config
        self.themes = themes
        self.setWindowTitle("Settings")
        self.resize(450, 600)
        
        theme = themes.get(config.get("theme", "Dark Modern"), themes["Dark Modern"])
        self.setStyleSheet(f"""
            QDialog {{ background-color: {theme['bg']}; color: {theme['text']}; }}
            QLabel {{ color: {theme['text']}; font-size: 13px; margin-bottom: 4px; }}
            QLineEdit, QListWidget, QComboBox {{ background-color: {theme['surface']}; color: {theme['text']}; border: 1px solid {theme['border']}; border-radius: 6px; padding: 6px; font-size: 13px; }}
            QPushButton {{ background-color: {theme['accent']}; color: {theme['bg']}; border: none; border-radius: 6px; padding: 8px 16px; font-weight: bold; font-size: 13px; }}
            QPushButton:hover {{ opacity: 0.9; }} QPushButton#secondary {{ background-color: {theme['surface_alt']}; color: {theme['text']}; }}
            QCheckBox {{ color: {theme['text']}; font-size: 13px; spacing: 8px; }}
            QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 4px; border: 1px solid {theme['subtext']}; }}
            QCheckBox::indicator:checked {{ background-color: {theme['accent']}; border: 1px solid {theme['accent']}; }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)
        
        layout.addWidget(QLabel("Theme (Changes apply on next launch)"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(themes.keys()))
        self.theme_combo.setCurrentText(config.get("theme", "Dark Modern"))
        layout.addWidget(self.theme_combo)
        
        self.hide_unverified_cb = QCheckBox("Hide unverified users")
        self.hide_unverified_cb.setChecked(config.get("hide_unverified", False))
        layout.addWidget(self.hide_unverified_cb)
        
        self.compact_mode_cb = QCheckBox("Compact mode (single line messages)")
        self.compact_mode_cb.setChecked(config.get("compact_mode", False))
        layout.addWidget(self.compact_mode_cb)
        
        layout.addWidget(QLabel("Blocked Users (Username or ID)"))
        self.blocked_list = QListWidget()
        self.blocked_list.addItems(config.get("blocked_users", []))
        layout.addWidget(self.blocked_list)
        
        btn_layout = QHBoxLayout()
        self.add_block_btn = QPushButton("Add")
        self.add_block_btn.setObjectName("secondary")
        self.add_block_btn.clicked.connect(self.add_blocked_user)
        self.remove_block_btn = QPushButton("Remove")
        self.remove_block_btn.setObjectName("secondary")
        self.remove_block_btn.clicked.connect(self.remove_blocked_user)
        btn_layout.addWidget(self.add_block_btn)
        btn_layout.addWidget(self.remove_block_btn)
        layout.addLayout(btn_layout)
        
        layout.addWidget(QLabel("Log Directory Override"))
        dir_layout = QHBoxLayout()
        self.log_dir_edit = QLineEdit(config.get("log_dir_override", ""))
        self.log_dir_btn = QPushButton("Browse")
        self.log_dir_btn.setObjectName("secondary")
        self.log_dir_btn.clicked.connect(self.browse_log_dir)
        dir_layout.addWidget(self.log_dir_edit)
        dir_layout.addWidget(self.log_dir_btn)
        layout.addLayout(dir_layout)
        
        layout.addWidget(QLabel("Token File Override"))
        token_layout = QHBoxLayout()
        self.token_file_edit = QLineEdit(config.get("token_file_override", ""))
        self.token_file_btn = QPushButton("Browse")
        self.token_file_btn.setObjectName("secondary")
        self.token_file_btn.clicked.connect(self.browse_token_file)
        token_layout.addWidget(self.token_file_edit)
        token_layout.addWidget(self.token_file_btn)
        layout.addLayout(token_layout)
        
        layout.addStretch()
        
        action_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save & Apply")
        save_btn.clicked.connect(self.save_and_close)
        action_layout.addWidget(cancel_btn)
        action_layout.addWidget(save_btn)
        layout.addLayout(action_layout)
        
    def add_blocked_user(self):
        name, ok = QInputDialog.getText(self, "Block User", "Enter username or ID:")
        if ok and name.strip(): self.blocked_list.addItem(name.strip())
    def remove_blocked_user(self):
        current = self.blocked_list.currentRow()
        if current >= 0: self.blocked_list.takeItem(current)
    def browse_log_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Log Directory")
        if dir_path: self.log_dir_edit.setText(dir_path)
    def browse_token_file(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Select Token File", "", "JSON Files (*.json)")
        if file_path: self.token_file_edit.setText(file_path)
    def save_and_close(self):
        self.config["theme"] = self.theme_combo.currentText()
        self.config["hide_unverified"] = self.hide_unverified_cb.isChecked()
        self.config["compact_mode"] = self.compact_mode_cb.isChecked()
        self.config["blocked_users"] = [self.blocked_list.item(i).text() for i in range(self.blocked_list.count())]
        self.config["log_dir_override"] = self.log_dir_edit.text().strip()
        self.config["token_file_override"] = self.token_file_edit.text().strip()
        save_config(self.config)
        self.accept()

class ChatWindow(QMainWindow):
    def __init__(self, client: ChatClient, config: dict):
        super().__init__()
        self.client = client
        self.config = config
        self.theme_name = config.get("theme", "Dark Modern")
        self.theme = THEMES.get(self.theme_name, THEMES["Dark Modern"])
        
        self.setWindowTitle("Roblox Chat")
        self.resize(600, 500)
        self.setMinimumSize(350, 250)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        central = QWidget()
        central.setObjectName("mainWindow")
        central.setStyleSheet(f"#mainWindow {{ background-color: {self.theme['bg']}; border-radius: 16px; border: 1px solid {self.theme['border']}; }}")
        self.setCentralWidget(central)
        
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(8)
        
        self.title_bar = TitleBar(self, self.theme)
        self.main_layout.addWidget(self.title_bar)
        
        self.verify_banner = VerifyBanner(self.theme)
        self.verify_banner.hide()
        self.main_layout.addWidget(self.verify_banner)
        
        self.vk_widget = VotekickWidget(self.theme)
        self.vk_widget.hide()
        self.vk_widget.vote_clicked.connect(lambda t: self.client.send_raw({"type": "votekick_vote", "target_name": t}))
        self.main_layout.addWidget(self.vk_widget)
        
        self.chat_area = ChatScrollArea(self.theme)
        self.main_layout.addWidget(self.chat_area, 1)
        
        input_frame = QFrame()
        input_frame.setStyleSheet(f"QFrame {{ background-color: {self.theme['surface']}; border-radius: 12px; border: 1px solid {self.theme['border']}; }}")
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(12, 8, 12, 8)
        
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Type a message...")
        self.entry.setStyleSheet(f"QLineEdit {{ background-color: transparent; color: {self.theme['text']}; border: none; font-size: 13px; }}")
        self.entry.returnPressed.connect(self.on_send)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.send_btn.setStyleSheet(f"QPushButton {{ background-color: {self.theme['accent']}; color: {self.theme['bg']}; border: none; border-radius: 6px; padding: 6px 16px; font-weight: bold; }} QPushButton:hover {{ opacity: 0.8; }}")
        self.send_btn.clicked.connect(self.on_send)
        
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(32, 32)
        self.settings_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.settings_btn.setStyleSheet(f"QPushButton {{ background-color: transparent; color: {self.theme['subtext']}; border: none; font-size: 18px; }} QPushButton:hover {{ color: {self.theme['text']}; }}")
        self.settings_btn.clicked.connect(self.open_settings)
        
        input_layout.addWidget(self.entry, 1)
        input_layout.addWidget(self.send_btn)
        input_layout.addWidget(self.settings_btn)
        self.main_layout.addWidget(input_frame)
        
        # Resize Grip
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 4, 8, 8)
        bottom_layout.addStretch()
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(16, 16)
        self.size_grip.setStyleSheet("QSizeGrip { background-color: transparent; }")
        bottom_layout.addWidget(self.size_grip)
        self.main_layout.addLayout(bottom_layout)
        
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_messages)
        self.poll_timer.start(50)
        
        self.banner_timer = QTimer()
        self.banner_timer.timeout.connect(self.tick_banners)
        self.banner_timer.start(1000)
        
        self.init_banners()

    def init_banners(self):
        if not self.client.verified and self.client.verify_code:
            self.banner_deadline = time.time() + CHALLENGE_TTL
            self.verify_banner.lbl.setText(f"Unverified — add to bio: {self.client.verify_code}")
            self.verify_banner.show()
        else:
            self.banner_deadline = None
            self.verify_banner.hide()

    def tick_banners(self):
        if self.verify_banner.isVisible() and self.banner_deadline:
            remaining = self.banner_deadline - time.time()
            if remaining > 0:
                mins, secs = divmod(int(remaining), 60)
                self.verify_banner.lbl.setText(f"Unverified — add to bio: {self.client.verify_code}  ({mins}:{secs:02d})")
            else:
                self.verify_banner.lbl.setText("Verifying...")
                self.banner_timer.stop()
                self.verify_thread = QThread()
                self.verify_worker = VerifyWorker(self.client)
                self.verify_worker.moveToThread(self.verify_thread)
                self.verify_thread.started.connect(self.verify_worker.run)
                self.verify_worker.finished.connect(self.on_verify_finished)
                self.verify_thread.start()
                
        if self.vk_widget.isVisible() and self.vk_widget.deadline:
            remaining = self.vk_widget.deadline - time.time()
            if remaining > 0:
                self.vk_widget.timer_lbl.setText(f"{int(remaining)}s")
            else:
                self.vk_widget.timer_lbl.setText("0s")
                self.resolve_votekick({"result": "expired", "target": self.vk_widget.target})

    def on_verify_finished(self, success):
        self.verify_thread.quit()
        self.verify_thread.wait()
        self.banner_timer.start()
        if success:
            self.verify_banner.lbl.setText("Verified ✓ Reconnecting...")
            self.verify_banner.setStyleSheet(f"QFrame {{ background-color: {self.theme['surface_alt']}; border-radius: 10px; }} QLabel {{ color: #4ade80; font-weight: bold; background: transparent; font-size: 12px; }}")
            QTimer.singleShot(3000, self.verify_banner.hide)
        else:
            self.verify_banner.lbl.setText("Verification expired — reconnect to try again")
            self.verify_banner.setStyleSheet(f"QFrame {{ background-color: {self.theme['surface_alt']}; border-radius: 10px; }} QLabel {{ color: {self.theme['error']}; font-weight: bold; background: transparent; font-size: 12px; }}")
            QTimer.singleShot(5000, self.verify_banner.hide)

    def poll_messages(self):
        for msg in self.client.poll(): self.handle_message(msg)
            
    def handle_message(self, msg):
        mtype = msg.get("type")
        if mtype in ["chat", "system", "error"]:
            self.chat_area.add_message(msg, self.theme, self.config)
        elif mtype == "clear":
            self.chat_area.clear_messages()
        elif mtype == "history":
            for m in msg.get("messages", []): self.handle_message(m)
        elif mtype == "votekick_init": self.show_votekick(msg)
        elif mtype == "votekick_update": self.update_votekick(msg)
        elif mtype == "votekick_result": self.resolve_votekick(msg)

    def show_votekick(self, msg):
        target = msg.get("target", "?")
        self.vk_widget.target = target.lower()
        self.vk_widget.deadline = msg.get("deadline", time.time() + 60)
        initiator = msg.get("initiator", "?")
        reason = msg.get("reason")
        votes = msg.get("votes", 0)
        needed = msg.get("needed", 3)
        reason_text = f' for "{reason}"' if reason else ""
        self.vk_widget.info_lbl.setText(f'{initiator} initiated a votekick on {target}{reason_text}')
        self.vk_widget.status_lbl.setText(f"Votes: {votes}/{needed}  —  /votekick {target} to vote")
        self.vk_widget.vote_btn.setEnabled(True)
        self.vk_widget.show()

    def update_votekick(self, msg):
        votes = msg.get("votes", 0)
        needed = msg.get("needed", 3)
        target = msg.get("target", "?")
        self.vk_widget.status_lbl.setText(f"Votes: {votes}/{needed}  —  /votekick {target} to vote")

    def resolve_votekick(self, msg):
        result = msg.get("result")
        target = msg.get("target", "?")
        if result == "kicked":
            self.vk_widget.info_lbl.setText(f"{target} was votekicked")
            self.vk_widget.info_lbl.setStyleSheet(f"color: #4ade80; font-weight: bold; font-size: 13px;")
        else:
            self.vk_widget.info_lbl.setText(f"Votekick on {target} expired")
            self.vk_widget.info_lbl.setStyleSheet(f"color: {self.theme['subtext']}; font-weight: bold; font-size: 13px;")
        self.vk_widget.status_lbl.setText("")
        self.vk_widget.vote_btn.setEnabled(False)
        QTimer.singleShot(4000, self.vk_widget.hide)
        self.vk_widget.deadline = None

    def on_send(self):
        text = self.entry.text().strip()
        if not text: return
        self.entry.clear()
        if text.lower().startswith("/votekick"):
            self.handle_votekick(text)
            return
        if text.lower() == "/clear":
            self.chat_area.clear_messages()
            return
        self.client.send(text)
        
    def handle_votekick(self, text):
        parts = text.split(maxsplit=2)
        if len(parts) < 2:
            self.chat_area.add_message({"type": "error", "text": "Usage: /votekick <name> [reason]"}, self.theme, self.config)
            return
        target_name = parts[1]
        reason = parts[2] if len(parts) > 2 else ""
        if self.vk_widget.isVisible() and self.vk_widget.target == target_name.lower():
            self.client.send_raw({"type": "votekick_vote", "target_name": target_name})
        else:
            self.client.send_raw({"type": "votekick_init", "target_name": target_name, "reason": reason})

    def open_settings(self):
        dialog = SettingsDialog(self.config, THEMES, self)
        dialog.exec()

    def closeEvent(self, event):
        self.client.disconnect()
        event.accept()

# region Start

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
    
    font = QFont("Segoe UI", 10)
    if not font.exactMatch(): font = QFont("Inter", 10)
    if not font.exactMatch(): font = QFont("SF Pro Display", 10)
    if not font.exactMatch(): font = QFont("system-ui", 10)
    app.setFont(font)
    
    window = ChatWindow(client, config)
    window.show()
    sys.exit(app.exec())
