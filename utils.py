import os
if os.name == "nt":
    import ctypes
else:
    ctypes = None

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except Exception:
    keyboard = None
    KEYBOARD_AVAILABLE = False

def normalize_hotkey(text: str) -> str:
    if not text:
        return ""

    text = text.strip().lower()
    parts = [p.strip() for p in text.split("+") if p.strip()]

    replacements = {
        "control": "ctrl",
        "meta": "windows",
        "cmd": "windows",
        "command": "windows",
        "win": "windows",
        "option": "alt",
        "return": "enter",
        "esc": "escape",
        "spacebar": "space",
        "pgup": "page up",
        "pgdown": "page down",
    }

    parts = [replacements.get(p, p) for p in parts]
    return "+".join(parts)

def force_foreground_window(hwnd: int):
    if os.name != "nt" or not hwnd:
        return

    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        foreground = user32.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
        current_thread = kernel32.GetCurrentThreadId()

        attached = False
        if foreground_thread and foreground_thread != current_thread:
            attached = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))

        user32.ShowWindow(hwnd, 9)
        user32.BringWindowToTop(hwnd)

        ok = user32.SetForegroundWindow(hwnd)

        if not ok:
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)
            user32.SetForegroundWindow(hwnd)

        if attached:
            user32.AttachThreadInput(current_thread, foreground_thread, False)

    except Exception:
        pass