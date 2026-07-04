"""
Transfer learning training orchestration.
Trains base model from aggregated data and fine-tunes per player.

Usage:
    python train_transfer.py train_base [--config config.yaml]
    python train_transfer.py train_player --player-id <id> [--config config.yaml]
    python train_transfer.py stats [--config config.yaml]
"""

import argparse
import os

import yaml
from stable_baselines3.common.monitor import Monitor

from boss_env import BossEnv
from rl_algo import resolve_algo, wrap_action_masker
from transfer_learning import TransferLearningManager


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def make_env(cfg: dict, player_id: str = "training", maskable: bool = False):
    env_cfg = cfg["env"]
    # cfg= keeps obs dims consistent across train/infer (G8).
    env = BossEnv(
        host=env_cfg["host"],
        port=env_cfg["port"],
        timeout=env_cfg.get("timeout", 60.0),
        step_delay=env_cfg.get("step_delay", 0.066),
        player_id=player_id,
        cfg=cfg,
    )
    env._max_steps = env_cfg.get("max_steps", 2000)
    env = Monitor(env)
    if maskable:
        env = wrap_action_masker(env)  # outermost, outside Monitor (G2)
    return env


def train_base(cfg: dict):
    """Train base model from aggregated player data or live training."""
    transfer_cfg = cfg.get("transfer", {})
    train_cfg = cfg["training"]
    log_cfg = cfg["logging"]

    manager = TransferLearningManager(
        base_model_dir=transfer_cfg.get("base_model_dir", "./models/base"),
        player_model_dir=transfer_cfg.get("player_model_dir", "./models/players"),
        replay_dir=transfer_cfg.get("replay_dir", "./replays"),
    )

    # Check replay data availability
    stats = manager.get_replay_stats()
    print(f"Replay data: {stats['total_players']} players")
    for pid, count in stats["players"].items():
        print(f"  {pid}: {count} episodes")

    timesteps = train_cfg.get("total_timesteps", 500000)

    AlgoCls, algo_name, maskable = resolve_algo(cfg)
    env = make_env(cfg, player_id="base_training", maskable=maskable)

    print(f"Base model algorithm: {algo_name}")
    model = manager.train_base_model(
        env,
        total_timesteps=timesteps,
        algo_cls=AlgoCls,
        device=train_cfg.get("device", "cpu"),
        tensorboard_log=log_cfg["tensorboard_dir"],
    )

    env.close()
    print("Base model training complete.")


def train_player(cfg: dict, player_id: str):
    """Fine-tune model for a specific player."""
    transfer_cfg = cfg.get("transfer", {})

    manager = TransferLearningManager(
        base_model_dir=transfer_cfg.get("base_model_dir", "./models/base"),
        player_model_dir=transfer_cfg.get("player_model_dir", "./models/players"),
        replay_dir=transfer_cfg.get("replay_dir", "./replays"),
    )

    AlgoCls, algo_name, maskable = resolve_algo(cfg)
    env = make_env(cfg, player_id=player_id, maskable=maskable)

    # Load existing player model or base model
    model, is_new = manager.load_player_model(
        player_id, env=env, device=cfg["training"].get("device", "cpu")
    )

    if model is None:
        print("No base model available. Train a base model first:")
        print("  python train_transfer.py train_base")
        env.close()
        return

    # Mixed-algo fine-tune is invalid: a legacy PPO checkpoint can only be
    # fine-tuned under algorithm: PPO (and MaskablePPO under MaskablePPO).
    model_maskable = model.__class__.__name__ == "MaskablePPO"
    if model_maskable != maskable:
        env.close()
        raise SystemExit(
            f"checkpoint algo ({'MaskablePPO' if model_maskable else 'PPO'}) "
            f"!= training.algorithm ({algo_name}) — legacy PPO checkpoints "
            "fine-tune only under algorithm: PPO"
        )

    if is_new:
        print(f"New player '{player_id}' — starting from base model")
    else:
        print(f"Continuing training for player '{player_id}'")

    fine_tune_steps = transfer_cfg.get("fine_tune_steps_per_episode", 50000)
    fine_tune_lr = transfer_cfg.get("fine_tune_lr", 0.0001)

    model = manager.fine_tune(
        model, env,
        timesteps=fine_tune_steps,
        lr=fine_tune_lr,
    )

    manager.save_player_model(model, player_id)
    env.close()
    print(f"Fine-tuning complete for player '{player_id}'")


def show_stats(cfg: dict):
    """Show transfer learning statistics."""
    transfer_cfg = cfg.get("transfer", {})

    manager = TransferLearningManager(
        base_model_dir=transfer_cfg.get("base_model_dir", "./models/base"),
        player_model_dir=transfer_cfg.get("player_model_dir", "./models/players"),
        replay_dir=transfer_cfg.get("replay_dir", "./replays"),
    )

    print("=== Transfer Learning Stats ===")
    print(f"Base model: {'exists' if manager.has_base_model() else 'not trained'}")

    stats = manager.get_replay_stats()
    print(f"Replay data: {stats['total_players']} players")
    for pid, count in stats["players"].items():
        has_model = "has model" if manager.has_player_model(pid) else "no model"
        print(f"  {pid}: {count} episodes ({has_model})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transfer Learning Training")
    parser.add_argument("command", choices=["train_base", "train_player", "stats"])
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--player-id", type=str, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.command == "train_base":
        train_base(cfg)
    elif args.command == "train_player":
        if not args.player_id:
            print("Error: --player-id required for train_player")
        else:
            train_player(cfg, args.player_id)
    elif args.command == "stats":
        show_stats(cfg)
