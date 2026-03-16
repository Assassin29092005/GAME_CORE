"""
Data utilities for MAML meta-learning.
Converts replay data into PlayerTask format with support/query splits,
and computes discounted returns for policy gradient loss.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch


@dataclass
class PlayerTask:
    """
    A single MAML task representing one player's data split into
    support (inner loop) and query (outer loss) sets.
    """

    player_id: str
    support_obs: np.ndarray
    support_actions: np.ndarray
    support_rewards: np.ndarray
    support_next_obs: np.ndarray
    support_dones: np.ndarray
    query_obs: np.ndarray
    query_actions: np.ndarray
    query_rewards: np.ndarray
    query_next_obs: np.ndarray
    query_dones: np.ndarray

    def to_tensors(self, gamma: float = 0.99) -> dict:
        """Convert to PyTorch tensors with computed returns."""
        support_returns = compute_returns(
            self.support_rewards, self.support_dones, gamma
        )
        query_returns = compute_returns(
            self.query_rewards, self.query_dones, gamma
        )

        return {
            "support_obs": torch.FloatTensor(self.support_obs),
            "support_actions": torch.LongTensor(self.support_actions),
            "support_returns": torch.FloatTensor(support_returns),
            "query_obs": torch.FloatTensor(self.query_obs),
            "query_actions": torch.LongTensor(self.query_actions),
            "query_returns": torch.FloatTensor(query_returns),
        }


def compute_returns(
    rewards: np.ndarray,
    dones: np.ndarray,
    gamma: float = 0.99,
) -> np.ndarray:
    """
    Compute discounted returns for each timestep.

    G_t = r_t + gamma * r_{t+1} + gamma^2 * r_{t+2} + ...
    Resets at episode boundaries (where done=True).

    Args:
        rewards: Array of rewards (T,)
        dones: Array of done flags (T,)
        gamma: Discount factor

    Returns:
        Array of discounted returns (T,)
    """
    T = len(rewards)
    returns = np.zeros(T, dtype=np.float32)

    running_return = 0.0
    for t in reversed(range(T)):
        if dones[t]:
            running_return = 0.0
        running_return = rewards[t] + gamma * running_return
        returns[t] = running_return

    return returns


def compute_gae(
    rewards: np.ndarray,
    values: np.ndarray,
    dones: np.ndarray,
    gamma: float = 0.99,
    gae_lambda: float = 0.95,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute Generalized Advantage Estimation.

    Args:
        rewards: (T,) array of rewards
        values: (T,) array of value estimates
        dones: (T,) array of done flags
        gamma: Discount factor
        gae_lambda: GAE lambda

    Returns:
        advantages: (T,) array
        returns: (T,) array (advantages + values)
    """
    T = len(rewards)
    advantages = np.zeros(T, dtype=np.float32)

    last_gae = 0.0
    for t in reversed(range(T)):
        if t == T - 1:
            next_value = 0.0
        else:
            next_value = values[t + 1] if not dones[t] else 0.0

        delta = rewards[t] + gamma * next_value - values[t]
        advantages[t] = last_gae = delta + gamma * gae_lambda * (
            0.0 if dones[t] else last_gae
        )

    returns = advantages + values
    return advantages, returns


def replay_to_tasks(
    replay_manager,
    min_episodes: int = 3,
    support_fraction: float = 0.5,
) -> list[PlayerTask]:
    """
    Convert all player replay data into MAML tasks.

    This is a convenience function that wraps ReplayBufferManager.get_all_player_tasks.

    Args:
        replay_manager: ReplayBufferManager instance
        min_episodes: Minimum episodes required per player
        support_fraction: Fraction of episodes for support set

    Returns:
        List of PlayerTask objects
    """
    return replay_manager.get_all_player_tasks(
        min_episodes=min_episodes,
        support_fraction=support_fraction,
    )
