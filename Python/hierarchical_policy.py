"""
Hierarchical agent combining a high-level strategist and low-level tactician.
Both are PPO models. The strategist runs every N steps to select a strategy archetype.
"""

import os

import numpy as np
from stable_baselines3 import PPO

from boss_env import BossEnv
from hierarchical_env import HierarchicalBossEnv, StrategistEnv, NUM_STRATEGIES
from strategy_reward import STRATEGY_NAMES


class HierarchicalAgent:
    """
    Two-level hierarchical RL agent for boss AI.

    High-level (Strategist): PPO with Discrete(4) output — selects strategy archetype.
    Low-level (Tactician): PPO with Discrete(5) output — selects combat actions
                           conditioned on the current strategy.
    """

    def __init__(
        self,
        strategist_path: str | None = None,
        tactician_path: str | None = None,
        strategy_interval: int = 30,
    ):
        self.strategy_interval = strategy_interval
        self.strategist: PPO | None = None
        self.tactician: PPO | None = None

        self._current_strategy = 0
        self._steps_since_strategy = 0
        self._strategy_onehot = np.zeros(NUM_STRATEGIES, dtype=np.float32)
        self._strategy_onehot[0] = 1.0

        if strategist_path and os.path.exists(strategist_path):
            self.strategist = PPO.load(strategist_path)
            print(f"Loaded strategist from {strategist_path}")

        if tactician_path and os.path.exists(tactician_path):
            self.tactician = PPO.load(tactician_path)
            print(f"Loaded tactician from {tactician_path}")

    def predict(self, obs: np.ndarray, deterministic: bool = True) -> tuple[int, dict]:
        """
        Full hierarchical prediction.

        Args:
            obs: 17-dim base observation from BossEnv
            deterministic: if True, use greedy action selection

        Returns:
            (action_index, info_dict) where action_index is 0-4
        """
        info = {
            "strategy": self._current_strategy,
            "strategy_name": STRATEGY_NAMES.get(self._current_strategy, "Unknown"),
        }

        # Check if strategist needs to select a new strategy
        if self.strategist is not None and self._steps_since_strategy >= self.strategy_interval:
            strategy_action, _ = self.strategist.predict(obs, deterministic=deterministic)
            self._current_strategy = int(strategy_action)
            self._strategy_onehot = np.zeros(NUM_STRATEGIES, dtype=np.float32)
            self._strategy_onehot[self._current_strategy] = 1.0
            self._steps_since_strategy = 0
            info["strategy_changed"] = True
            info["strategy"] = self._current_strategy
            info["strategy_name"] = STRATEGY_NAMES.get(self._current_strategy, "Unknown")

        # Augment observation with strategy context for tactician
        augmented_obs = np.concatenate([obs, self._strategy_onehot])

        # Get tactical action
        if self.tactician is not None:
            action, _ = self.tactician.predict(augmented_obs, deterministic=deterministic)
        else:
            action = np.random.randint(0, 5)

        self._steps_since_strategy += 1

        return int(action), info

    def reset(self):
        """Reset strategy state for a new episode."""
        self._current_strategy = 0
        self._steps_since_strategy = self.strategy_interval  # force strategy selection on first step
        self._strategy_onehot = np.zeros(NUM_STRATEGIES, dtype=np.float32)
        self._strategy_onehot[0] = 1.0

    def save(self, directory: str):
        """Save both models to a directory."""
        os.makedirs(directory, exist_ok=True)
        if self.strategist:
            self.strategist.save(os.path.join(directory, "strategist"))
        if self.tactician:
            self.tactician.save(os.path.join(directory, "tactician"))
        print(f"Saved hierarchical agent to {directory}")

    @classmethod
    def load(cls, directory: str, strategy_interval: int = 30) -> "HierarchicalAgent":
        """Load both models from a directory."""
        strategist_path = os.path.join(directory, "strategist.zip")
        tactician_path = os.path.join(directory, "tactician.zip")

        return cls(
            strategist_path=strategist_path if os.path.exists(strategist_path) else None,
            tactician_path=tactician_path if os.path.exists(tactician_path) else None,
            strategy_interval=strategy_interval,
        )
