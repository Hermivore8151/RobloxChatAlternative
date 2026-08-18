"""
2.5.0
- Fix a bug to do with saving settings
- De-monolith the codebase
"""
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

from config import load_config
from log_parser import parse_latest_log
from client import ChatClient
from ui.main_window import ChatWindow

def main():
    config = load_config()
    _, server_id = parse_latest_log(config)

    if server_id is None:
        print("No active Roblox session found. Make sure Roblox is running.")
        input("Press enter to exit.")
        sys.exit(1)

    print(f"Detected server {server_id}")

    client = ChatClient(server_id, config)
    client.connect() 

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    font = QFont("Segoe UI", 10)

    if not font.exactMatch():
        font = QFont("Inter", 10)
    if not font.exactMatch():
        font = QFont("SF Pro Display", 10)
    if not font.exactMatch():
        font = QFont("system-ui", 10)

    app.setFont(font)
    
    window = ChatWindow(client, config)
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()