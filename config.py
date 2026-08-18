from pathlib import Path
import os, json

CONFIG_FILE = Path.home() / ".roblox_chat_config.json"
TOKEN_FILE_DEFAULT = Path.home() / ".roblox_chat_token"


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
    "auth_method": "oauth", # oauth is technically more reliable, but im unsure what roblox will think. Always good to have options.
                            # if you want to use the alt method, set this to "friends"
    "hide_unverified": False,
    "compact_mode": False,
    "show_on_server_change": True,
    "focus_hotkey": "",
    "auto_hide_on_send": False,
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


def _load_stored_token(config: dict) -> dict:
    try:
        return json.loads(get_token_file(config).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_stored_token(config: dict, key: str, token: str | None):
    stored = _load_stored_token(config)
    if token is None:
        stored.pop(str(key), None)
    else:
        stored[str(key)] = token
    get_token_file(config).write_text(json.dumps(stored), encoding="utf-8")