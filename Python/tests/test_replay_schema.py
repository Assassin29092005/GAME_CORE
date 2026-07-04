"""Replay npz schema contract (I7): additive `masks` (T,5) uint8 +
`player_actions` (T,) int32; loaders tolerate old files without them.
Also verifies ReplayRecorder captures the PRE-step mask (EXT 3.5).
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

_PY_DIR = Path(__file__).resolve().parents[1]
for _p in (str(_PY_DIR), str(_PY_DIR / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from replay_buffer_manager import ReplayBufferManager
from replay_recorder import ReplayRecorder
from env_stubs import TinyEnv, MaskStubEnv


def _dummy_step(dim=17):
    return np.zeros(dim, dtype=np.float32), np.ones(dim, dtype=np.float32)


class TestNpzSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mgr = ReplayBufferManager(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _episode_file(self, player="p1"):
        files = sorted((Path(self.tmp.name) / player).glob("episode_*.npz"))
        self.assertTrue(files, "no episode file written")
        return files[-1]

    def test_masks_and_player_actions_saved_with_dtypes(self):
        obs, nxt = _dummy_step()
        self.mgr.start_episode("p1")
        for i in range(3):
            self.mgr.record_step(
                obs, i, 0.5, nxt, i == 2,
                player_action=2,
                mask=np.array([1, 0, 1, 1, 1], dtype=bool),
            )
        self.mgr.end_episode()

        with np.load(self._episode_file()) as data:
            self.assertIn("masks", data)
            self.assertEqual(data["masks"].shape, (3, 5))
            self.assertEqual(data["masks"].dtype, np.uint8)
            np.testing.assert_array_equal(data["masks"][0], [1, 0, 1, 1, 1])
            self.assertIn("player_actions", data)
            self.assertEqual(data["player_actions"].dtype, np.int32)
            np.testing.assert_array_equal(data["player_actions"], [2, 2, 2])

    def test_no_masks_key_when_never_recorded(self):
        # additive schema: files written without masks stay in the old shape
        obs, nxt = _dummy_step()
        self.mgr.start_episode("p1")
        self.mgr.record_step(obs, 0, 0.0, nxt, True)
        self.mgr.end_episode()
        with np.load(self._episode_file()) as data:
            self.assertNotIn("masks", data)
            self.assertNotIn("player_actions", data)

    def test_partial_masks_default_all_legal(self):
        obs, nxt = _dummy_step()
        self.mgr.start_episode("p1")
        self.mgr.record_step(obs, 0, 0.0, nxt, False)  # no mask (old-style)
        self.mgr.record_step(obs, 1, 0.0, nxt, True,
                             mask=np.array([0, 1, 0, 0, 1], dtype=bool))
        self.mgr.end_episode()
        with np.load(self._episode_file()) as data:
            np.testing.assert_array_equal(data["masks"][0], [1, 1, 1, 1, 1])
            np.testing.assert_array_equal(data["masks"][1], [0, 1, 0, 0, 1])

    def test_loaders_tolerate_old_files_without_masks(self):
        # simulate a pre-upgrade replay written by the old pipeline
        player_dir = Path(self.tmp.name) / "old_player"
        player_dir.mkdir(parents=True)
        T, D = 4, 17
        for i in range(2):
            np.savez_compressed(
                player_dir / f"episode_{i:04d}.npz",
                obs=np.zeros((T, D), dtype=np.float32),
                actions=np.zeros(T, dtype=np.int32),
                rewards=np.zeros(T, dtype=np.float32),
                next_obs=np.zeros((T, D), dtype=np.float32),
                dones=np.zeros(T, dtype=bool),
            )

        episodes = self.mgr.load_player_replays("old_player")
        self.assertEqual(len(episodes), 2)
        self.assertEqual(episodes[0]["obs"].shape, (T, D))

        agg = self.mgr.aggregate_replays(min_episodes_per_player=1)
        self.assertIsNotNone(agg)
        self.assertEqual(agg["total_steps"], 2 * T)

        task = self.mgr.get_player_tasks("old_player")
        self.assertIsNotNone(task)
        self.assertEqual(task.support_obs.shape[1], D)


class TestReplayRecorderMaskCapture(unittest.TestCase):
    def test_recorder_stores_pre_step_mask(self):
        # the mask must be captured BEFORE env.step mutates it, so the
        # (obs, mask) pairing matches the obs the action was chosen from
        with tempfile.TemporaryDirectory() as tmp:
            base = MaskStubEnv()
            base.mask = np.array([1, 1, 0, 0, 0], dtype=bool)

            def mutate_mask(env, action):
                env.mask = np.array([0, 0, 1, 1, 1], dtype=bool)
                env.hero_hp = 0.0  # terminate -> episode flushes to disk

            base.step_hook = mutate_mask
            rec = ReplayRecorder(base, replay_dir=tmp, player_id="p1")
            rec.reset()
            rec.step(1)

            files = sorted((Path(tmp) / "p1").glob("episode_*.npz"))
            self.assertEqual(len(files), 1)
            with np.load(files[0]) as data:
                np.testing.assert_array_equal(
                    data["masks"][0], [1, 1, 0, 0, 0]  # PRE-step mask
                )

    def test_recorder_propagates_hero_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = MaskStubEnv()
            base.info_extra = {"hero_action": 3}

            def kill(env, action):
                env.hero_hp = 0.0

            base.step_hook = kill
            rec = ReplayRecorder(base, replay_dir=tmp, player_id="p1")
            rec.reset()
            rec.step(0)

            files = sorted((Path(tmp) / "p1").glob("episode_*.npz"))
            with np.load(files[0]) as data:
                self.assertIn("player_actions", data)
                np.testing.assert_array_equal(data["player_actions"], [3])

    def test_recorder_tolerates_maskless_base_env(self):
        # legacy path: base env without action_masks -> no masks key, no crash
        with tempfile.TemporaryDirectory() as tmp:
            rec = ReplayRecorder(TinyEnv(), replay_dir=tmp, player_id="p1")
            rec.reset()
            rec.step(0)  # TinyEnv terminates immediately
            files = sorted((Path(tmp) / "p1").glob("episode_*.npz"))
            self.assertEqual(len(files), 1)
            with np.load(files[0]) as data:
                self.assertNotIn("masks", data)


if __name__ == "__main__":
    unittest.main()
