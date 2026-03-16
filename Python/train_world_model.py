"""
Training script for the Boss AI world model.
Trains a dynamics model on replay data for planning-based action selection.

Usage:
    python train_world_model.py [--config config.yaml]
    python train_world_model.py evaluate
"""

import argparse
import os

import torch
import yaml

from replay_buffer_manager import ReplayBufferManager
from world_model import WorldModel, WorldModelTrainer


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def train_world_model(cfg: dict):
    """Train world model on aggregated replay data from all players."""
    wm_cfg = cfg.get("world_model", {})
    replay_dir = cfg.get("transfer", {}).get("replay_dir", "./replays")

    obs_dim = cfg.get("env", {}).get("observation_size", 17)
    hidden_size = wm_cfg.get("hidden_size", 128)
    lr = wm_cfg.get("learning_rate", 0.001)
    epochs = wm_cfg.get("train_epochs", 50)
    batch_size = wm_cfg.get("batch_size", 256)
    model_dir = wm_cfg.get("model_dir", "./models/world_model")

    print("=== World Model Training ===")
    print(f"  Obs dim: {obs_dim}, Hidden: {hidden_size}, LR: {lr}")
    print(f"  Epochs: {epochs}, Batch size: {batch_size}")

    # Load replay data
    replay_mgr = ReplayBufferManager(replay_dir)
    players = replay_mgr.list_players()
    print(f"  Found {len(players)} players with replay data")

    all_episodes = []
    for player_id in players:
        episodes = replay_mgr.load_player_replays(player_id)
        all_episodes.extend(episodes)
        print(f"    {player_id}: {len(episodes)} episodes")

    if not all_episodes:
        print("ERROR: No replay data found. Record replays first.")
        return

    # Split train/test
    n_test = max(1, len(all_episodes) // 10)
    test_episodes = all_episodes[-n_test:]
    train_episodes = all_episodes[:-n_test]

    print(f"  Training on {len(train_episodes)} episodes, "
          f"testing on {len(test_episodes)} episodes")

    # Create and train model
    model = WorldModel(obs_dim=obs_dim, hidden_size=hidden_size)
    trainer = WorldModelTrainer(model, learning_rate=lr)

    print("\nTraining...")
    metrics = trainer.train_on_replays(
        train_episodes, epochs=epochs, batch_size=batch_size, verbose=True
    )

    print(f"\nTraining complete. Best val loss: {metrics['best_val_loss']:.6f}")
    print(f"Total transitions used: {metrics['total_transitions']}")

    # Evaluate on test set
    print("\nEvaluating on held-out episodes...")
    eval_metrics = trainer.evaluate(test_episodes)
    print(f"  Test obs MSE: {eval_metrics['total_obs_mse']:.6f}")
    print(f"  Test reward MSE: {eval_metrics['reward_mse']:.6f}")
    print(f"  Per-dimension MSE:")

    dim_names = [
        "hero_vel_x", "hero_vel_y", "hero_vel_z", "hero_combo",
        "hero_attacking", "hero_hp", "distance", "angle", "boss_hp",
        "aggression", "dodge", "block", "opener", "pressure",
        "kiting", "combo_completion", "positional_var",
    ]
    for i, mse in enumerate(eval_metrics["per_dim_mse"]):
        name = dim_names[i] if i < len(dim_names) else f"dim_{i}"
        print(f"    {name}: {mse:.6f}")

    # Save model
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, "world_model.pt")
    torch.save(model.state_dict(), model_path)
    print(f"\nModel saved to {model_path}")


def evaluate_world_model(cfg: dict):
    """Evaluate a trained world model on replay data."""
    wm_cfg = cfg.get("world_model", {})
    replay_dir = cfg.get("transfer", {}).get("replay_dir", "./replays")
    obs_dim = cfg.get("env", {}).get("observation_size", 17)
    hidden_size = wm_cfg.get("hidden_size", 128)
    model_dir = wm_cfg.get("model_dir", "./models/world_model")
    model_path = os.path.join(model_dir, "world_model.pt")

    if not os.path.exists(model_path):
        print(f"ERROR: No model found at {model_path}. Train first.")
        return

    # Load model
    model = WorldModel(obs_dim=obs_dim, hidden_size=hidden_size)
    model.load_state_dict(torch.load(model_path, weights_only=True))
    model.eval()

    # Load replay data
    replay_mgr = ReplayBufferManager(replay_dir)
    all_episodes = []
    for player_id in replay_mgr.list_players():
        all_episodes.extend(replay_mgr.load_player_replays(player_id))

    if not all_episodes:
        print("ERROR: No replay data found.")
        return

    trainer = WorldModelTrainer(model)
    metrics = trainer.evaluate(all_episodes)

    print("=== World Model Evaluation ===")
    print(f"  Total obs MSE: {metrics['total_obs_mse']:.6f}")
    print(f"  Reward MSE: {metrics['reward_mse']:.6f}")
    print(f"  Transitions evaluated: {metrics['num_transitions']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train/evaluate Boss AI world model")
    parser.add_argument("command", nargs="?", default="train",
                        choices=["train", "evaluate"],
                        help="Command to run")
    parser.add_argument("--config", type=str, default="config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.command == "train":
        train_world_model(cfg)
    elif args.command == "evaluate":
        evaluate_world_model(cfg)
