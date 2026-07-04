"""Wrapper contract tests: ConstrainedBossEnv (EXT 3.4) and
HierarchicalBossEnv (EXT 3.1) — mask pass-through, legal-only epsilon,
epsilon_substituted info key, strategy-reward history off-by-one fix.

All in-process against env_stubs — no sockets, no SB3 models.
"""

import sys
import unittest
from pathlib import Path

import gymnasium as gym
import numpy as np

_PY_DIR = Path(__file__).resolve().parents[1]
for _p in (str(_PY_DIR), str(_PY_DIR / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hierarchical_env
from constrained_wrapper import ConstrainedBossEnv
from hierarchical_env import HierarchicalBossEnv
from env_stubs import TinyEnv, MaskStubEnv


class TestConstrainedMasking(unittest.TestCase):
    def test_action_masks_passthrough(self):
        base = MaskStubEnv()
        base.mask = np.array([1, 0, 1, 0, 1], dtype=bool)
        env = ConstrainedBossEnv(base)
        np.testing.assert_array_equal(env.action_masks(), base.mask)

    def test_action_masks_fallback_all_ones(self):
        env = ConstrainedBossEnv(TinyEnv())  # base has no action_masks
        self.assertTrue(env.action_masks().all())
        self.assertEqual(env.action_masks().shape, (5,))

    def test_suboptimal_action_samples_legal_only(self):
        base = MaskStubEnv()
        base.mask = np.array([1, 0, 0, 1, 0], dtype=bool)
        env = ConstrainedBossEnv(base)
        for _ in range(50):
            # legal \ {chosen}: only 3 remains
            self.assertEqual(env._suboptimal_action(0), 3)

    def test_suboptimal_action_empty_alternatives_keeps_original(self):
        base = MaskStubEnv()
        base.mask = np.array([1, 0, 0, 0, 0], dtype=bool)
        env = ConstrainedBossEnv(base)
        for _ in range(20):
            self.assertEqual(env._suboptimal_action(0), 0)

    def test_epsilon_substituted_false_without_substitution(self):
        base = MaskStubEnv()
        env = ConstrainedBossEnv(base)
        env.reset()
        self.assertEqual(env.current_epsilon, 0.0)
        _, _, _, _, info = env.step(2)
        self.assertIn("epsilon_substituted", info)  # I2: always present
        self.assertFalse(info["epsilon_substituted"])
        self.assertEqual(base.received_actions, [2])

    def test_epsilon_substitution_is_legal_and_flagged(self):
        base = MaskStubEnv()
        base.mask = np.array([1, 1, 0, 0, 0], dtype=bool)
        env = ConstrainedBossEnv(base)
        env.reset()
        env.current_epsilon = 1.0  # force substitution every step
        _, _, _, _, info = env.step(0)
        self.assertTrue(info["epsilon_substituted"])
        self.assertEqual(base.received_actions, [1])  # only legal alternative

    def test_forced_epsilon_never_emits_illegal_action(self):
        base = MaskStubEnv()
        base.mask = np.array([1, 0, 1, 1, 0], dtype=bool)
        env = ConstrainedBossEnv(base)
        env.reset()
        env.current_epsilon = 1.0
        legal = {0, 2, 3}
        for chosen in (0, 2, 3) * 10:
            env.step(chosen)
        self.assertTrue(set(base.received_actions) <= legal,
                        f"illegal action reached env: {base.received_actions}")


class TestHierarchicalMasking(unittest.TestCase):
    def test_action_masks_passthrough_through_intermediate_wrapper(self):
        base = MaskStubEnv()
        base.mask = np.array([0, 1, 1, 0, 1], dtype=bool)
        # plain gym.Wrapper between: gymnasium 1.2.x forwards nothing, so
        # this only works via env.unwrapped (G2)
        env = HierarchicalBossEnv(gym.Wrapper(base))
        np.testing.assert_array_equal(env.action_masks(), base.mask)

    def test_action_masks_fallback_all_ones(self):
        env = HierarchicalBossEnv(TinyEnv())
        mask = env.action_masks()
        self.assertEqual(mask.shape, (5,))
        self.assertTrue(mask.all())

    def test_augmented_obs_size(self):
        env = HierarchicalBossEnv(MaskStubEnv())
        obs, _ = env.reset()
        self.assertEqual(obs.shape, (21,))  # 17 + strategy one-hot(4)


class TestStrategyRewardHistory(unittest.TestCase):
    """EXT 3.1: compute_strategy_reward must see the PREVIOUS action as
    history[-1] — the current action is appended AFTER the reward block."""

    def setUp(self):
        self._orig = hierarchical_env.compute_strategy_reward
        self.calls: list[dict] = []

        def spy(strategy, obs, action, prev_obs, action_history=None, **kw):
            self.calls.append({
                "action": action,
                "history": list(action_history or []),
                "kwargs": dict(kw),
            })
            return 0.0

        hierarchical_env.compute_strategy_reward = spy

    def tearDown(self):
        hierarchical_env.compute_strategy_reward = self._orig

    def test_history_excludes_current_action(self):
        env = HierarchicalBossEnv(MaskStubEnv())
        env.reset()
        env.step(1)
        env.step(2)
        env.step(4)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.calls[0]["history"], [])       # nothing prior
        self.assertEqual(self.calls[1]["history"], [1])      # prev only
        self.assertEqual(self.calls[2]["history"], [1, 2])   # 4 not yet in
        self.assertEqual(env._action_history, [1, 2, 4])     # appended after

    def test_emotion_scores_passed_when_base_env_emotion_enabled(self):
        base = MaskStubEnv(obs_size=20)
        base._emotion_enabled = True
        base._emotion_start = 17
        env = HierarchicalBossEnv(base)
        env.reset()
        env.step(0)
        self.assertEqual(len(self.calls), 1)
        kw = self.calls[0]["kwargs"]
        self.assertIn("emotion_scores", kw)
        self.assertEqual(tuple(kw["emotion_scores"]), (0.0, 0.0, 0.0))

    def test_emotion_scores_absent_when_disabled(self):
        env = HierarchicalBossEnv(MaskStubEnv())
        env.reset()
        env.step(0)
        self.assertNotIn("emotion_scores", self.calls[0]["kwargs"])


if __name__ == "__main__":
    unittest.main()
