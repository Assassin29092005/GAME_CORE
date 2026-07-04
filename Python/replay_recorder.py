"""Gymnasium wrapper that records episodes into ReplayBufferManager.

The replay write API (start_episode / record_step / end_episode) existed but
nothing called it during live play — MAML, IRL, world-model and transfer
training all *read* replays/{player_id}/episode_NNNN.npz, so without this
wrapper overnight runs produced no datasets (ROADMAP.md M1).

Wrap BossEnv directly (inside ConstrainedBossEnv, if used) so recorded rewards
are the raw environment rewards, not the constraint-shaped ones.
"""

from __future__ import annotations

import gymnasium as gym

from replay_buffer_manager import ReplayBufferManager


class ReplayRecorder(gym.Wrapper):
    def __init__(self, env: gym.Env, replay_dir: str, player_id: str):
        super().__init__(env)
        self._mgr = ReplayBufferManager(replay_dir)
        self._player_id = player_id
        self._last_obs = None

    def reset(self, **kwargs):
        # Flush any partial episode (e.g. external reset before done) — partial
        # trajectories are still useful to the IRL / world-model consumers.
        self._mgr.end_episode()

        obs, info = self.env.reset(**kwargs)
        self._mgr.start_episode(self._player_id)
        self._last_obs = obs
        return obs, info

    def step(self, action):
        # Capture the mask BEFORE the inner step: at this moment
        # _last_action_mask still corresponds to self._last_obs (the obs the
        # action was chosen from), so the (obs, mask) pairing is exact.
        mask = getattr(self.env.unwrapped, "action_masks", lambda: None)()

        obs, reward, terminated, truncated, info = self.env.step(action)
        done = bool(terminated or truncated)

        if self._last_obs is not None:
            self._mgr.record_step(
                self._last_obs, int(action), float(reward), obs, done,
                player_action=info.get("hero_action"),
                mask=mask,
            )
        self._last_obs = obs

        if done:
            self._mgr.end_episode()
        return obs, reward, terminated, truncated, info

    def close(self):
        self._mgr.end_episode()
        super().close()
