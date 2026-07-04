"""Shared in-process env stubs for wrapper/contract tests (no sockets)."""

from __future__ import annotations

import sys
from pathlib import Path

import gymnasium as gym
import numpy as np
from gymnasium import spaces

_PY_DIR = Path(__file__).resolve().parents[1]
if str(_PY_DIR) not in sys.path:
    sys.path.insert(0, str(_PY_DIR))


class TinyEnv(gym.Env):
    """Minimal 17-dim / Discrete(5) env WITHOUT action_masks (fallback tests,
    offline SB3 model construction)."""

    metadata = {"render_modes": []}

    def __init__(self, obs_size: int = 17):
        super().__init__()
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_size,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(5)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        return np.zeros(self.observation_space.shape, dtype=np.float32), {}

    def step(self, action):
        obs = np.zeros(self.observation_space.shape, dtype=np.float32)
        return obs, 0.0, True, False, {}


class MaskStubEnv(gym.Env):
    """17-dim / Discrete(5) stub WITH a settable legal-action mask (I1 shape).

    Obs indices 5/8 carry hero_hp/boss_hp so BossEnv.IDX_* consumers
    (ConstrainedBossEnv) work. Hooks:
      .mask              mask returned by action_masks()
      .received_actions  actions passed to step(), in order
      .step_hook         callable(env, action) run inside step() before the
                         obs is built (mutate hp / mask to script scenarios)
      .info_extra        dict merged into every step info
    """

    metadata = {"render_modes": []}

    def __init__(self, obs_size: int = 17):
        super().__init__()
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_size,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(5)
        self.mask = np.ones(5, dtype=bool)
        self.hero_hp = 1.0
        self.boss_hp = 1.0
        self.received_actions: list[int] = []
        self.step_hook = None
        self.info_extra: dict = {}
        self._steps = 0

    def action_masks(self) -> np.ndarray:
        return np.asarray(self.mask, dtype=bool).copy()

    def _obs(self) -> np.ndarray:
        obs = np.zeros(self.observation_space.shape, dtype=np.float32)
        obs[5] = self.hero_hp
        obs[8] = self.boss_hp
        return obs

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._steps = 0
        return self._obs(), {}

    def step(self, action):
        action = int(action)
        self.received_actions.append(action)
        self._steps += 1
        if self.step_hook is not None:
            self.step_hook(self, action)
        terminated = self.hero_hp <= 0.0 or self.boss_hp <= 0.0
        info = dict(self.info_extra)
        return self._obs(), 0.0, terminated, False, info
