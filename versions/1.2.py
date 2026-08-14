"""
v1.2
first major attempt of the chat system with the API fully supported
supports linux (with arch help hints) and windows
"""
from tkinter import scrolledtext
from pathlib import Path
try:
    import tkinter as tk
except:
    input("Failed to Install tkinter, presumably because you are on linux. It can be installed (on arch) like this: \npacman -S python tk\nPlease search for the respective ways to install for your OS\nPress enter to exit")
import threading
import queue
import json
import time
import re
import os

httpx_error = False
ws_error = False

try:
    import httpx
except ImportError as e:
    input(str(e))
    httpx_error = True

try:
    import websockets.sync.client as ws_sync
    import websockets.exceptions
except ImportError as e:
    input(str(e))
    ws_error = True

if ws_error or httpx_error:
    out1 = "Install websockets | py -m pip install websockets" if os.name == "nt" else "Install websockets | pacman -S python-websockets"
    out2 = "Install httpx | py -m pip install httpx" if os.name == "nt" else "Install websockets | pacman -S python-httpx"
    out3 = "Install both httpx and websockets | py -m pip install httpx websockets" if os.name == "nt" else "Install websockets | pacman -S python-websockets and pacman -S python-httpx"
    output = out3 if ws_error and httpx_error else out1 if httpx_error else out2

    print("A fatal error occured during loading")
    print("")
    print(output)
    print("Press enter to exit")
    input()
    exit(1)

TOKEN_FILE = Path.home() / ".roblox_chat_token"
API_BASE = "https://hermivore.cat"
WS_BASE  = "wss://hermivore.cat"
# CHALLENGE_TTL = 30 # im impatient
CHALLENGE_TTL = 60

LOG_DIR = Path.home() / "AppData/Local/Roblox/logs" if os.name == "nt" else Path.home() / ".var/app/org.vinegarhq.Sober/data/sober/sober_logs/"

_RE_UID  = re.compile(r"userid:(\d+)", re.I)
_RE_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)

# exact markers, lowercased for comparison
_JOIN_MARKER = "[flog::output] ! joining game"   # carries the JobId (shared)
_LOAD_MARKER = "gamejoinloadtime"                # carries the userid



def _load_stored_token() -> dict:
    try:
        return json.loads(TOKEN_FILE.read_text())
    except Exception:
        return {}


def _save_stored_token(user_id: int, token: str):
    stored = _load_stored_token()
    stored[str(user_id)] = token
    TOKEN_FILE.write_text(json.dumps(stored))



def find_latest_log() -> Path | None:
    if not LOG_DIR.exists():
        return None
    log_files = [f for f in LOG_DIR.glob("**/*.log") if f.is_file()]
    return max(log_files, key=lambda f: f.stat().st_mtime) if log_files else None

def parse_log_text(text: str) -> tuple[str | None, str | None]:
    """
    Keep the LAST Joining-game JobId and the LAST GameJoinLoadTime userid.
    Last = most recent join = current server / account.
    """
    user_id = None
    server_id = None
    lines = text.split("\n")

    for i, line in enumerate(lines):
        low = line.lower()

        # ── JobId (the shared server id we actually want) ────────────
        if _JOIN_MARKER in low:
            m = _RE_UUID.search(line)
            # some builds put the uuid on the following line; look ahead,
            # but never into a GameJoinLoadTime line (that uuid is the
            # wrong per-client sid)
            if not m and i + 1 < len(lines) \
                    and _LOAD_MARKER not in lines[i + 1].lower():
                m = _RE_UUID.search(lines[i + 1])
            if m:
                server_id = m.group(0).lower()   # normalise case for hashing

        # ── userid ───────────────────────────────────────────────────
        if _LOAD_MARKER in low:
            m = _RE_UID.search(line)
            if m:
                user_id = m.group(1)

    return user_id, server_id


