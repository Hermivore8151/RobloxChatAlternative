from pathlib import Path
import re

from config import get_log_dir

_RE_UID = re.compile(r"userid:(\d+)", re.I) # isn't needed anymore, but its 5am so ill clean it up later
_RE_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)

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