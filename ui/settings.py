from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, 
    QLabel, QDialog, QCheckBox,QFileDialog, 
    QListWidget, QInputDialog, QComboBox
)

from config import THEMES, save_config
from utils import KEYBOARD_AVAILABLE
from ui.widgets import HotkeyEdit

class SettingsDialog(QDialog):
    def __init__(self, config: dict, themes: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.themes = themes
        self.setWindowTitle("Settings")
        self.resize(480, 700)

        theme = themes.get(config.get("theme", "Dark Modern"), themes["Dark Modern"])

        self.setStyleSheet(
            f"""
            QDialog {{ background-color: {theme['bg']}; color: {theme['text']}; }}
            QLabel {{ color: {theme['text']}; font-size: 13px; margin-bottom: 4px; }}
            QLineEdit, QListWidget, QComboBox {{
                background-color: {theme['surface']};
                color: {theme['text']};
                border: 1px solid {theme['border']};
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
            }}
            QPushButton {{
                background-color: {theme['accent']};
                color: {theme['bg']};
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{ opacity: 0.9; }}
            QPushButton#secondary {{
                background-color: {theme['surface_alt']};
                color: {theme['text']};
            }}
            QCheckBox {{
                color: {theme['text']};
                font-size: 13px;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid {theme['subtext']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {theme['accent']};
                border: 1px solid {theme['accent']};
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        layout.addWidget(QLabel("Theme (changes fully apply on next launch)"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(themes.keys()))
        self.theme_combo.setCurrentText(config.get("theme", "Dark Modern"))
        layout.addWidget(self.theme_combo)

        self.compact_mode_cb = QCheckBox("Compact mode ([time] [name] [message])")
        self.compact_mode_cb.setChecked(config.get("compact_mode", False))
        layout.addWidget(self.compact_mode_cb)

        self.show_on_server_cb = QCheckBox("Re-show window when server changes")
        self.show_on_server_cb.setChecked(config.get("show_on_server_change", True))
        layout.addWidget(self.show_on_server_cb)

        layout.addWidget(QLabel("Global focus hotkey"))
        self.hotkey_edit = HotkeyEdit(config.get("focus_hotkey", ""))
        layout.addWidget(self.hotkey_edit)

        self.auto_hide_cb = QCheckBox("Auto-hide && return focus to game after sending via hotkey")
        self.auto_hide_cb.setChecked(config.get("auto_hide_on_send", False))
        layout.addWidget(self.auto_hide_cb)

        if KEYBOARD_AVAILABLE:
            hotkey_note = QLabel(
                "Warning: a simple hotkey like / will be intercepted globally and "
                "will not reach other apps while this program is running."
            )
        else:
            hotkey_note = QLabel(
                "Global hotkeys require the optional `keyboard` package:\n"
                "pip install keyboard\n"
                "On Linux this may need root/uinput permissions."
            )

        hotkey_note.setWordWrap(True)
        hotkey_note.setStyleSheet(f"color: {theme['subtext']}; font-size: 11px;")
        layout.addWidget(hotkey_note)

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

        # Double ampersand escapes the mnemonic, so it displays "Save & Apply".
        save_btn = QPushButton("Save && Apply")
        save_btn.clicked.connect(self.save_and_close)

        action_layout.addWidget(cancel_btn)
        action_layout.addWidget(save_btn)
        layout.addLayout(action_layout)

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
        if dir_path:
            self.log_dir_edit.setText(dir_path)

    def browse_token_file(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Select Token File",
            "",
            "JSON Files (*.json)"
        )
        if file_path:
            self.token_file_edit.setText(file_path)

    def save_and_close(self):
        self.config["theme"] = self.theme_combo.currentText()
        self.config["compact_mode"] = self.compact_mode_cb.isChecked()
        self.config["show_on_server_change"] = self.show_on_server_cb.isChecked()
        self.config["focus_hotkey"] = self.hotkey_edit.text().strip()
        self.config["auto_hide_on_send"] = self.auto_hide_cb.isChecked()

        self.config["blocked_users"] = [
            self.blocked_list.item(i).text()
            for i in range(self.blocked_list.count())
        ]

        self.config["log_dir_override"] = self.log_dir_edit.text().strip()
        self.config["token_file_override"] = self.token_file_edit.text().strip()

        save_config(self.config)
        self.accept()