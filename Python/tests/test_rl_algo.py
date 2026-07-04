"""rl_algo contract tests (I3, G3, G4) + config.yaml consistency.

sb3-contrib-dependent cases skip until the smoke agent installs it;
their inverses (missing-contrib SystemExit) run only while it is absent.
"""

import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

_PY_DIR = Path(__file__).resolve().parents[1]
for _p in (str(_PY_DIR), str(_PY_DIR / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rl_algo
from env_stubs import TinyEnv, MaskStubEnv

HAS_SB3_CONTRIB = importlib.util.find_spec("sb3_contrib") is not None


def _fake_sb3_zip(path: str, data_text: str, member: str = "data"):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(member, data_text)


class TestConstants(unittest.TestCase):
    def test_heartbeat_noop_action(self):
        self.assertEqual(rl_algo.HEARTBEAT_NOOP_ACTION, -1)


class TestResolveAlgo(unittest.TestCase):
    def test_ppo_and_normalization(self):
        from stable_baselines3 import PPO
        for raw in ("PPO", "ppo", "Ppo"):
            cls, name, maskable = rl_algo.resolve_algo(
                {"training": {"algorithm": raw}}
            )
            self.assertIs(cls, PPO)
            self.assertEqual(name, "PPO")
            self.assertFalse(maskable)

    def test_default_is_ppo(self):
        _, name, maskable = rl_algo.resolve_algo({})
        self.assertEqual(name, "PPO")
        self.assertFalse(maskable)

    def test_unknown_algorithm_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            rl_algo.resolve_algo({"training": {"algorithm": "DQN"}})
        msg = str(ctx.exception)
        self.assertIn("PPO", msg)
        self.assertIn("MaskablePPO", msg)

    @unittest.skipUnless(HAS_SB3_CONTRIB, "sb3-contrib not installed yet")
    def test_maskable_variants(self):
        from sb3_contrib import MaskablePPO
        for raw in ("MaskablePPO", "maskable_ppo", "MASKABLE-PPO"):
            cls, name, maskable = rl_algo.resolve_algo(
                {"training": {"algorithm": raw}}
            )
            self.assertIs(cls, MaskablePPO)
            self.assertEqual(name, "MaskablePPO")
            self.assertTrue(maskable)

    @unittest.skipIf(HAS_SB3_CONTRIB, "sb3-contrib installed; hint path dead")
    def test_maskable_without_contrib_exits_with_install_hint(self):
        with self.assertRaises(SystemExit) as ctx:
            rl_algo.resolve_algo({"training": {"algorithm": "MaskablePPO"}})
        self.assertIn("sb3-contrib", str(ctx.exception))


class TestCheckpointSniffing(unittest.TestCase):
    """G3: 'data' zip member substring check is the only discriminator."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _p(self, name):
        return os.path.join(self.tmp.name, name)

    def test_maskable_marker_detected(self):
        path = self._p("maskable.zip")
        _fake_sb3_zip(path, json.dumps(
            {"policy_class": "sb3_contrib.common.maskable.policies."
                             "MaskableActorCriticPolicy"}
        ))
        self.assertTrue(rl_algo.checkpoint_is_maskable(path))

    def test_legacy_ppo_not_maskable(self):
        path = self._p("legacy.zip")
        _fake_sb3_zip(path, json.dumps(
            {"policy_class": "stable_baselines3.common.policies."
                             "ActorCriticPolicy"}
        ))
        self.assertFalse(rl_algo.checkpoint_is_maskable(path))

    def test_missing_file_false(self):
        self.assertFalse(rl_algo.checkpoint_is_maskable(self._p("nope.zip")))

    def test_not_a_zip_false(self):
        path = self._p("garbage.zip")
        with open(path, "wb") as f:
            f.write(b"not a zip at all")
        self.assertFalse(rl_algo.checkpoint_is_maskable(path))

    def test_zip_without_data_member_false(self):
        path = self._p("nodata.zip")
        _fake_sb3_zip(path, "MaskableActorCriticPolicy", member="other")
        self.assertFalse(rl_algo.checkpoint_is_maskable(path))


class TestFindLatestCheckpoint(unittest.TestCase):
    def test_empty_dir_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(rl_algo.find_latest_checkpoint(d))

    def test_newest_by_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            older = os.path.join(d, "boss_ppo_1000_steps.zip")
            newer = os.path.join(d, "autosave_on_exit.zip")
            other = os.path.join(d, "notes.txt")
            for p in (older, newer, other):
                with open(p, "wb") as f:
                    f.write(b"x")
            now = time.time()
            os.utime(older, (now - 100, now - 100))
            os.utime(newer, (now, now))
            self.assertEqual(rl_algo.find_latest_checkpoint(d), newer)


class TestCheckpointRoundtrip(unittest.TestCase):
    """Real SB3 save -> sniff -> load_checkpoint_auto (slowest tests here)."""

    def test_ppo_roundtrip_loads_as_legacy(self):
        from stable_baselines3 import PPO
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ppo_ckpt.zip")
            model = PPO("MlpPolicy", TinyEnv(), n_steps=8, batch_size=8,
                        device="cpu")
            model.save(path)
            self.assertFalse(rl_algo.checkpoint_is_maskable(path))
            loaded, mask_aware = rl_algo.load_checkpoint_auto(
                path, env=None, device="cpu"
            )
            self.assertFalse(mask_aware)
            self.assertEqual(loaded.__class__.__name__, "PPO")

    @unittest.skipUnless(HAS_SB3_CONTRIB, "sb3-contrib not installed yet")
    def test_maskable_roundtrip_loads_as_maskable(self):
        from sb3_contrib import MaskablePPO
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "maskable_ckpt.zip")
            env = rl_algo.wrap_action_masker(MaskStubEnv())
            model = MaskablePPO("MlpPolicy", env, n_steps=8, batch_size=8,
                                device="cpu")
            model.save(path)
            self.assertTrue(rl_algo.checkpoint_is_maskable(path))
            loaded, mask_aware = rl_algo.load_checkpoint_auto(
                path, env=None, device="cpu"
            )
            self.assertTrue(mask_aware)
            self.assertEqual(loaded.__class__.__name__, "MaskablePPO")


@unittest.skipUnless(HAS_SB3_CONTRIB, "sb3-contrib not installed yet")
class TestWrapActionMasker(unittest.TestCase):
    """G2: mask fn goes through env.unwrapped, never getattr forwarding."""

    def test_mask_reaches_base_env_through_plain_wrapper(self):
        import gymnasium as gym
        import numpy as np
        from sb3_contrib.common.wrappers import ActionMasker

        base = MaskStubEnv()
        base.mask = np.array([1, 0, 1, 1, 0], dtype=bool)
        # gymnasium 1.2.x plain Wrapper does NOT forward action_masks —
        # exactly the situation wrap_action_masker must survive
        wrapped = rl_algo.wrap_action_masker(gym.Wrapper(base))
        self.assertIsInstance(wrapped, ActionMasker)
        np.testing.assert_array_equal(
            wrapped.action_masks(), np.array([1, 0, 1, 1, 0], dtype=bool)
        )


class TestConfigContract(unittest.TestCase):
    """config.yaml keys the upgrade relies on (CORE 2.5)."""

    def setUp(self):
        import yaml
        with open(_PY_DIR / "config.yaml", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)

    def test_training_algorithm_valid(self):
        algo = self.cfg["training"].get("algorithm", "PPO")
        self.assertIn(algo, ("PPO", "MaskablePPO"))

    def test_env_heartbeat_default_off(self):
        self.assertEqual(
            float(self.cfg["env"].get("heartbeat_interval", 0.0)), 0.0
        )

    def test_training_device_explicit(self):
        self.assertIn("device", self.cfg["training"])

    def test_resolve_algo_accepts_shipped_config(self):
        algo = self.cfg["training"].get("algorithm", "PPO")
        if algo == "MaskablePPO" and not HAS_SB3_CONTRIB:
            self.skipTest("shipped algo needs sb3-contrib (smoke installs)")
        _, name, _ = rl_algo.resolve_algo(self.cfg)
        self.assertEqual(name, algo)


if __name__ == "__main__":
    unittest.main()