def parse_latest_log() -> tuple[str | None, str | None]:
    path = find_latest_log()
    if path is None:
        return None, None
    try:
        return parse_log_text(path.read_text(errors="replace"))
    except Exception:
        return None, None
    
class ChatClient:
    def __init__(self, server_id: str, user_id: int):
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

        stored = _load_stored_token()
        self.client_token = stored.get(str(user_id))

    # ── handshake ────────────────────────────────────────────────────

    def connect(self) -> bool:
        data = self._handshake(client_token=self.client_token)
        if data is None:
            return False

        self.verified    = data.get("verified", False)
        self.verify_code = data.get("verify_code")

        # ── store the persistent token if we got one ─────────────────────
        if "client_token" in data:
            self.client_token = data["client_token"]
            _save_stored_token(self.user_id, self.client_token)

        self.name    = data["name"]
        self.room_id = data["room_id"]
        self.token   = data["ws_token"]

        # open websocket
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

            try:
                self._ws.close()
            except Exception:
                pass

            # use _handshake so client_token is sent
            data = self._handshake(client_token=self.client_token)
            if data is None or data.get("error"):
                continue

            # handle re-verification if we have a token now
            if "client_token" in data:
                self.client_token = data["client_token"]
                _save_stored_token(self.user_id, self.client_token)

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
        if client_token:
            body["client_token"] = client_token
        if action:
            body["action"] = action

        try:
            resp = httpx.post(
                f"{API_BASE}/api/roblox/chat/{self.server_id}",
                json=body,
                timeout=10,
            )
            return resp.json()
        except Exception as e:
            print(f"Handshake failed: {e}")
            return None

    # ── background loops ─────────────────────────────────────────────

    def _watch_logs(self, interval: float = 3.0):
        last_path: Path | None = None
        last_size: int = 0

        while self._running:
            time.sleep(interval)

            path = find_latest_log()
            if path is None:
                continue

            try:
                size = path.stat().st_size
            except OSError:
                continue

            # nothing changed — same file, same size
            if path == last_path and size == last_size:
                continue

            last_path = path
            last_size = size

            # something changed — re-parse
            try:
                text = path.read_text(errors="replace")
            except Exception:
                continue

            new_uid, new_sid = parse_log_text(text)

            # log not ready yet (no join recorded)
            if new_sid is None:
                continue

            # same server, nothing to do
            if new_sid == self.server_id:
                continue

            # ── server changed ───────────────────────────────────────────
            print(f"Server change: {self.server_id} → {new_sid}")

            # account switch within the same client session
            if new_uid and new_uid != str(self.user_id):
                self.user_id = int(new_uid)
                stored = _load_stored_token()
                self.client_token = stored.get(str(self.user_id))
                print(f"Account change: user_id → {self.user_id}")

            self.server_id = new_sid

            # notify overlay, then kill socket → _reconnect handles the rest
            self._recv_queue.put({"type": "clear"})
            self._recv_queue.put({
                "type": "system",
                "text": "Switching server…",
                "ts": time.time(),
            })

            try:
                self._ws.close()
            except Exception:
                pass

    def _recv_loop(self):
        while self._running:
            try:
                raw = self._ws.recv(timeout=60)
            except TimeoutError:
                continue                        # quiet chat, just loop
            except websockets.exceptions.ConnectionClosed:
                break                           # actual disconnect
            except Exception:
                break

            try:
                msg = json.loads(raw)
                self._recv_queue.put(msg)
            except json.JSONDecodeError:
                continue

        # fell out of the loop → try to reconnect
        if self._running:
            self._recv_queue.put({"type": "system", "text": "Reconnecting…", "ts": time.time()})
            self._reconnect()

    def _send_loop(self):
        while self._running:
            try:
                item = self._send_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                if isinstance(item, str):
                    self._ws.send(json.dumps({"type": "text", "text": item}))
                else:
                    self._ws.send(json.dumps(item))
            except Exception:
                pass

    # ── public API ───────────────────────────────────────────────────

    def send(self, text: str):
        if self._running:
            self._send_queue.put(text)

    def send_raw(self, payload: dict):
        if self._running:
            self._send_queue.put(payload)


    def poll(self) -> list[dict]:
        """Drain all pending received messages. Call from your UI loop."""
        msgs = []
        while not self._recv_queue.empty():
            try:
                msgs.append(self._recv_queue.get_nowait())
            except queue.Empty:
                break
        return msgs

    def disconnect(self):
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass


