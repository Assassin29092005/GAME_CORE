"""Self-test of the I8 mock bridge protocol (raw sockets, no BossEnv)."""

import json
import socket
import sys
import time
import unittest
from pathlib import Path

_PY_DIR = Path(__file__).resolve().parents[1]
for _p in (str(_PY_DIR), str(_PY_DIR / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mock_ue_server import MockUEServer, OBS_KEYS


# Per-socket receive buffer: one recv() can deliver SEVERAL newline-delimited
# lines in a single TCP segment (e.g. an injected reward line + the obs line);
# the leftover must survive between _read_line calls or line 2 is lost and the
# next read times out.
_rx_buffers: dict[socket.socket, str] = {}


def _read_line(sock: socket.socket, timeout: float = 2.0) -> str:
    sock.settimeout(timeout)
    buf = _rx_buffers.get(sock, "")
    while "\n" not in buf:
        chunk = sock.recv(4096).decode("utf-8")
        if not chunk:
            raise ConnectionError("server closed connection")
        buf += chunk
    line, _rx_buffers[sock] = buf.split("\n", 1)
    return line


def _assert_no_data(testcase, sock: socket.socket, wait: float = 0.3):
    leftover = _rx_buffers.get(sock, "")
    if leftover.strip():
        testcase.fail(f"expected silence, got buffered: {leftover!r}")
    sock.settimeout(wait)
    try:
        chunk = sock.recv(4096)
        testcase.fail(f"expected silence, got: {chunk!r}")
    except socket.timeout:
        pass  # correct: no reply


class TestMockProtocol(unittest.TestCase):
    def setUp(self):
        _rx_buffers.clear()  # don't leak buffered lines across tests
        self.server = MockUEServer().start()
        self.client = socket.create_connection(("127.0.0.1", self.server.port))

    def tearDown(self):
        try:
            self.client.close()
        except OSError:
            pass
        self.server.stop()

    def _send(self, payload: dict | str):
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        self.client.sendall((raw + "\n").encode("utf-8"))

    def test_set_player_id_no_reply(self):
        self._send({"command": "set_player_id", "player_id": "rusher"})
        _assert_no_data(self, self.client)
        self.assertTrue(
            self.server.wait_for(lambda s: s.player_ids == ["rusher"])
        )

    def test_reset_returns_exactly_one_obs_with_required_keys(self):
        self._send({"command": "reset"})
        obs = json.loads(_read_line(self.client))
        self.assertEqual(set(obs.keys()), OBS_KEYS)
        # I8 field shapes/types
        self.assertEqual(len(obs["hero_vel"]), 3)
        self.assertEqual(len(obs["profile"]), 8)
        self.assertEqual(obs["emotion"], [0.0, 0.0, 0.0])  # C++ stub zeros
        self.assertEqual(len(obs["mask"]), 5)
        self.assertTrue(all(isinstance(v, int) for v in obs["mask"]))
        self.assertIsInstance(obs["hero_attacking"], bool)
        _assert_no_data(self, self.client)  # exactly ONE line

    def test_observe_returns_one_obs(self):
        self._send({"command": "observe"})
        obs = json.loads(_read_line(self.client))
        self.assertIn("boss_hp", obs)
        _assert_no_data(self, self.client)

    def test_action_recorded_never_replied(self):
        self._send({"action": 2})
        self._send({"action": -1})  # heartbeat no-op: recorded, no reply
        self.assertTrue(self.server.wait_for(lambda s: s.actions == [2, -1]))
        _assert_no_data(self, self.client)

    def test_action_dispatched_before_command_in_same_message(self):
        self._send({"command": "observe", "action": 1})
        obs = json.loads(_read_line(self.client))
        self.assertIn("boss_hp", obs)
        self.assertTrue(self.server.wait_for(lambda s: len(s.dispatch_log) >= 2))
        self.assertEqual(
            self.server.dispatch_log, [("action", 1), ("command", "observe")]
        )
        _assert_no_data(self, self.client)  # only the one obs

    def test_unknown_command_and_garbage_silently_dropped(self):
        self._send({"command": "does_not_exist"})
        self._send("this is not json")
        self._send({"unrelated_key": 42})
        _assert_no_data(self, self.client)
        # connection still healthy afterwards
        self._send({"command": "observe"})
        obs = json.loads(_read_line(self.client))
        self.assertIn("boss_hp", obs)
        self.assertEqual(self.server.malformed_count, 1)

    def test_single_client_served_at_a_time(self):
        second = socket.create_connection(("127.0.0.1", self.server.port))
        try:
            second.sendall(b'{"command": "reset"}\n')
            _assert_no_data(self, second, wait=0.4)  # queued, not served
            # first client still works
            self._send({"command": "observe"})
            json.loads(_read_line(self.client))
        finally:
            second.close()

    def test_inject_lines_flushed_before_next_obs(self):
        self.server.inject_lines.append('{"reward": 3.5}')
        self._send({"command": "observe"})
        first = json.loads(_read_line(self.client))
        second = json.loads(_read_line(self.client))
        self.assertEqual(first, {"reward": 3.5})
        self.assertIn("boss_hp", second)

    def test_reconnect_after_disconnect(self):
        # BossEnv reconnects on every reset() — the mock must accept again.
        self.client.close()
        time.sleep(0.05)
        self.client = socket.create_connection(("127.0.0.1", self.server.port))
        self._send({"command": "reset"})
        obs = json.loads(_read_line(self.client))
        self.assertIn("boss_hp", obs)


if __name__ == "__main__":
    unittest.main()
