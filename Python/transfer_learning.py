"""
Transfer learning manager for cross-player knowledge transfer.
Trains a base policy from aggregated player data, then fine-tunes per player.
"""

import os
from pathlib import Path

from stable_baselines3 import PPO

from replay_buffer_manager import ReplayBufferManager


class TransferLearningManager:
    """
    Manages base model training from aggregated data and per-player fine-tuning.

    Workflow:
    1. Multiple players generate replay data via ReplayBufferManager
    2. train_base_model() aggregates replays and trains a base PPO model
    3. load_player_model() returns the per-player model (or copies base if new)
    4. fine_tune() adapts the model to a specific player with lower LR
    5. save_player_model() persists the fine-tuned model
    """

    def __init__(
        self,
        base_model_dir: str = "./models/base",
        player_model_dir: str = "./models/players",
        replay_dir: str = "./replays",
    ):
        self.base_model_dir = Path(base_model_dir)
        self.player_model_dir = Path(player_model_dir)
        self.replay_manager = ReplayBufferManager(replay_dir)

        self.base_model_dir.mkdir(parents=True, exist_ok=True)
        self.player_model_dir.mkdir(parents=True, exist_ok=True)

    @property
    def base_model_path(self) -> Path:
        return self.base_model_dir / "base_model.zip"

    def player_model_path(self, player_id: str) -> Path:
        return self.player_model_dir / f"{player_id}.zip"

    def has_base_model(self) -> bool:
        return self.base_model_path.exists()

    def has_player_model(self, player_id: str) -> bool:
        return self.player_model_path(player_id).exists()

    def train_base_model(self, env, total_timesteps: int = 1000000, **ppo_kwargs) -> PPO:
        """
        Train a base model from scratch using the provided environment.
        The base model learns general boss behavior across all players.

        In practice, this should be called after collecting replay data from
        multiple players. The env should wrap aggregated replay data or
        train live against varied player behavior.
        """
        print(f"Training base model for {total_timesteps} timesteps...")

        default_kwargs = {
            "learning_rate": 0.0003,
            "n_steps": 2048,
            "batch_size": 64,
            "gamma": 0.99,
            "gae_lambda": 0.95,
            "clip_range": 0.2,
            "ent_coef": 0.01,
            "n_epochs": 10,
            "verbose": 1,
        }
        default_kwargs.update(ppo_kwargs)

        model = PPO("MlpPolicy", env, **default_kwargs)
        model.learn(total_timesteps=total_timesteps)

        self.base_model_dir.mkdir(parents=True, exist_ok=True)
        model.save(str(self.base_model_path.with_suffix("")))
        print(f"Base model saved to {self.base_model_path}")

        return model

    def load_player_model(self, player_id: str, env=None) -> tuple[PPO, bool]:
        """
        Load per-player fine-tuned model. If none exists, copies base model.
        If no base model exists, returns None.

        Returns:
            (model, is_new_player) — is_new_player is True if starting from base
        """
        player_path = self.player_model_path(player_id)

        if player_path.exists():
            model = PPO.load(str(player_path.with_suffix("")), env=env)
            print(f"Loaded player model for '{player_id}'")
            return model, False

        if self.has_base_model():
            model = PPO.load(str(self.base_model_path.with_suffix("")), env=env)
            print(f"New player '{player_id}' — initialized from base model")
            return model, True

        print(f"No base model or player model for '{player_id}'")
        return None, True

    def save_player_model(self, model: PPO, player_id: str):
        """Save per-player fine-tuned model."""
        self.player_model_dir.mkdir(parents=True, exist_ok=True)
        save_path = self.player_model_path(player_id).with_suffix("")
        model.save(str(save_path))
        print(f"Saved player model for '{player_id}'")

    def fine_tune(self, model: PPO, env, timesteps: int = 50000,
                  lr: float = 0.0001) -> PPO:
        """
        Fine-tune a model for a specific player.
        Uses lower learning rate to preserve base knowledge while adapting.
        """
        model.set_env(env)
        model.learning_rate = lr

        print(f"Fine-tuning for {timesteps} steps (lr={lr})...")
        model.learn(total_timesteps=timesteps)

        return model

    def get_replay_stats(self) -> dict:
        """Get statistics about available replay data."""
        players = self.replay_manager.list_players()
        stats = {
            "total_players": len(players),
            "players": {},
        }
        for player_id in players:
            count = self.replay_manager.get_player_episode_count(player_id)
            stats["players"][player_id] = count

        return stats
