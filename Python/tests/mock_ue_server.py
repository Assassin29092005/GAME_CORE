"""Mock UE RLBridge TCP server for offline testing (interface I8).

Speaks exactly the bridge protocol (brief 0/2):
  - newline-delimited JSON (NDJSON); single client served at a time
  - "action" and "command" are MUTUALLY EXCLUSIVE per line: the real
    RLBridgeComponent::ProcessMessage returns immediately after handling
    an "action" field, so a combined {"action": n, "command": "observe"}
    line dispatches the action and SILENTLY DROPS the command (no reply)
  - {"action": n}                      -> recorded, never replied to
                                          (includes the -1 heartbeat no-op)
  - {"command": "reset"}               -> exactly one observation line
  - {"command": "observe"}             -> exactly one observation line
  - {"command": "set_player_id", ...}  -> recorded, no reply
  - unknown commands / malformed JSON  -> silently dropped

Observation JSON keys (exactly, unless a test overrides/omits):
  hero_vel[3], hero_combo, hero_attacking (bool), hero_hp, dist, angle,
  boss_hp, profile[8], hero_action, emotion[3] (zeros — the C++ stub sends
  zeros), mask[5 ints].

Test hooks (all safe to set between steps; guarded by an internal lock):
  .mask              5-int legal-action mask sent with every obs
  .extra_obs_fields  dict merged over the base obs (override mask with a
                     malformed value, add "exec"/"dropped"/"busy", etc.)
  .omit_fields       set of obs keys to drop before sending
  .inject_lines      raw lines flushed to the client BEFORE the next obs
                     (e.g. an unsolicited {"reward": ...} SendReward payload)
  .received / .actions / .commands / .player_ids / .dispatch_log
  .wait_for(predicate, timeout)

Run the suite from the Python dir:
  venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import socket
import threading
import time


OBS_KEYS = {
    "hero_vel", "hero_combo", "hero_attacking", "hero_hp", "dist", "angle",
    "boss_hp", "profile", "hero_action", "emotion", "mask",
}


class MockUEServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self._requested_port = port
        self.port: int | None = None  # assigned in start()

        # --- Scriptable observation state ---
        self.hero_vel = [0.0, 0.0, 0.0]
        self.hero_combo = 0
        self.hero_attacking = False
        self.hero_hp = 1.0
        self.dist = 0.5
        self.angle = 0.0
        self.boss_hp = 1.0
        self.profile = [0.5] * 8
        self.hero_action = 5  # 5 = idle/none (BossEnv default)
        self.emotion = [0.0, 0.0, 0.0]  # C++ stub sends constant zeros
        self.mask = [1, 1, 1, 1, 1]
        self.reset_restores_hp = True

        # --- Test hooks ---
        self.extra_obs_fields: dict = {}
        self.omit_fields: set = set()
        self.inject_lines: list[str] = []

        # --- Records (inspect from tests) ---
        self.received: list[dict] = []      # every parsed JSON message
        self.actions: list[int] = []        # every {"action": n} payload
        self.commands: list[str] = []       # every {"command": ...} payload
        self.player_ids: list[str] = []     # every set_player_id payload
        self.dispatch_log: list[tuple] = [] # ("action", n) / ("command", name) in dispatch order
        self.malformed_count = 0
        self.obs_sent = 0

        self._lock = threading.Lock()
        self._listen_sock: socket.socket | None = None
        self._conn: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    # ------------------------------------------------------------------ #
    def start(self) -> "MockUEServer":
        self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen_sock.bind((self.host, self._requested_port))
        self._listen_sock.listen(1)  # single client; extras queue in backlog
        self.port = self._listen_sock.getsockname()[1]
        self._running = True
        self._thread = threading.Thread(target=self._serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._running = False
        for s in (self._conn, self._listen_sock):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        self._conn = None
        self._listen_sock = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> "MockUEServer":
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def wait_for(self, predicate, timeout: float = 2.0) -> bool:
        """Poll until predicate(self) is truthy or timeout elapses."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if predicate(self):
                    return True
            time.sleep(0.01)
        return False

    # ------------------------------------------------------------------ #
    def _serve_forever(self):
        # One client at a time; when it disconnects (BossEnv reconnects on
        # every reset()), loop back to accept the next connection.
        while self._running:
            try:
                conn, _ = self._listen_sock.accept()
            except OSError:
                return  # listen socket closed by stop()
            self._conn = conn
            try:
                self._serve_client(conn)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
                if self._conn is conn:
                    self._conn = None

    def _serve_client(self, conn: socket.socket):
        buffer = ""
        while self._running:
            try:
                chunk = conn.recv(4096).decode("utf-8")
            except (ConnectionResetError, ConnectionAbortedError, OSError):
                return
            if not chunk:
                return  # client disconnected
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if line.strip():
                    self._dispatch_line(conn, line)

    def _dispatch_line(self, conn: socket.socket, line: str):
        try:
            msg = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            with self._lock:
                self.malformed_count += 1
            return  # malformed -> silently dropped
        if not isinstance(msg, dict):
            with self._lock:
                self.malformed_count += 1
            return

        with self._lock:
            self.received.append(msg)

        # Mirrors RLBridgeComponent::ProcessMessage: an "action" field is
        # handled first and the bridge RETURNS immediately — a "command" on
        # the same line is silently dropped (no observation reply). Keeping
        # that early-return here means a client that bundles action+observe
        # into one line hangs against the mock exactly as it would vs UE.
        if "action" in msg:
            with self._lock:
                self.actions.append(int(msg["action"]))
                self.dispatch_log.append(("action", int(msg["action"])))
            return  # never a reply — includes the -1 heartbeat no-op

        if "command" in msg:
            cmd = msg["command"]
            with self._lock:
                self.commands.append(cmd)
                self.dispatch_log.append(("command", cmd))
            if cmd == "reset":
                with self._lock:
                    if self.reset_restores_hp:
                        self.hero_hp = 1.0
                        self.boss_hp = 1.0
                self._send_observation(conn)
            elif cmd == "observe":
                self._send_observation(conn)
            elif cmd == "set_player_id":
                with self._lock:
                    self.player_ids.append(msg.get("player_id", ""))
                # no reply
            # unknown command -> silently dropped

    def _send_observation(self, conn: socket.socket):
        with self._lock:
            obs = {
                "hero_vel": list(self.hero_vel),
                "hero_combo": self.hero_combo,
                "hero_attacking": bool(self.hero_attacking),
                "hero_hp": self.hero_hp,
                "dist": self.dist,
                "angle": self.angle,
                "boss_hp": self.boss_hp,
                "profile": list(self.profile),
                "hero_action": self.hero_action,
                "emotion": list(self.emotion),
                "mask": [int(v) for v in self.mask],
            }
            obs.update(self.extra_obs_fields)
            for key in self.omit_fields:
                obs.pop(key, None)
            pre_lines = [
                l if l.endswith("\n") else l + "\n" for l in self.inject_lines
            ]
            self.inject_lines = []
            self.obs_sent += 1
        for raw in pre_lines:
            conn.sendall(raw.encode("utf-8"))
        conn.sendall((json.dumps(obs) + "\n").encode("utf-8"))
