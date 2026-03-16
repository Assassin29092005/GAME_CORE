"""
Hierarchical environment wrapper for two-level Boss RL policy.
Augments observations with strategy context and applies strategy-specific reward shaping.
"""

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from boss_env import BossEnv
from strategy_reward import compute_strategy_reward, STRATEGY_NAMES

NUM_STRATEGIES = 4


class HierarchicalBossEnv(gym.Wrapper):
    """
    Wraps BossEnv for use with a two-level hierarchical policy.

    The low-level tactician receives:
      - 17-dim base observation (from BossEnv)
      - 4-dim one-hot strategy embedding
      = 21-dim observation

    The high-level strategist selects a strategy every `strategy_interval` steps.
    This env handles the observation augmentation and strategy-conditioned reward shaping.
    """

    def __init__(
        self,
        env: gym.Env,
        strategy_interval: int = 30,
        strategy_reward_weight: float = 0.5,
    ):
        super().__init__(env)

        self.strategy_interval = strategy_interval
        self.strategy_reward_weight = strategy_reward_weight
        self.current_strategy = 0
        self.steps_since_strategy = 0

        # Augmented observation: base (17) + strategy one-hot (4) = 21
        inner_obs_size = env.observation_space.shape[0]
        self.base_obs_size = inner_obs_size
        self.augmented_size = inner_obs_size + NUM_STRATEGIES

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(self.augmented_size,),
            dtype=np.float32,
        )
        self.action_space = env.action_space

        # Action history for strategy reward (hit-and-run, counter patterns)
        self._action_history: list[int] = []
        self._prev_obs: np.ndarray | None = None

    def reset(self, **kwargs):
        obs, info = self.env.reset(**kwargs)
        self.current_strategy = 0
        self.steps_since_strategy = 0
        self._action_history = []
        self._prev_obs = obs.copy()
        return self._augment_obs(obs), info

    def step(self, action):
        action = int(action)
        self._action_history.append(action)

        # Keep action history bounded
        if len(self._action_history) > 100:
            self._action_history = self._action_history[-50:]

        obs, reward, terminated, truncated, info = self.env.step(action)

        # Add strategy-specific reward shaping
        if self._prev_obs is not None:
            strategy_bonus = compute_strategy_reward(
                self.current_strategy, obs, action, self._prev_obs,
                action_history=self._action_history,
            )
            reward += strategy_bonus * self.strategy_reward_weight

        self._prev_obs = obs.copy()
        self.steps_since_strategy += 1

        info["strategy"] = self.current_strategy
        info["strategy_name"] = STRATEGY_NAMES.get(self.current_strategy, "Unknown")

        return self._augment_obs(obs), reward, terminated, truncated, info

    def set_strategy(self, strategy_id: int):
        """Set the current high-level strategy. Called by the strategist."""
        self.current_strategy = strategy_id
        self.steps_since_strategy = 0

    def needs_strategy_update(self) -> bool:
        """Check if the strategist should select a new strategy."""
        return self.steps_since_strategy >= self.strategy_interval

    def get_base_obs(self, augmented_obs: np.ndarray) -> np.ndarray:
        """Extract the base observation from an augmented observation."""
        return augmented_obs[:self.base_obs_size]

    def _augment_obs(self, obs: np.ndarray) -> np.ndarray:
        """Append strategy one-hot encoding to observation."""
        strategy_onehot = np.zeros(NUM_STRATEGIES, dtype=np.float32)
        strategy_onehot[self.current_strategy] = 1.0
        return np.concatenate([obs, strategy_onehot])


class StrategistEnv(gym.Env):
    """
    Environment for the high-level strategist.

    Each 'step' corresponds to `strategy_interval` steps of the tactician.
    The observation is the base observation (17-dim).
    The action selects a strategy archetype (Discrete(4)).
    The reward is the cumulative tactician reward over the interval.
    """

    metadata = {"render_modes": []}

    def __init__(self, hierarchical_env: HierarchicalBossEnv, tactician_model):
        super().__init__()

        self.hier_env = hierarchical_env
        self.tactician = tactician_model

        # Strategist sees base observation only
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(hierarchical_env.base_obs_size,),
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(NUM_STRATEGIES)

        self._current_obs: np.ndarray | None = None

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        aug_obs, info = self.hier_env.reset()
        self._current_obs = self.hier_env.get_base_obs(aug_obs)
        return self._current_obs, info

    def step(self, strategy_action):
        """Execute one strategist step = N tactician steps."""
        strategy_action = int(strategy_action)
        self.hier_env.set_strategy(strategy_action)

        cumulative_reward = 0.0
        terminated = False
        truncated = False
        info = {}

        # Run tactician for strategy_interval steps
        for _ in range(self.hier_env.strategy_interval):
            # Get augmented observation for tactician
            aug_obs = self.hier_env._augment_obs(self._current_obs)
            tac_action, _ = self.tactician.predict(aug_obs, deterministic=False)

            aug_obs, reward, terminated, truncated, info = self.hier_env.step(int(tac_action))
            self._current_obs = self.hier_env.get_base_obs(aug_obs)
            cumulative_reward += reward

            if terminated or truncated:
                break

        return self._current_obs, cumulative_reward, terminated, truncated, info
