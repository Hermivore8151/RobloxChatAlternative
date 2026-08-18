from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QFrame,QMenu, QSystemTrayIcon
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QEvent
from PyQt6.QtGui import QCursor, QAction

import os, time, httpx, webbrowser

from utils import force_foreground_window, KEYBOARD_AVAILABLE, keyboard, ctypes
from config import THEMES, _save_stored_token
from constants import API_BASE
from client import ChatClient

from ui.widgets import TitleBar, VerifyBanner, VotekickWidget, ChatScrollArea, create_tray_icon
from ui.filters import ResizeEventFilter
from ui.settings import SettingsDialog
from ui.workers import VerifyWorker

class ChatWindow(QMainWindow):
    hotkey_pressed = pyqtSignal()

    def __init__(self, client: ChatClient, config: dict):
        super().__init__()
        self.client = client
        self.config = config

        self.theme_name = config.get("theme", "Dark Modern")
        self.theme = THEMES.get(self.theme_name, THEMES["Dark Modern"])

        self.hotkey_handle = None
        self.tray = None
        self._trayhint_shown = False

        self._win_hwnd = 0
        
        # Tracking state for the "auto hide & return focus" feature
        self._opened_via_hotkey_only = False
        self._prev_hwnd = 0
        self._prev_state = "visible"

        self.setWindowTitle("Roblox Chat")
        self.resize(600, 500)
        self.setMinimumSize(380, 280)

        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True) # Needed for cursor tracking when not clicking

        panel = QFrame()
        panel.setObjectName("panel")
        panel.setStyleSheet(
            f"""
            #panel {{
                background-color: {self.theme['bg']};
                border-radius: 16px;
                border: 1px solid {self.theme['border']};
            }}
            """
        )

        self.setCentralWidget(panel)

        self.main_layout = QVBoxLayout(panel)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(8)

        self.title_bar = TitleBar(self, self.theme)
        self.main_layout.addWidget(self.title_bar)

        self.verify_banner = VerifyBanner(self.theme)
        self.verify_banner.hide()
        self.main_layout.addWidget(self.verify_banner)

        self.vk_widget = VotekickWidget(self.theme)
        self.vk_widget.hide()
        self.vk_widget.vote_clicked.connect(
            lambda t: self.client.send_raw({"type": "votekick_vote", "target_name": t})
        )
        self.main_layout.addWidget(self.vk_widget)

        self.chat_area = ChatScrollArea(self.theme)
        self.main_layout.addWidget(self.chat_area, 1)

        input_frame = QFrame()
        input_frame.setStyleSheet(
            f"""
            QFrame {{
                background-color: {self.theme['surface']};
                border-radius: 12px;
                border: 1px solid {self.theme['border']};
            }}
            """
        )

        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(12, 8, 12, 8)

        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Type a message...")
        self.entry.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: transparent;
                color: {self.theme['text']};
                border: none;
                font-size: 13px;
            }}
            """
        )
        self.entry.returnPressed.connect(self.on_send)

        self.send_btn = QPushButton("Send")
        self.send_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.send_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {self.theme['accent']};
                color: {self.theme['bg']};
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{ opacity: 0.8; }}
            """
        )
        self.send_btn.clicked.connect(self.on_send)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(32, 32)
        self.settings_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.settings_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                color: {self.theme['subtext']};
                border: none;
                font-size: 18px;
            }}
            QPushButton:hover {{ color: {self.theme['text']}; }}
            """
        )
        self.settings_btn.clicked.connect(self.open_settings)

        input_layout.addWidget(self.entry, 1)
        input_layout.addWidget(self.send_btn)
        input_layout.addWidget(self.settings_btn)

        self.main_layout.addWidget(input_frame)

        self.setup_tray()

        self.hotkey_pressed.connect(lambda: self.show_from_tray(focus_input=True, via_hotkey=True))
        self.register_hotkey()

        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_messages)
        self.poll_timer.start(50)

        self.banner_timer = QTimer()
        self.banner_timer.timeout.connect(self.tick_banners)
        self.banner_timer.start(1000)

        self.init_banners()
        
        # Install resize filter over the entire app to catch margins reliably
        self.resize_filter = ResizeEventFilter(self)
        QApplication.instance().installEventFilter(self.resize_filter)
        
        # Install event filter on the whole application to catch mouse clicks on any child widget
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        # If the user clicks anywhere inside the chat window, we consider it "interacted with"
        # and disable the "auto hide on send" feature for this session.
        if event.type() == QEvent.Type.MouseButtonPress:
            if obj is self or (isinstance(obj, QWidget) and self.isAncestorOf(obj)):
                self._opened_via_hotkey_only = False
        return super().eventFilter(obj, event)

    def _ensure_hwnd(self):
        if os.name != "nt":
            return

        if not self._win_hwnd:
            try:
                self._win_hwnd = int(self.winId())
            except Exception:
                self._win_hwnd = 0

    def _on_hotkey(self):
        # Track state prior to using the hotkey
        if not self.isVisible():
            self._prev_state = "hidden"
        elif self.isMinimized():
            self._prev_state = "minimized"
        else:
            self._prev_state = "visible"

        if os.name == "nt":
            self._ensure_hwnd()
            try:
                self._prev_hwnd = ctypes.windll.user32.GetForegroundWindow()
            except Exception:
                self._prev_hwnd = 0
            force_foreground_window(self._win_hwnd)

        self.hotkey_pressed.emit()

    # region Tray / Visibility

    def setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return

        self.tray = QSystemTrayIcon(create_tray_icon(self.theme), self)
        self.tray.setToolTip("Roblox Chat")

        menu = QMenu()

        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show_from_tray)

        hide_action = QAction("Hide", self)
        hide_action.triggered.connect(self.hide_to_tray)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_app)

        menu.addAction(show_action)
        menu.addAction(hide_action)
        menu.addSeparator()
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible() and not self.isMinimized():
                self.hide_to_tray()
            else:
                self.show_from_tray()

        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_from_tray()

    def minimize_to_tray(self):
        self.hide_to_tray()

    def hide_to_tray(self):
        if self.tray and self.tray.isVisible():
            self.hide()

            if not self._trayhint_shown:
                self.tray.showMessage(
                    "Roblox Chat",
                    "Chat hidden. Click the tray icon or use your focus hotkey to restore.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )
                self._trayhint_shown = True
        else:
            self.showMinimized()

    def show_from_tray(self, focus_input: bool = False, via_hotkey: bool = False):
        if via_hotkey:
            self._opened_via_hotkey_only = True
        else:
            # If shown via tray click or server change, reset the hotkey-only state
            self._opened_via_hotkey_only = False

        if self.isMinimized():
            self.showNormal()
        elif not self.isVisible():
            self.show()

        self.raise_()
        self.activateWindow()
        QApplication.setActiveWindow(self)

        if focus_input:
            QTimer.singleShot(20, self._focus_entry)

    def _focus_entry(self):
        if not self.isVisible():
            return

        if os.name == "nt":
            self._ensure_hwnd()
            force_foreground_window(self._win_hwnd)

        self.entry.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.entry.activateWindow()

    def quit_app(self):
        self.unregister_hotkey()

        if self.tray:
            self.tray.hide()

        self.client.disconnect()
        QApplication.quit()

    # region Global Hotkey

    def register_hotkey(self):
        if not KEYBOARD_AVAILABLE or keyboard is None:
            return

        hotkey = self.config.get("focus_hotkey", "").strip()
        if not hotkey:
            return

        self._ensure_hwnd()

        try:
            self.hotkey_handle = keyboard.add_hotkey(
                hotkey,
                self._on_hotkey,
                suppress=True
            )
        except Exception as e:
            print(f"Failed to register hotkey '{hotkey}': {e}")
            self.hotkey_handle = None

    def unregister_hotkey(self):
        if not KEYBOARD_AVAILABLE or keyboard is None:
            return

        if self.hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.hotkey_handle)
            except Exception:
                pass

            self.hotkey_handle = None

    def open_settings(self):
        self.unregister_hotkey()

        dialog = SettingsDialog(self.config, THEMES, self)
        dialog.exec()

        self.register_hotkey()

    # region Banners / Timers

    def init_banners(self):
        if not self.client._running:
            self.start_verification_flow()
        else:
            self.banner_deadline = None
            self.verify_banner.hide()

    def start_verification_flow(self):
        if not self.banner_timer.isActive():
            self.banner_timer.start(1000)

        method = self.config.get("auth_method", "friend")  # "friend" | "oauth" | or auto-fallback
        endpoint = "/api/roblox/verify/challenge" if method == "friend" else "/api/roblox/oauth/challenge"

        try:
            data = httpx.post(f"{API_BASE}{endpoint}", timeout=10).json()
        except Exception:
            self.verify_banner.lbl.setText("Failed to contact verify server")
            self.verify_banner.show()
            return

        if "error" in data:
            self.verify_banner.lbl.setText(data.get("reason", "Verify error"))
            self.verify_banner.show()
            return

        if "bot_name" in data:
            QApplication.clipboard().setText(data["bot_name"])
            webbrowser.open(f"https://www.roblox.com/users/{data['bot_id']}/profile")
            status_url = f"{API_BASE}/api/roblox/verify/status/{data['session_id']}"
            self.verify_banner.lbl.setText(f"Add {data['bot_name']} (copied to clipboard), then wait...")

        else:
            webbrowser.open(data["auth_url"])
            status_url = f"{API_BASE}/api/roblox/oauth/status/{data['session_id']}"
            self.verify_banner.lbl.setText("Log in with Roblox in the browser...")

        self.banner_deadline = time.time() + data["ttl"]
        self.verify_banner.show()

        self.verify_thread = QThread()
        self.verify_worker = VerifyWorker(status_url)
        self.verify_worker.moveToThread(self.verify_thread)
        self.verify_thread.started.connect(self.verify_worker.run)
        self.verify_worker.finished.connect(self.on_verify_finished)
        self.verify_thread.start()

    def tick_banners(self):
        if self.verify_banner.isVisible() and self.banner_deadline:
            remaining = self.banner_deadline - time.time()

            if remaining > 0:
                mins, secs = divmod(int(remaining), 60)
                self.verify_banner.lbl.setText(
                    f"Add friend (name copied to clipboard)  ({mins}:{secs:02d})"
                )
            else:
                self.verify_banner.lbl.setText("Verification timed out - retrying...")
                self.banner_timer.stop()
                # Automatically retry after 2 seconds
                QTimer.singleShot(2000, self.start_verification_flow)

        if self.vk_widget.isVisible() and self.vk_widget.deadline:
            remaining = self.vk_widget.deadline - time.time()

            if remaining > 0:
                self.vk_widget.timer_lbl.setText(f"{int(remaining)}s")
            else:
                self.vk_widget.timer_lbl.setText("0s")
                self.resolve_votekick({"result": "expired", "target": self.vk_widget.target})

    def on_verify_finished(self, success: bool, token: str = ""):
        try:
            self.verify_thread.quit()
            self.verify_thread.wait()
        except Exception:
            pass

        if success and token:
            self.verify_banner.lbl.setText("Verified ✓ Connecting...")
            self.client.session_token = token
            # Ensure it's saved to the ACTUAL config's token file path for next launch
            _save_stored_token(self.client.config, "backend_session_jwt", token)
            
            if self.client.connect():
                self.verify_banner.lbl.setText("Connected!")
                QTimer.singleShot(2000, self.verify_banner.hide)
            else:
                self.verify_banner.lbl.setText("Verified, but connection failed.")
        else:
            self.verify_banner.lbl.setText("Verification expired - retrying...")
            QTimer.singleShot(2000, self.start_verification_flow)

    # region Messages

    def poll_messages(self):
        for msg in self.client.poll():
            self.handle_message(msg)

    def handle_message(self, msg: dict):
        mtype = msg.get("type")

        if mtype == "server_change":
            if self.config.get("show_on_server_change", True):
                if not self.isVisible() or self.isMinimized():
                    self.show_from_tray()
            return

        if mtype in ("chat", "system", "error"):
            self.chat_area.add_message(msg, self.theme, self.config)

        elif mtype == "clear":
            self.chat_area.clear_messages()

        elif mtype == "history":
            for m in msg.get("messages", []):
                self.handle_message(m)

        elif mtype == "votekick_init":
            self.show_votekick(msg)

        elif mtype == "votekick_update":
            self.update_votekick(msg)

        elif mtype == "votekick_result":
            self.resolve_votekick(msg)

    def show_votekick(self, msg: dict):
        target = msg.get("target", "?")
        self.vk_widget.target = target.lower()
        self.vk_widget.deadline = msg.get("deadline", time.time() + 60)

        initiator = msg.get("initiator", "?")
        reason = msg.get("reason")
        votes = msg.get("votes", 0)
        needed = msg.get("needed", 3)

        reason_text = f' for "{reason}"' if reason else ""

        self.vk_widget.info_lbl.setText(
            f"{initiator} initiated a votekick on {target}{reason_text}"
        )
        self.vk_widget.status_lbl.setText(
            f"Votes: {votes}/{needed}  —  /votekick {target} to vote"
        )

        self.vk_widget.vote_btn.setEnabled(True)
        self.vk_widget.show()

    def update_votekick(self, msg: dict):
        votes = msg.get("votes", 0)
        needed = msg.get("needed", 3)
        target = msg.get("target", "?")

        self.vk_widget.status_lbl.setText(
            f"Votes: {votes}/{needed}  —  /votekick {target} to vote"
        )

    def resolve_votekick(self, msg: dict):
        result = msg.get("result")
        target = msg.get("target", "?")

        if result == "kicked":
            self.vk_widget.info_lbl.setText(f"{target} was votekicked")
            self.vk_widget.info_lbl.setStyleSheet(
                "color: #4ade80; font-weight: bold; font-size: 13px;"
            )
        else:
            self.vk_widget.info_lbl.setText(f"Votekick on {target} expired")
            self.vk_widget.info_lbl.setStyleSheet(
                f"color: {self.theme['subtext']}; font-weight: bold; font-size: 13px;"
            )

        self.vk_widget.status_lbl.setText("")
        self.vk_widget.vote_btn.setEnabled(False)

        QTimer.singleShot(4000, self.vk_widget.hide)
        self.vk_widget.deadline = None

    # region Input

    def on_send(self):
        text = self.entry.text().strip()
        if not text:
            return

        self.entry.clear()

        if text.lower().startswith("/votekick"):
            self.handle_votekick(text)
        elif text.lower() == "/clear":
            self.chat_area.clear_messages()
        else:
            self.client.send(text)

        self._post_send_logic()

    def _post_send_logic(self):
        # If the user enabled the setting AND they haven't clicked the window 
        # since the hotkey brought it up, mirror previous state.
        if self.config.get("auto_hide_on_send", False) and self._opened_via_hotkey_only:
            if self._prev_state == "hidden":
                self.hide() # Back to tray
            elif self._prev_state == "minimized":
                self.showMinimized() # Back to taskbar
            else:
                # Was visible but unfocused, so we drop to bottom of Z-order and give focus back to the game
                self.lower()
                self.clearFocus()
                if os.name == "nt" and self._prev_hwnd:
                    try:
                        prev = self._prev_hwnd
                        QTimer.singleShot(50, lambda: ctypes.windll.user32.SetForegroundWindow(prev))
                    except Exception:
                        pass
            
            self._opened_via_hotkey_only = False

    def handle_votekick(self, text: str):
        parts = text.split(maxsplit=2)

        if len(parts) < 2:
            self.chat_area.add_message(
                {"type": "error", "text": "Usage: /votekick <name> [reason]"},
                self.theme,
                self.config
            )
            return

        target_name = parts[1]
        reason = parts[2] if len(parts) > 2 else ""

        if self.vk_widget.isVisible() and self.vk_widget.target == target_name.lower():
            self.client.send_raw({
                "type": "votekick_vote",
                "target_name": target_name
            })
        else:
            self.client.send_raw({
                "type": "votekick_init",
                "target_name": target_name,
                "reason": reason
            })

    # region Window events

    def closeEvent(self, event):
        self.unregister_hotkey()

        if self.tray:
            self.tray.hide()

        self.client.disconnect()
        event.accept()