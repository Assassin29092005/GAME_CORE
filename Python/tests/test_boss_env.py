"""BossEnv contract tests against the mock bridge (I1, I2, G4, G5, G6).

Everything here runs offline — no UE editor, no GPU, no sb3-contrib.
"""

import socket
import sys
import threading
import time
import unittest
from pathlib import Path

import numpy as np

_PY_DIR = Path(__file__).resolve().parents[1]
for _p in (str(_PY_DIR), str(_PY_DIR / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from boss_env import BossEnv
from mock_ue_server import MockUEServer


def _make_env(port: int, **kwargs) -> BossEnv:
    defaults = dict(
        host="127.0.0.1", port=port, timeout=5.0, step_delay=0.0, cfg={}
    )
    defaults.update(kwargs)
    return BossEnv(**defaults)


class TestBossEnvBase(unittest.TestCase):
    def setUp(self):
        self.server = MockUEServer().start()
        self.env = None

    def tearDown(self):
        if self.env is not None:
            self.env.close()
        self.server.stop()

    # ------------------------------------------------------------- I1 ---
    def test_action_masks_valid_pre_reset_all_ones(self):
        self.env = _make_env(self.server.port)
        mask = self.env.action_masks()
        self.assertEqual(mask.shape, (5,))
        self.assertEqual(mask.dtype, np.bool_)
        self.assertTrue(mask.all())

    def test_action_masks_returns_a_copy(self):
        self.env = _make_env(self.server.port)
        m = self.env.action_masks()
        m[:] = False
        self.assertTrue(self.env.action_masks().all())

    # ------------------------------------------------------------- G5 ---
    def test_mask_parsed_from_obs(self):
        self.server.mask = [1, 0, 1, 0, 1]
        self.env = _make_env(self.server.port)
        self.env.reset()
        np.testing.assert_array_equal(
            self.env.action_masks(), np.array([1, 0, 1, 0, 1], dtype=bool)
        )

    def test_malformed_short_mask_defaults_all_ones(self):
        self.server.extra_obs_fields = {"mask": [1, 0, 1]}
        self.env = _make_env(self.server.port)
        self.env.reset()
        self.assertTrue(self.env.action_masks().all())

    def test_non_list_mask_defaults_all_ones(self):
        self.server.extra_obs_fields = {"mask": "junk"}
        self.env = _make_env(self.server.port)
        self.env.reset()
        self.assertTrue(self.env.action_masks().all())

    def test_all_zero_mask_defaults_all_ones(self):
        # all-zero would crash MaskablePPO's categorical (G5)
        self.server.mask = [0, 0, 0, 0, 0]
        self.env = _make_env(self.server.port)
        self.env.reset()
        self.assertTrue(self.env.action_masks().all())

    def test_absent_mask_defaults_all_ones(self):
        self.server.omit_fields = {"mask"}
        self.env = _make_env(self.server.port)
        self.env.reset()
        self.assertTrue(self.env.action_masks().all())

    def test_mask_updates_per_step(self):
        self.env = _make_env(self.server.port)
        self.env.reset()
        self.assertTrue(self.env.action_masks().all())
        self.server.mask = [0, 1, 1, 1, 0]
        _, _, _, _, info = self.env.step(0)
        np.testing.assert_array_equal(
            self.env.action_masks(), np.array([0, 1, 1, 1, 0], dtype=bool)
        )
        np.testing.assert_array_equal(
            info["action_mask"], np.array([0, 1, 1, 1, 0], dtype=bool)
        )

    # ------------------------------------------------------------- I2 ---
    def test_step_info_contract_defaults(self):
        self.env = _make_env(self.server.port)
        self.env.reset()
        _, _, _, _, info = self.env.step(3)
        for key in ("boss_hp", "hero_hp", "steps",
                    "action_mask", "exec_action", "dropped_actions", "busy"):
            self.assertIn(key, info)
        self.assertEqual(info["exec_action"], -1)   # absent -> -1 (G6)
        self.assertEqual(info["dropped_actions"], 0)
        self.assertEqual(info["busy"], 0)

    def test_step_info_parses_bridge_telemetry(self):
        self.server.extra_obs_fields = {"exec": 2, "dropped": 3, "busy": 1}
        self.env = _make_env(self.server.port)
        self.env.reset()
        _, _, _, _, info = self.env.step(0)
        self.assertEqual(info["exec_action"], 2)
        self.assertEqual(info["dropped_actions"], 3)
        self.assertEqual(info["busy"], 1)

    # ------------------------------------------------ obs parsing -------
    def test_reset_parses_base_obs(self):
        self.server.reset_restores_hp = False
        self.server.hero_vel = [1.0, 2.0, 3.0]
        self.server.hero_combo = 2
        self.server.hero_attacking = True
        self.server.hero_hp = 0.8
        self.server.dist = 0.4
        self.server.angle = 0.25
        self.server.boss_hp = 0.6
        self.server.profile = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        self.env = _make_env(self.server.port)
        obs, _ = self.env.reset()
        self.assertEqual(obs.shape, (17,))
        np.testing.assert_allclose(obs[0:3], [1.0, 2.0, 3.0])
        self.assertAlmostEqual(float(obs[3]), 2.0)
        self.assertAlmostEqual(float(obs[4]), 1.0)
        self.assertAlmostEqual(float(obs[5]), 0.8, places=5)
        self.assertAlmostEqual(float(obs[6]), 0.4, places=5)
        self.assertAlmostEqual(float(obs[7]), 0.25, places=5)
        self.assertAlmostEqual(float(obs[8]), 0.6, places=5)
        np.testing.assert_allclose(
            obs[9:17], [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8], rtol=1e-5
        )

    def test_termination_on_hero_death(self):
        self.env = _make_env(self.server.port)
        self.env.reset()
        self.server.hero_hp = 0.0
        _, reward, terminated, _, _ = self.env.step(0)
        self.assertTrue(terminated)
        self.assertGreater(reward, 0.0)  # boss-wins terminal bonus

    def test_emotion_dims_parsed_when_enabled(self):
        self.server.emotion = [0.1, 0.2, 0.3]
        self.env = _make_env(
            self.server.port, cfg={"emotion": {"enabled": True}}
        )
        self.assertEqual(self.env.OBS_SIZE, 20)
        obs, _ = self.env.reset()
        np.testing.assert_allclose(obs[17:20], [0.1, 0.2, 0.3], rtol=1e-5)

    def test_hero_action_in_info_when_recording(self):
        self.server.hero_action = 2
        self.env = _make_env(
            self.server.port,
            cfg={"world_model": {"record_player_actions": True}},
        )
        self.env.reset()
        _, _, _, _, info = self.env.step(0)
        self.assertEqual(info["hero_action"], 2)

    # ---------------------------------- unsolicited SendReward defense --
    def test_unsolicited_reward_line_skipped_on_reset(self):
        self.server.inject_lines.append('{"reward": 3.5}')
        self.env = _make_env(self.server.port)
        obs, _ = self.env.reset()
        self.assertAlmostEqual(float(obs[8]), 1.0)  # real obs, not zeros

    def test_unsolicited_reward_line_skipped_mid_episode(self):
        self.env = _make_env(self.server.port)
        self.env.reset()
        self.server.inject_lines.append('{"reward": -1.0}')
        obs, _, terminated, _, _ = self.env.step(1)
        self.assertAlmostEqual(float(obs[8]), 1.0)
        self.assertFalse(terminated)

    def test_obs_carrying_reward_field_is_not_skipped(self):
        # discard rule is (has "reward" AND lacks "boss_hp") — an obs that
        # happens to carry a reward field must still parse
        self.server.reset_restores_hp = False
        self.server.boss_hp = 0.77
        self.server.extra_obs_fields = {"reward": 1.0}
        self.env = _make_env(self.server.port)
        obs, _ = self.env.reset()
        self.assertAlmostEqual(float(obs[8]), 0.77, places=5)

    # ------------------------------------------------- reconnect --------
    def test_reset_twice_reconnects_cleanly(self):
        self.env = _make_env(self.server.port)
        self.env.reset()
        self.env.step(0)
        self.env.reset()  # closes old socket, reconnects
        _, _, _, _, info = self.env.step(1)
        self.assertEqual(info["steps"], 1)


class TestBossEnvHeartbeat(unittest.TestCase):
    """G4: no-op {"action": -1} keeps the C++ 45s watchdog fed."""

    def setUp(self):
        self.server = MockUEServer().start()
        self.env = None

    def tearDown(self):
        if self.env is not None:
            self.env.close()
        self.server.stop()

    def test_default_off(self):
        self.env = _make_env(self.server.port)
        self.env.reset()
        time.sleep(0.4)
        self.assertNotIn(-1, self.server.actions)
        self.assertIsNone(self.env._hb_thread)

    def test_heartbeat_sends_noop_when_idle(self):
        self.env = _make_env(self.server.port, heartbeat_interval=0.2)
        self.env.reset()
        self.assertTrue(
            self.server.wait_for(lambda s: -1 in s.actions, timeout=1.5),
            "heartbeat {'action': -1} never arrived during send silence",
        )
        # the no-op is never replied to, so newline framing stays in sync
        _, _, _, _, info = self.env.step(0)
        self.assertEqual(info["steps"], 1)

    def test_close_stops_heartbeat_thread(self):
        self.env = _make_env(self.server.port, heartbeat_interval=0.2)
        self.env.reset()
        self.assertIsNotNone(self.env._hb_thread)
        self.env.close()
        self.assertTrue(self.env._hb_stop.is_set())
        self.env._hb_thread.join(timeout=1.0)
        self.assertFalse(self.env._hb_thread.is_alive())
        self.env = None  # already closed


class TestBossEnvConnectRetry(unittest.TestCase):
    """_connect retries ConnectionRefusedError (reset-reconnect race)."""

    def test_reset_succeeds_when_server_comes_up_late(self):
        # reserve a free port, then start the server on it 0.6s later —
        # inside the retry window (0.5s + 1.0s backoffs)
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        server = MockUEServer(port=port)
        starter = threading.Timer(0.6, server.start)
        starter.start()
        env = _make_env(port)
        try:
            obs, _ = env.reset()
            self.assertEqual(obs.shape, (17,))
        finally:
            starter.cancel()
            env.close()
            server.stop()

    def test_gives_up_after_three_attempts(self):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        env = _make_env(port)
        with self.assertRaises(ConnectionRefusedError):
            env.reset()
        env.close()


if __name__ == "__main__":
    unittest.main()
