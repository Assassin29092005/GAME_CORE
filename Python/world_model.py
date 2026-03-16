"""
World Model for Boss AI planning.
Learns environment dynamics: f(obs, boss_action, player_action) -> (next_obs, reward)

Enables 1-2 step lookahead planning so the boss can anticipate consequences
of its actions before committing, transforming it from reactive to deliberative.

Reference: Ha & Schmidhuber 2018 "World Models", DreamerV3 2023
Novel application: no prior work applies world models to boss AI combat planning.
"""

import os
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


class WorldModel(nn.Module):
    """
    MLP dynamics model predicting next observation and reward.

    Input:  [obs (17-dim), boss_action_onehot (5-dim), player_action_onehot (6-dim)]
    Output: [predicted_next_obs (17-dim), predicted_reward (1-dim)]

    Player action has 6 values: 0-4 = game actions, 5 = idle.
    """

    NUM_BOSS_ACTIONS = 5
    NUM_PLAYER_ACTIONS = 6  # 5 game actions + idle

    def __init__(
        self,
        obs_dim: int = 17,
        hidden_size: int = 128,
        num_boss_actions: int = 5,
        num_player_actions: int = 6,
    ):
        super().__init__()
        self.obs_dim = obs_dim
        self.num_boss_actions = num_boss_actions
        self.num_player_actions = num_player_actions

        input_dim = obs_dim + num_boss_actions + num_player_actions
        output_dim = obs_dim + 1  # next_obs + reward

        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, output_dim),
        )

    def forward(
        self,
        obs: torch.Tensor,
        boss_action_onehot: torch.Tensor,
        player_action_onehot: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Forward pass.

        Returns:
            next_obs_pred: predicted next observation (batch, obs_dim)
            reward_pred: predicted reward (batch, 1)
        """
        x = torch.cat([obs, boss_action_onehot, player_action_onehot], dim=-1)
        out = self.net(x)
        next_obs_pred = out[:, : self.obs_dim]
        reward_pred = out[:, self.obs_dim :]
        return next_obs_pred, reward_pred

    def predict(
        self,
        obs: np.ndarray,
        boss_action: int,
        player_action: int,
    ) -> tuple[np.ndarray, float]:
        """
        Single-step prediction (numpy convenience method).

        Args:
            obs: current observation (obs_dim,)
            boss_action: boss action index (0-4)
            player_action: player action index (0-5)

        Returns:
            next_obs: predicted next observation (obs_dim,)
            reward: predicted reward scalar
        """
        obs_t = torch.FloatTensor(obs).unsqueeze(0)

        boss_onehot = torch.zeros(1, self.num_boss_actions)
        boss_onehot[0, boss_action] = 1.0

        player_onehot = torch.zeros(1, self.num_player_actions)
        player_onehot[0, player_action] = 1.0

        with torch.no_grad():
            next_obs_pred, reward_pred = self.forward(
                obs_t, boss_onehot, player_onehot
            )

        return next_obs_pred.squeeze(0).numpy(), reward_pred.item()


class WorldModelTrainer:
    """Trains the world model on replay data using supervised learning."""

    def __init__(
        self,
        model: WorldModel,
        learning_rate: float = 0.001,
    ):
        self.model = model
        self.optimizer = optim.Adam(model.parameters(), lr=learning_rate)
        self.obs_loss_fn = nn.MSELoss()
        self.reward_loss_fn = nn.MSELoss()

    def train_on_replays(
        self,
        replay_episodes: list[dict],
        epochs: int = 50,
        batch_size: int = 256,
        validation_split: float = 0.1,
        verbose: bool = True,
    ) -> dict:
        """
        Train world model on collected replay data.

        Args:
            replay_episodes: List of episode dicts from ReplayBufferManager
            epochs: Training epochs
            batch_size: Batch size
            validation_split: Fraction held out for validation
            verbose: Print progress

        Returns:
            Training metrics dict
        """
        # Collect all transitions
        all_obs = []
        all_actions = []
        all_player_actions = []
        all_rewards = []
        all_next_obs = []

        for ep in replay_episodes:
            obs = ep["obs"]
            actions = ep["actions"]
            rewards = ep["rewards"]
            next_obs = ep["next_obs"]

            # Use player actions if available, otherwise default to idle (5)
            if "player_actions" in ep:
                player_acts = ep["player_actions"]
            else:
                player_acts = np.full(len(actions), 5, dtype=np.int32)

            all_obs.append(obs)
            all_actions.append(actions)
            all_player_actions.append(player_acts)
            all_rewards.append(rewards)
            all_next_obs.append(next_obs)

        obs_arr = np.concatenate(all_obs)
        action_arr = np.concatenate(all_actions)
        player_action_arr = np.concatenate(all_player_actions)
        reward_arr = np.concatenate(all_rewards)
        next_obs_arr = np.concatenate(all_next_obs)

        n = len(obs_arr)
        if n == 0:
            raise ValueError("No transitions found in replay data")

        # Truncate obs to base dimensions if needed
        obs_dim = self.model.obs_dim
        if obs_arr.shape[1] > obs_dim:
            obs_arr = obs_arr[:, :obs_dim]
            next_obs_arr = next_obs_arr[:, :obs_dim]

        # One-hot encode actions
        boss_onehot = np.zeros((n, self.model.num_boss_actions), dtype=np.float32)
        boss_onehot[np.arange(n), action_arr] = 1.0

        player_onehot = np.zeros((n, self.model.num_player_actions), dtype=np.float32)
        player_action_arr = np.clip(player_action_arr, 0, self.model.num_player_actions - 1)
        player_onehot[np.arange(n), player_action_arr] = 1.0

        # Convert to tensors
        obs_t = torch.FloatTensor(obs_arr)
        boss_t = torch.FloatTensor(boss_onehot)
        player_t = torch.FloatTensor(player_onehot)
        reward_t = torch.FloatTensor(reward_arr).unsqueeze(1)
        next_obs_t = torch.FloatTensor(next_obs_arr)

        # Train/val split
        val_size = max(1, int(n * validation_split))
        train_size = n - val_size

        indices = np.random.permutation(n)
        train_idx = indices[:train_size]
        val_idx = indices[train_size:]

        train_dataset = TensorDataset(
            obs_t[train_idx], boss_t[train_idx], player_t[train_idx],
            next_obs_t[train_idx], reward_t[train_idx],
        )
        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)

        # Training loop
        best_val_loss = float("inf")
        metrics = {"train_losses": [], "val_losses": []}

        for epoch in range(epochs):
            self.model.train()
            epoch_loss = 0.0

            for batch in train_loader:
                b_obs, b_boss, b_player, b_next_obs, b_reward = batch

                next_obs_pred, reward_pred = self.model(b_obs, b_boss, b_player)

                obs_loss = self.obs_loss_fn(next_obs_pred, b_next_obs)
                rew_loss = self.reward_loss_fn(reward_pred, b_reward)
                loss = obs_loss + 0.1 * rew_loss  # obs prediction is primary

                self.optimizer.zero_grad()
                loss.backward()
                self.optimizer.step()

                epoch_loss += loss.item() * len(b_obs)

            avg_train_loss = epoch_loss / train_size
            metrics["train_losses"].append(avg_train_loss)

            # Validation
            self.model.eval()
            with torch.no_grad():
                val_next_pred, val_rew_pred = self.model(
                    obs_t[val_idx], boss_t[val_idx], player_t[val_idx]
                )
                val_obs_loss = self.obs_loss_fn(val_next_pred, next_obs_t[val_idx])
                val_rew_loss = self.reward_loss_fn(val_rew_pred, reward_t[val_idx])
                val_loss = val_obs_loss.item() + 0.1 * val_rew_loss.item()

            metrics["val_losses"].append(val_loss)

            if val_loss < best_val_loss:
                best_val_loss = val_loss

            if verbose and (epoch + 1) % 10 == 0:
                print(
                    f"  Epoch {epoch + 1}/{epochs}: "
                    f"train_loss={avg_train_loss:.6f}, "
                    f"val_loss={val_loss:.6f}, "
                    f"val_obs_mse={val_obs_loss.item():.6f}, "
                    f"val_rew_mse={val_rew_loss.item():.6f}"
                )

        metrics["best_val_loss"] = best_val_loss
        metrics["total_transitions"] = n
        return metrics

    def evaluate(self, replay_episodes: list[dict]) -> dict:
        """Evaluate model on held-out episodes."""
        all_obs, all_actions, all_player_actions = [], [], []
        all_rewards, all_next_obs = [], []

        for ep in replay_episodes:
            obs_dim = self.model.obs_dim
            obs = ep["obs"][:, :obs_dim] if ep["obs"].shape[1] > obs_dim else ep["obs"]
            next_obs = ep["next_obs"][:, :obs_dim] if ep["next_obs"].shape[1] > obs_dim else ep["next_obs"]
            all_obs.append(obs)
            all_actions.append(ep["actions"])
            all_player_actions.append(
                ep.get("player_actions", np.full(len(ep["actions"]), 5, dtype=np.int32))
            )
            all_rewards.append(ep["rewards"])
            all_next_obs.append(next_obs)

        obs_arr = np.concatenate(all_obs)
        action_arr = np.concatenate(all_actions)
        player_arr = np.concatenate(all_player_actions)
        reward_arr = np.concatenate(all_rewards)
        next_obs_arr = np.concatenate(all_next_obs)

        n = len(obs_arr)
        boss_onehot = np.zeros((n, self.model.num_boss_actions), dtype=np.float32)
        boss_onehot[np.arange(n), action_arr] = 1.0
        player_onehot = np.zeros((n, self.model.num_player_actions), dtype=np.float32)
        player_arr = np.clip(player_arr, 0, self.model.num_player_actions - 1)
        player_onehot[np.arange(n), player_arr] = 1.0

        self.model.eval()
        with torch.no_grad():
            next_pred, rew_pred = self.model(
                torch.FloatTensor(obs_arr),
                torch.FloatTensor(boss_onehot),
                torch.FloatTensor(player_onehot),
            )

        next_pred_np = next_pred.numpy()
        rew_pred_np = rew_pred.squeeze(1).numpy()

        # Per-dimension MSE
        dim_mse = np.mean((next_pred_np - next_obs_arr) ** 2, axis=0)
        total_mse = float(np.mean(dim_mse))
        reward_mse = float(np.mean((rew_pred_np - reward_arr) ** 2))

        return {
            "total_obs_mse": total_mse,
            "reward_mse": reward_mse,
            "per_dim_mse": dim_mse.tolist(),
            "num_transitions": n,
        }
