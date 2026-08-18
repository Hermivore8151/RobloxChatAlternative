from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, 
    QLabel, QFrame, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal
)
from PyQt6.QtGui import (
    QFont, QCursor, QPixmap, QPainter, 
    QIcon, QKeySequence, QColor
)
import html, time

from utils import normalize_hotkey

def create_tray_icon(theme: dict) -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setBrush(QColor(theme["accent"]))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)

    painter.setPen(QColor(theme["bg"]))
    font = QFont("Segoe UI", 28, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "C")
    painter.end()

    return QIcon(pixmap)

class HotkeyEdit(QLineEdit):
    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setReadOnly(True)
        self.setPlaceholderText("Click here, then press a key/combo (Esc clears)")

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()

        if key in (
            Qt.Key.Key_Control,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
        ):
            return

        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            super().keyPressEvent(event)
            return

        if key == Qt.Key.Key_Escape and not mods:
            self.setText("")
            return

        parts = []

        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")

        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")

        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")

        if mods & Qt.KeyboardModifier.MetaModifier:
            parts.append("windows")

        key_name = ""

        try:
            key_name = (
                QKeySequence(int(key))
                .toString(QKeySequence.SequenceFormat.NativeText)
                .strip()
                .lower()
            )
        except Exception:
            key_name = ""

        if not key_name:
            text = event.text()
            if text and text.isprintable() and text.strip():
                key_name = text.strip().lower()

        if not key_name:
            return

        if key_name == "+":
            key_name = "plus"

        parts.append(key_name)

        self.setText(normalize_hotkey("+".join(parts)))


class ChatMessageWidget(QWidget):
    def __init__(self, theme: dict, msg: dict, config: dict):
        super().__init__()
        self.theme = theme
        self.config = config
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        mtype = msg.get("type")
        if mtype == "chat":
            self.setup_chat(msg)
        elif mtype == "system":
            self.setup_system(msg)
        elif mtype == "error":
            self.setup_error(msg)
        else:
            self.hide()

    def setup_chat(self, msg: dict):
        sender_raw = msg.get("name", "")
        text_raw = msg.get("text", "")
        is_verified = msg.get("verified", False)
        ts = time.strftime("%H:%M", time.localtime(msg.get("ts", 0)))

        if self.config.get("compact_mode"):
            sender = html.escape(sender_raw)
            text = html.escape(text_raw).replace("\n", "<br>")

            if not is_verified:
                name_html = (
                    f"<span style='background-color: {self.theme['unverified_bg']}; "
                    f"color: {self.theme['unverified_text']}; "
                    f"padding: 1px 6px; border-radius: 4px; "
                    f"font-weight: bold; font-size: 12px;'>{sender}</span>"
                )
            else:
                name_html = (
                    f"<span style='color: {self.theme['accent']}; "
                    f"font-weight: bold; font-size: 12px;'>{sender}</span>"
                )

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
            bubble.setStyleSheet(
                f"QFrame {{ background-color: {self.theme['surface']}; border-radius: 8px; }}"
            )

            b_layout = QVBoxLayout(bubble)
            b_layout.setContentsMargins(10, 6, 10, 8)
            b_layout.addWidget(lbl)

            self.main_layout.addWidget(bubble)

        else:
            bubble = QFrame()
            bubble.setStyleSheet(
                f"QFrame {{ background-color: {self.theme['surface']}; border-radius: 12px; }}"
            )

            bubble_layout = QVBoxLayout(bubble)
            bubble_layout.setContentsMargins(14, 10, 14, 12)
            bubble_layout.setSpacing(6)

            header_layout = QHBoxLayout()
            header_layout.setSpacing(8)

            time_lbl = QLabel(ts)
            time_lbl.setStyleSheet(
                f"color: {self.theme['subtext']}; font-size: 11px; background: transparent;"
            )

            user_lbl = QLabel(sender_raw)
            if not is_verified:
                user_lbl.setStyleSheet(
                    f"""
                    background-color: {self.theme['unverified_bg']};
                    color: {self.theme['unverified_text']};
                    padding: 2px 8px;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 12px;
                    """
                )
            else:
                user_lbl.setStyleSheet(
                    f"color: {self.theme['accent']}; font-weight: bold; font-size: 12px; background: transparent;"
                )

            header_layout.addWidget(time_lbl)
            header_layout.addWidget(user_lbl)
            header_layout.addStretch()

            text_lbl = QLabel(text_raw)
            text_lbl.setWordWrap(True)
            text_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text_lbl.setStyleSheet(
                f"color: {self.theme['text']}; font-size: 13px; background: transparent;"
            )

            bubble_layout.addLayout(header_layout)
            bubble_layout.addWidget(text_lbl)

            self.main_layout.addWidget(bubble)

    def setup_system(self, msg: dict):
        lbl = QLabel(msg.get("text", ""))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {self.theme['subtext']}; font-style: italic; font-size: 11px; "
            f"padding: 4px; background: transparent;"
        )
        self.main_layout.addWidget(lbl)

    def setup_error(self, msg: dict):
        bubble = QFrame()
        bubble.setStyleSheet(
            f"QFrame {{ background-color: rgba(255, 50, 50, 0.1); "
            f"border: 1px solid {self.theme['error']}; border-radius: 8px; }}"
        )

        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(10, 6, 10, 6)

        lbl = QLabel(f"⚠ {msg.get('text', '')}")
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {self.theme['error']}; font-size: 12px; background: transparent;"
        )

        layout.addWidget(lbl)
        self.main_layout.addWidget(bubble)


