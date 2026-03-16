"""
MAML meta-training orchestration for Boss AI.
Manages the outer meta-learning loop, task sampling, and per-player adaptation.

Training produces meta-parameters that adapt to new players in 2-3 gradient steps
instead of 50k+ fine-tuning steps (as in the transfer learning approach).
"""

import os
import random
from pathlib import Path

import numpy as np
import torch
import torch.optim as optim

from maml_data_utils import PlayerTask, compute_returns
from maml_policy import MamlPolicy, compute_meta_loss, inner_adapt, compute_ppo_loss
from replay_buffer_manager import ReplayBufferManager


class MAMLTrainer:
    """
    MAML meta-trainer for Boss AI.

    Outer loop: iterate over batches of player tasks, compute meta-loss,
    update meta-parameters.
    Inner loop (per task): adapt meta-policy on player's support set,
    evaluate on query set.
    """

    def __init__(
        self,
        obs_dim: int = 17,
        num_actions: int = 5,
        hidden_size: int = 64,
        meta_lr: float = 0.001,
        replay_dir: str = "./replays",
        gamma: float = 0.99,
    ):
        self.obs_dim = obs_dim
        self.num_actions = num_actions
        self.hidden_size = hidden_size
        self.gamma = gamma

        self.meta_policy = MamlPolicy(obs_dim, num_actions, hidden_size)
        self.meta_optimizer = optim.Adam(self.meta_policy.parameters(), lr=meta_lr)
        self.replay_manager = ReplayBufferManager(replay_dir)

    def sample_tasks(
        self,
        num_tasks: int,
        min_episodes: int = 3,
        support_fraction: float = 0.5,
    ) -> list[dict]:
        """
        Sample a batch of player tasks for meta-training.

        Returns:
            List of task dicts with support/query PyTorch tensors
        """
        all_tasks = self.replay_manager.get_all_player_tasks(
            min_episodes=min_episodes,
            support_fraction=support_fraction,
        )

        if len(all_tasks) < num_tasks:
            # If not enough players, sample with replacement
            if len(all_tasks) == 0:
                return []
            sampled = [random.choice(all_tasks) for _ in range(num_tasks)]
        else:
            sampled = random.sample(all_tasks, num_tasks)

        # Convert to tensor format
        tensor_tasks = []
        for task in sampled:
            tensor_tasks.append(task.to_tensors(gamma=self.gamma))

        return tensor_tasks

    def meta_train(
        self,
        num_iterations: int = 5000,
        tasks_per_batch: int = 4,
        inner_lr: float = 0.01,
        inner_steps: int = 3,
        min_episodes: int = 3,
        support_fraction: float = 0.5,
        log_interval: int = 100,
        tb_writer=None,
    ) -> dict:
        """
        Run the MAML outer-loop meta-training.

        Args:
            num_iterations: Number of outer-loop iterations
            tasks_per_batch: Players sampled per meta-batch
            inner_lr: Inner loop learning rate
            inner_steps: Inner loop gradient steps
            min_episodes: Minimum episodes per player to include
            support_fraction: Fraction of episodes for support set
            log_interval: How often to print progress
            tb_writer: Optional TensorBoard SummaryWriter

        Returns:
            Training metrics dict
        """
        print(f"=== MAML Meta-Training ===")
        print(f"  Obs dim: {self.obs_dim}, Actions: {self.num_actions}")
        print(f"  Inner LR: {inner_lr}, Inner steps: {inner_steps}")
        print(f"  Tasks per batch: {tasks_per_batch}")
        print(f"  Meta iterations: {num_iterations}")

        players = self.replay_manager.list_players()
        qualified = [p for p in players
                     if self.replay_manager.get_player_episode_count(p) >= min_episodes]
        print(f"  Players with sufficient data: {len(qualified)}/{len(players)}")

        if not qualified:
            print("ERROR: No players with sufficient replay data.")
            return {"error": "insufficient_data"}

        losses = []
        best_loss = float("inf")

        for iteration in range(num_iterations):
            # Sample task batch
            tasks = self.sample_tasks(
                tasks_per_batch,
                min_episodes=min_episodes,
                support_fraction=support_fraction,
            )

            if not tasks:
                continue

            # Compute meta-loss
            meta_loss = compute_meta_loss(
                self.meta_policy, tasks,
                inner_lr=inner_lr,
                inner_steps=inner_steps,
            )

            # Meta-gradient update
            self.meta_optimizer.zero_grad()
            meta_loss.backward()
            torch.nn.utils.clip_grad_norm_(self.meta_policy.parameters(), 1.0)
            self.meta_optimizer.step()

            loss_val = meta_loss.item()
            losses.append(loss_val)

            if loss_val < best_loss:
                best_loss = loss_val

            if tb_writer and iteration % 10 == 0:
                tb_writer.add_scalar("maml/meta_loss", loss_val, iteration)

            if (iteration + 1) % log_interval == 0:
                avg_loss = np.mean(losses[-log_interval:])
                print(
                    f"  Iteration {iteration + 1}/{num_iterations}: "
                    f"meta_loss={loss_val:.6f}, "
                    f"avg_loss={avg_loss:.6f}, "
                    f"best={best_loss:.6f}"
                )

        return {
            "final_loss": losses[-1] if losses else float("nan"),
            "best_loss": best_loss,
            "total_iterations": len(losses),
            "losses": losses,
        }

    def adapt_to_player(
        self,
        player_id: str,
        num_inner_steps: int = 3,
        inner_lr: float = 0.01,
    ) -> MamlPolicy | None:
        """
        Fast-adapt the meta-policy to a specific player.

        Args:
            player_id: Which player to adapt to
            num_inner_steps: Number of gradient steps (typically 2-3)
            inner_lr: Learning rate for adaptation

        Returns:
            Adapted policy, or None if player has no replay data
        """
        task = self.replay_manager.get_player_tasks(player_id)
        if task is None:
            return None

        tensors = task.to_tensors(gamma=self.gamma)

        adapted = inner_adapt(
            self.meta_policy,
            tensors["support_obs"],
            tensors["support_actions"],
            tensors["support_returns"],
            inner_lr=inner_lr,
            inner_steps=num_inner_steps,
            create_graph=False,  # No need for meta-gradients during inference
        )

        return adapted

    def evaluate_adaptation(
        self,
        player_id: str,
        max_inner_steps: int = 5,
        inner_lr: float = 0.01,
    ) -> dict:
        """
        Evaluate adaptation quality at each inner step.

        Reports query loss at 0, 1, 2, ..., max_inner_steps inner steps.
        This is the key metric for measuring MAML effectiveness.

        Returns:
            Dict mapping step count -> query loss
        """
        task = self.replay_manager.get_player_tasks(player_id)
        if task is None:
            return {"error": f"No data for player '{player_id}'"}

        tensors = task.to_tensors(gamma=self.gamma)
        results = {}

        for n_steps in range(max_inner_steps + 1):
            if n_steps == 0:
                # Unadapted meta-policy
                query_loss = compute_ppo_loss(
                    self.meta_policy,
                    tensors["query_obs"],
                    tensors["query_actions"],
                    tensors["query_returns"],
                ).item()
            else:
                adapted = inner_adapt(
                    self.meta_policy,
                    tensors["support_obs"],
                    tensors["support_actions"],
                    tensors["support_returns"],
                    inner_lr=inner_lr,
                    inner_steps=n_steps,
                    create_graph=False,
                )
                query_loss = compute_ppo_loss(
                    adapted,
                    tensors["query_obs"],
                    tensors["query_actions"],
                    tensors["query_returns"],
                ).item()

            results[n_steps] = query_loss

        return results

    def save_meta_model(self, path: str):
        """Save meta-model to disk."""
        save_dir = Path(path)
        save_dir.mkdir(parents=True, exist_ok=True)
        torch.save({
            "meta_policy": self.meta_policy.state_dict(),
            "obs_dim": self.obs_dim,
            "num_actions": self.num_actions,
            "hidden_size": self.hidden_size,
        }, save_dir / "meta_model.pt")

    def load_meta_model(self, path: str):
        """Load meta-model from disk."""
        checkpoint = torch.load(
            Path(path) / "meta_model.pt", weights_only=True
        )
        self.meta_policy.load_state_dict(checkpoint["meta_policy"])
