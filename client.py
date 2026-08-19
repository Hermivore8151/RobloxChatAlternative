import queue, time, json, httpx, threading
import websockets.sync.client as ws_sync

from typing import Optional

from config import _load_stored_token, _save_stored_token
from log_parser import find_latest_log, parse_log_text
from constants import API_BASE, WS_BASE

class ChatClient:
    def __init__(self, server_id: str, config: dict):
        self.config = config
        self.server_id = server_id
        self.user_id = None
        self.name = None
        self.room_id = None
        self.token = None
        self.verified = False

        self._ws = None
        self._send_queue = queue.Queue()
        self._recv_queue = queue.Queue()
        self._running = False

        self._ws_thread = None
        self._send_thread = None
        self._watcher_thread = None

        stored = _load_stored_token(self.config)
        self.session_token = stored.get("backend_session_jwt")

    def connect(self) -> bool:
        if not self.session_token:
            return False

        data = self._handshake()
        if data is None or data.get("error"):
            if data and "Invalid session" in data.get("reason", ""):
                self.session_token = None
                _save_stored_token(self.config, "backend_session_jwt", None)
            return False

        # The backend now provides these!
        self.user_id = data.get("user_id")
        self.name = data.get("name")
        self.room_id = data.get("room_id")
        self.token = data.get("ws_token")
        self.verified = True

        url = (
            f"{WS_BASE}/api/roblox/chat/room/{self.room_id}"
            f"?token={self.token}&user_id={self.user_id}"
            f"&name={self.name}&verified=1"
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

    def _handshake(self) -> Optional[dict]:
        body = {"session_token": self.session_token}
        try:
            resp = httpx.post(
                f"{API_BASE}/api/roblox/chat/{self.server_id}",
                json=body,
                timeout=10,
            )
            if resp.status_code == 401:
                # Extract the specific reason from the backend!
                data = resp.json()
                return {"error": True, "reason": data.get("reason", "Invalid session")}
            return resp.json()
        except Exception as e:
            print(f"Handshake failed: {e}")
            return None

    def _reconnect(self, retries: int = 5, backoff: float = 2.0):
        for attempt in range(1, retries + 1):
            time.sleep(backoff * attempt)
            try: self._ws.close()
            except: pass

            data = self._handshake()
            if data is None or data.get("error"):
                continue

            self.user_id = data.get("user_id")
            self.name = data.get("name")
            self.room_id = data.get("room_id")
            self.token = data.get("ws_token")

            try:
                # Added verified=1 here to match the new connect() behavior
                url = (
                    f"{WS_BASE}/api/roblox/chat/room/{self.room_id}"
                    f"?token={self.token}&user_id={self.user_id}"
                    f"&name={self.name}&verified=1"
                )
                self._ws = ws_sync.connect(url)
            except Exception:
                continue

            self._recv_queue.put({"type": "system", "text": "Reconnected", "ts": time.time()})
            self._recv_loop()
            return

        self._running = False
        self._recv_queue.put({"type": "system", "text": "Disconnected", "ts": time.time()})

    def _watch_logs(self, interval: float = 3.0):
        last_path = None
        last_size = None

        while self._running:
            time.sleep(interval)
            path = find_latest_log(self.config)
            if path is None: continue
            
            try: size = path.stat().st_size
            except OSError: continue

            if path == last_path and size == last_size: continue
            last_path, last_size = path, size

            try: text = path.read_text(errors="replace", encoding="utf-8")
            except: continue

            # We ONLY care about server_id (Job ID) changes now
            _, new_sid = parse_log_text(text, self.config)

            if new_sid is None or new_sid == self.server_id:
                continue

            self.server_id = new_sid
            self._recv_queue.put({"type": "server_change", "server_id": new_sid, "ts": time.time()})
            self._recv_queue.put({"type": "clear"})
            self._recv_queue.put({"type": "system", "text": "Switching server…", "ts": time.time()})
            
            try: self._ws.close()
            except: pass

    def _recv_loop(self):
        while self._running:
            try:
                raw = self._ws.recv(timeout=60)
            except TimeoutError:
                continue
            except Exception:
                break

            try:
                self._recv_queue.put(json.loads(raw))
            except json.JSONDecodeError:
                continue

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

    def send(self, text: str):
        if self._running:
            self._send_queue.put(text)

    def send_raw(self, payload: dict):
        if self._running:
            self._send_queue.put(payload)

    def poll(self) -> list[dict]:
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