class ChatScrollArea(QScrollArea):
    def __init__(self, theme: dict):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            f"""
            QScrollArea {{ border: none; background-color: {theme['bg']}; }}
            QScrollBar:vertical {{ border: none; background: {theme['bg']}; width: 10px; margin: 0px; }}
            QScrollBar::handle:vertical {{ background: {theme['surface_alt']}; min-height: 20px; border-radius: 5px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            """
        )

        self.container = QWidget()
        self.container.setStyleSheet(f"background-color: {theme['bg']};")
        self.container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self.layout = QVBoxLayout(self.container)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(8)
        self.layout.addStretch(1)

        self.setWidget(self.container)

    def add_message(self, msg: dict, theme: dict, config: dict):
        mtype = msg.get("type")

        if mtype == "chat":
            sender = msg.get("name", "")
            sender_id = str(msg.get("user_id", ""))
            is_verified = msg.get("verified", False)

            # if config.get("hide_unverified") and not is_verified:
            #     return

            blocked = config.get("blocked_users", [])
            if sender in blocked or sender_id in blocked:
                return

        widget = ChatMessageWidget(theme, msg, config)
        self.layout.addWidget(widget)
        QTimer.singleShot(10, self.scroll_to_bottom)

    def clear_messages(self):
        while self.layout.count() > 1:
            item = self.layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

    def scroll_to_bottom(self):
        vbar = self.verticalScrollBar()
        vbar.setValue(vbar.maximum())


class VerifyBanner(QFrame):
    def __init__(self, theme: dict):
        super().__init__()
        self.setStyleSheet(
            f"""
            QFrame {{ background-color: {theme['surface_alt']}; border-radius: 10px; }}
            QLabel {{ color: {theme['accent']}; font-weight: bold; background: transparent; font-size: 12px; }}
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)

        self.lbl = QLabel()
        layout.addWidget(self.lbl)


class VotekickWidget(QFrame):
    vote_clicked = pyqtSignal(str)

    def __init__(self, theme: dict):
        super().__init__()
        self.target = ""
        self.deadline = 0

        self.setStyleSheet(
            f"""
            QFrame {{ background-color: {theme['surface']}; border: 1px solid {theme['border']}; border-radius: 12px; }}
            QLabel {{ background: transparent; }}
            QPushButton {{
                background-color: {theme['error']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{ opacity: 0.9; }}
            QPushButton:disabled {{ background-color: {theme['subtext']}; }}
            """
        )

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

    def on_vote(self):
        self.vote_clicked.emit(self.target)


class TitleBar(QWidget):
    def __init__(self, parent_window: "ChatWindow", theme: dict): # type: ignore
        super().__init__()
        self.parent_window = parent_window

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        title_lbl = QLabel("Roblox Chat")
        title_lbl.setStyleSheet(
            f"color: {theme['text']}; font-weight: bold; font-size: 14px; background: transparent;"
        )

        min_btn = QPushButton("–")
        min_btn.setFixedSize(24, 24)
        min_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        min_btn.setToolTip("Minimize to tray")
        min_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                color: {theme['subtext']};
                border: none;
                font-weight: bold;
                font-size: 16px;
            }}
            QPushButton:hover {{ color: {theme['text']}; }}
            """
        )
        min_btn.clicked.connect(parent_window.minimize_to_tray)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setToolTip("Close")
        close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                color: {theme['subtext']};
                border: none;
                font-weight: bold;
                font-size: 16px;
            }}
            QPushButton:hover {{ color: {theme['error']}; }}
            """
        )
        close_btn.clicked.connect(parent_window.close)

        layout.addWidget(title_lbl)
        layout.addStretch()
        layout.addWidget(min_btn)
        layout.addWidget(close_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "drag_pos"):
            self.parent_window.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()
