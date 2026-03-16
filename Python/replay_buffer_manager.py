"""
Replay buffer manager for collecting and aggregating player encounter data.
Used by transfer learning, IRL training, MAML meta-training, and world model training.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


class ReplayBufferManager:
    """
    Collects and manages replay data for transfer learning.
    Stores (obs, action, reward, next_obs, done) tuples per player as .npz files.
    """

    def __init__(self, replay_dir: str = "./replays"):
        self.replay_dir = Path(replay_dir)
        self.replay_dir.mkdir(parents=True, exist_ok=True)

        # In-memory buffer for current episode
        self._current_player: str | None = None
        self._episode_buffer: list[dict] = []
        self._episode_count = 0

    def start_episode(self, player_id: str):
        """Start recording a new episode for a player."""
        self._current_player = player_id
        self._episode_buffer = []

    def record_step(self, obs: np.ndarray, action: int, reward: float,
                    next_obs: np.ndarray, done: bool,
                    player_action: int | None = None):
        """Append a step to the current episode buffer."""
        step = {
            "obs": obs.copy(),
            "action": action,
            "reward": reward,
            "next_obs": next_obs.copy(),
            "done": done,
        }
        if player_action is not None:
            step["player_action"] = player_action
        self._episode_buffer.append(step)

    def end_episode(self):
        """Save the current episode to disk."""
        if not self._current_player or not self._episode_buffer:
            return

        player_dir = self.replay_dir / self._current_player
        player_dir.mkdir(parents=True, exist_ok=True)

        # Count existing episodes for this player
        existing = list(player_dir.glob("episode_*.npz"))
        episode_idx = len(existing)

        # Convert buffer to numpy arrays
        obs_arr = np.array([s["obs"] for s in self._episode_buffer], dtype=np.float32)
        action_arr = np.array([s["action"] for s in self._episode_buffer], dtype=np.int32)
        reward_arr = np.array([s["reward"] for s in self._episode_buffer], dtype=np.float32)
        next_obs_arr = np.array([s["next_obs"] for s in self._episode_buffer], dtype=np.float32)
        done_arr = np.array([s["done"] for s in self._episode_buffer], dtype=bool)

        filepath = player_dir / f"episode_{episode_idx:04d}.npz"
        save_kwargs = dict(
            obs=obs_arr,
            actions=action_arr,
            rewards=reward_arr,
            next_obs=next_obs_arr,
            dones=done_arr,
        )

        # Include player actions if recorded (for world model training)
        if any("player_action" in s for s in self._episode_buffer):
            player_action_arr = np.array(
                [s.get("player_action", 5) for s in self._episode_buffer],
                dtype=np.int32,
            )
            save_kwargs["player_actions"] = player_action_arr

        np.savez_compressed(filepath, **save_kwargs)

        self._episode_count += 1
        self._episode_buffer = []

    def get_player_episode_count(self, player_id: str) -> int:
        """Count episodes recorded for a player."""
        player_dir = self.replay_dir / player_id
        if not player_dir.exists():
            return 0
        return len(list(player_dir.glob("episode_*.npz")))

    def list_players(self) -> list[str]:
        """List all players with replay data."""
        if not self.replay_dir.exists():
            return []
        return [d.name for d in self.replay_dir.iterdir() if d.is_dir()]

    def load_player_replays(self, player_id: str) -> list[dict]:
        """Load all replay episodes for a player."""
        player_dir = self.replay_dir / player_id
        if not player_dir.exists():
            return []

        episodes = []
        for filepath in sorted(player_dir.glob("episode_*.npz")):
            data = np.load(filepath)
            episodes.append({
                "obs": data["obs"],
                "actions": data["actions"],
                "rewards": data["rewards"],
                "next_obs": data["next_obs"],
                "dones": data["dones"],
            })
        return episodes

    def aggregate_replays(self, min_episodes_per_player: int = 5) -> dict | None:
        """
        Combine replays from all players with enough data.
        Returns aggregated arrays or None if insufficient data.
        """
        all_obs = []
        all_actions = []
        all_rewards = []
        all_next_obs = []
        all_dones = []

        players_included = 0

        for player_id in self.list_players():
            if self.get_player_episode_count(player_id) < min_episodes_per_player:
                continue

            episodes = self.load_player_replays(player_id)
            for ep in episodes:
                all_obs.append(ep["obs"])
                all_actions.append(ep["actions"])
                all_rewards.append(ep["rewards"])
                all_next_obs.append(ep["next_obs"])
                all_dones.append(ep["dones"])

            players_included += 1

        if players_included == 0:
            return None

        return {
            "obs": np.concatenate(all_obs),
            "actions": np.concatenate(all_actions),
            "rewards": np.concatenate(all_rewards),
            "next_obs": np.concatenate(all_next_obs),
            "dones": np.concatenate(all_dones),
            "num_players": players_included,
            "total_steps": sum(len(o) for o in all_obs),
        }

    # --- Extension 8: IRL trajectory support ---

    def get_player_trajectories(
        self, player_id: str
    ) -> list[list[tuple[np.ndarray, int]]]:
        """
        Convert player replay data into IRL trajectory format.

        Returns:
            List of episodes, each a list of (feature_vector, action) tuples.
            Feature vectors are computed by irl_feature_engineering.
        """
        from irl_feature_engineering import trajectories_from_replays

        episodes = self.load_player_replays(player_id)
        if not episodes:
            return []
        return trajectories_from_replays(episodes)

    # --- Extension 7: MAML task support ---

    def get_player_tasks(
        self, player_id: str, support_fraction: float = 0.5
    ) -> PlayerTask | None:
        """
        Split a player's replay data into support/query sets for MAML.

        Args:
            player_id: Which player's data to load
            support_fraction: Fraction of episodes used for support (inner loop)

        Returns:
            PlayerTask with support and query arrays, or None if insufficient data
        """
        episodes = self.load_player_replays(player_id)
        if len(episodes) < 2:
            return None

        split_idx = max(1, int(len(episodes) * support_fraction))
        support_eps = episodes[:split_idx]
        query_eps = episodes[split_idx:]

        if not query_eps:
            # If only 2 episodes, use first as support, second as query
            support_eps = episodes[:1]
            query_eps = episodes[1:]

        def stack_episodes(eps: list[dict]) -> dict:
            return {
                "obs": np.concatenate([e["obs"] for e in eps]),
                "actions": np.concatenate([e["actions"] for e in eps]),
                "rewards": np.concatenate([e["rewards"] for e in eps]),
                "next_obs": np.concatenate([e["next_obs"] for e in eps]),
                "dones": np.concatenate([e["dones"] for e in eps]),
            }

        support = stack_episodes(support_eps)
        query = stack_episodes(query_eps)

        return PlayerTask(
            player_id=player_id,
            support_obs=support["obs"],
            support_actions=support["actions"],
            support_rewards=support["rewards"],
            support_next_obs=support["next_obs"],
            support_dones=support["dones"],
            query_obs=query["obs"],
            query_actions=query["actions"],
            query_rewards=query["rewards"],
            query_next_obs=query["next_obs"],
            query_dones=query["dones"],
        )

    def get_all_player_tasks(
        self,
        min_episodes: int = 3,
        support_fraction: float = 0.5,
    ) -> list[PlayerTask]:
        """Get MAML tasks for all players with sufficient data."""
        tasks = []
        for player_id in self.list_players():
            if self.get_player_episode_count(player_id) < min_episodes:
                continue
            task = self.get_player_tasks(player_id, support_fraction)
            if task is not None:
                tasks.append(task)
        return tasks


@dataclass
class PlayerTask:
    """MAML task: support set (inner loop) + query set (outer loss)."""

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