# ── tkinter overlay ──────────────────────────────────────────────────

class ChatOverlay:
    def __init__(self, client: ChatClient):
        self.client = client
        self.root = tk.Tk()
        self.root.title("Chat")
        self.root.geometry("580x450")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)
        self.root.configure(bg="#1e1e2e")

        self._vk_banner = None
        self._vk_frame = None
        self._vk_target = None
        self._vk_deadline = None

        # ── verification banner ──────────────────────────────────────
        self.banner = None
        self._banner_deadline = None

        if not client.verified and client.verify_code:
            self._banner_deadline = time.time() + CHALLENGE_TTL
            self.banner = tk.Label(
                self.root,
                bg="#45475a",
                fg="#f9e2af",
                font=("Consolas", 9),
                anchor="w",
                padx=6,
                pady=2,
            )
            self.banner.pack(fill=tk.X, padx=4, pady=(4, 0))
            self._tick_banner()


        # message display
        self.display = scrolledtext.ScrolledText(
            self.root,
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg="#1e1e2e",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            font=("Consolas", 10),
            relief=tk.FLAT,
            padx=8,
            pady=8,
        )
        self.display.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))

        # tag colours
        self.display.tag_configure("system", foreground="#a6adc8", font=("Consolas", 9, "italic"))
        self.display.tag_configure("name",   foreground="#89b4fa", font=("Consolas", 10, "bold"))
        self.display.tag_configure("verified", foreground="#a6e3a1", font=("Consolas", 10, "bold"))
        self.display.tag_configure("error",  foreground="#f38ba8")

        # input
        frame = tk.Frame(self.root, bg="#1e1e2e")
        frame.pack(fill=tk.X, padx=4, pady=4)

        self.entry = tk.Entry(
            frame,
            bg="#313244",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            font=("Consolas", 10),
            relief=tk.FLAT,
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        self.entry.bind("<Return>", self._on_send)

        send_btn = tk.Button(
            frame,
            text="Send",
            command=self._on_send,
            bg="#89b4fa",
            fg="#1e1e2e",
            relief=tk.FLAT,
            font=("Consolas", 9, "bold"),
        )
        self.send_btn = send_btn
        send_btn.pack(side=tk.RIGHT, padx=(4, 0), ipady=2)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_send(self, event=None):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)

        if text.lower().startswith("/votekick"):
            self._handle_votekick(text)
            return

        self.client.send(text)

    def _append(self, msg: dict):
        self.display.configure(state=tk.NORMAL)

        mtype = msg.get("type")

        if mtype == "system":
            self.display.insert(tk.END, f"  {msg['text']}\n", "system")

        elif mtype == "error":
            self.display.insert(tk.END, f"  ⚠ {msg['text']}\n", "error")

        elif mtype == "chat":
            ts = time.strftime("%H:%M", time.localtime(msg.get("ts", 0)))
            self.display.insert(tk.END, f"[{ts}] ", "system")
            self.display.insert(tk.END, f"{msg['name']}", "name")
            if msg.get("verified"):
                self.display.insert(tk.END, " ✓", "verified")
            self.display.insert(tk.END, f": {msg['text']}\n")

        elif mtype == "clear":
            self.display.configure(state=tk.NORMAL)
            self.display.delete("1.0", tk.END)
            self.display.configure(state=tk.DISABLED)
            return
        
        elif mtype == "history":
            for m in msg.get("messages", []):
                self._append(m)
            self.display.configure(state=tk.DISABLED)
            return

        elif mtype == "votekick_init":
            self._show_votekick(msg)

        elif mtype == "votekick_update":
            self._update_votekick(msg)

        elif mtype == "votekick_result":
            self._resolve_votekick(msg)
            # also show it in the chat log
            target = msg.get("target", "?")
            if msg.get("result") == "kicked":
                self.display.insert(tk.END, f"  {target} was votekicked\n", "system")
            else:
                self.display.insert(tk.END, f"  votekick on {target} expired\n", "system")

        self.display.configure(state=tk.DISABLED)
        self.display.see(tk.END)

    def _tick_banner(self):
        """Update countdown every second. At zero, attempt verification."""
        if self.banner is None:
            return

        remaining = self._banner_deadline - time.time()

        if remaining > 0:
            mins, secs = divmod(int(remaining), 60)
            self.banner.configure(
                text=f"Unverified — add to bio, in order: {self.client.verify_code}  ({mins}:{secs:02d})"
            )
            self.root.after(1000, self._tick_banner)
            return

        # time's up — try to verify in a background thread
        # (don't block tkinter's main thread with an HTTP call)
        self.banner.configure(text="Verifying…")
        threading.Thread(target=self._attempt_verify, daemon=True).start()

    def _attempt_verify(self):
        """
        Runs in a background thread.
        Asks the server to check the bio.
        If verified: save token, kill WS, let _reconnect handle the rest.
        If not: show expired notice on the main thread, then remove banner.
        """
        data = self.client._handshake(action="verify")

        if data and data.get("client_token"):
            # success — save the persistent token
            self.client.client_token = data["client_token"]
            self.client.verified = True
            _save_stored_token(self.client.user_id, data["client_token"])

            # update banner on the main thread, then trigger reconnect
            self.root.after(0, self._banner_verified)

            # kill the WS — recv_loop will call _reconnect,
            # which now sends client_token and gets a verified WS token
            try:
                self.client._ws.close()
            except Exception:
                pass
        else:
            # failed — show expired on the main thread
            self.root.after(0, self._banner_expired)

    def _banner_verified(self):
        if self.banner:
            self.banner.configure(text="Verified ✓  Reconnecting…", fg="#a6e3a1")
            # remove banner after 3 seconds
            self.root.after(3000, self._destroy_banner)

    def _banner_expired(self):
        if self.banner:
            self.banner.configure(
                text="Verification expired — reconnect to try again",
                fg="#f38ba8",
            )
            # remove banner after 5 seconds
            self.root.after(5000, self._destroy_banner)

    def _destroy_banner(self):
        if self.banner:
            self.banner.destroy()
            self.banner = None

    def _poll(self):
        for msg in self.client.poll():
            self._append(msg)
        self.root.after(50, self._poll)   # 20 fps poll

    def _on_close(self):
        self.client.disconnect()
        self.root.destroy()

    def _handle_votekick(self, text: str):
        parts = text.split(maxsplit=2)   # ["/votekick", "TargetName", "reason..."]
        if len(parts) < 2:
            self._append({
                "type": "error",
                "text": "Usage: /votekick <name> [reason]",
            })
            return

        target_name = parts[1]
        reason = parts[2] if len(parts) > 2 else ""

        # if a votekick is already showing for this target, just vote
        if self._vk_frame and self._vk_target == target_name.lower():
            self.client.send_raw({
                "type": "votekick_vote",
                "target_name": target_name,
            })
        else:
            self.client.send_raw({
                "type": "votekick_init",
                "target_name": target_name,
                "reason": reason,
            })

    def _show_votekick(self, msg: dict):
        """Create or update the votekick banner."""
        target = msg["target"]
        self._vk_target = target.lower()
        self._vk_deadline = msg.get("deadline", time.time() + 60)

        initiator = msg.get("initiator", "?")
        reason = msg.get("reason")
        votes = msg.get("votes", 0)
        needed = msg.get("needed", 3)

        reason_text = f' for "{reason}"' if reason else ""
        info = f'{initiator} initiated a votekick on {target}{reason_text}'
        instruction = f"Votes: {votes}/{needed}  —  /votekick {target} to vote"

        if self._vk_frame is None:
            self._vk_frame = tk.Frame(self.root, bg="#45475a")
            # pack it right after the verification banner / before the display
            self._vk_frame.pack(fill=tk.X, padx=4, pady=(2, 0),
                                before=self.display)

            self._vk_info = tk.Label(
                self._vk_frame, text=info,
                bg="#45475a", fg="#fab387",
                font=("Consolas", 9, "bold"),
                anchor="w", padx=6,
            )
            self._vk_info.pack(fill=tk.X)

            self._vk_status = tk.Label(
                self._vk_frame, text=instruction,
                bg="#45475a", fg="#f9e2af",
                font=("Consolas", 9),
                anchor="w", padx=6,
            )
            self._vk_status.pack(fill=tk.X)

            btn_frame = tk.Frame(self._vk_frame, bg="#45475a")
            btn_frame.pack(fill=tk.X, padx=6, pady=(0, 4))

            self._vk_vote_btn = tk.Button(
                btn_frame, text="Vote Yes",
                command=lambda: self.client.send_raw({
                    "type": "votekick_vote",
                    "target_name": target,
                }),
                bg="#f38ba8", fg="#1e1e2e",
                relief=tk.FLAT, font=("Consolas", 9, "bold"),
            )
            self._vk_vote_btn.pack(side=tk.LEFT)

            self._vk_timer_label = tk.Label(
                btn_frame, text="", bg="#45475a", fg="#a6adc8",
                font=("Consolas", 9),
            )
            self._vk_timer_label.pack(side=tk.RIGHT)

            self._tick_votekick()
        else:
            self._vk_info.configure(text=info)
            self._vk_status.configure(text=instruction)

    def _tick_votekick(self):
        if self._vk_frame is None or self._vk_deadline is None:
            return
        remaining = self._vk_deadline - time.time()
        if remaining <= 0:
            return  # the server will send votekick_result shortly
        self._vk_timer_label.configure(text=f"{int(remaining)}s")
        self.root.after(1000, self._tick_votekick)

    def _update_votekick(self, msg: dict):
        if self._vk_frame is None:
            return
        votes = msg.get("votes", 0)
        needed = msg.get("needed", 3)
        target = msg.get("target", "?")
        self._vk_status.configure(
            text=f"Votes: {votes}/{needed}  —  /votekick {target} to vote"
        )

    def _resolve_votekick(self, msg: dict):
        result = msg.get("result")
        target = msg.get("target", "?")

        if self._vk_frame:
            if result == "kicked":
                self._vk_info.configure(
                    text=f"{target} was votekicked", fg="#a6e3a1"
                )
            else:
                self._vk_info.configure(
                    text=f"Votekick on {target} expired", fg="#a6adc8"
                )
            self._vk_status.configure(text="")
            self._vk_vote_btn.configure(state=tk.DISABLED)
            # remove after 4 seconds
            self.root.after(4000, self._destroy_votekick)

    def _destroy_votekick(self):
        if self._vk_frame:
            self._vk_frame.destroy()
            self._vk_frame = None
            self._vk_target = None
            self._vk_deadline = None

    def run(self):
        self.root.after(50, self._poll)
        self.root.mainloop()


# ── entrypoint ───────────────────────────────────────────────────────

if __name__ == "__main__":
    user_id, server_id = parse_latest_log()

    if server_id is None:
        input("No active Roblox session found. Make sure Roblox is running. Press enter to exit.")
        exit(1)

    print(f"Detected user {user_id} in server {server_id}")

    client = ChatClient(server_id, int(user_id))
    if not client.connect():
        input("Failed to connect. Press enter to exit.")
        exit(1)

    print(f"Connected as {client.name} → room {client.room_id}")

    overlay = ChatOverlay(client)
    overlay.run()
