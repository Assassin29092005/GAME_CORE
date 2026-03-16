"""
MAML meta-training script for Boss AI.
Trains meta-parameters that adapt to new players in 2-3 gradient steps.

Usage:
    python train_maml.py meta_train [--config config.yaml]
    python train_maml.py adapt --player-id player1
    python train_maml.py evaluate --player-id player1
    python train_maml.py stats
"""

import argparse

import yaml

from maml_trainer import MAMLTrainer


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def train_meta(cfg: dict):
    """Run MAML meta-training on all available player data."""
    maml_cfg = cfg.get("maml", {})
    replay_dir = cfg.get("transfer", {}).get("replay_dir", "./replays")
    obs_dim = cfg.get("env", {}).get("observation_size", 17)

    trainer = MAMLTrainer(
        obs_dim=obs_dim,
        num_actions=5,
        hidden_size=maml_cfg.get("policy_hidden_size", 64),
        meta_lr=maml_cfg.get("meta_lr", 0.001),
        replay_dir=replay_dir,
    )

    # Optional TensorBoard logging
    tb_writer = None
    try:
        from torch.utils.tensorboard import SummaryWriter
        tb_dir = cfg.get("logging", {}).get("tensorboard_dir", "./tb_logs")
        tb_writer = SummaryWriter(f"{tb_dir}/maml")
    except ImportError:
        pass

    metrics = trainer.meta_train(
        num_iterations=maml_cfg.get("meta_iterations", 5000),
        tasks_per_batch=maml_cfg.get("tasks_per_batch", 4),
        inner_lr=maml_cfg.get("inner_lr", 0.01),
        inner_steps=maml_cfg.get("inner_steps", 3),
        min_episodes=maml_cfg.get("min_episodes_per_player", 3),
        support_fraction=maml_cfg.get("support_fraction", 0.5),
        tb_writer=tb_writer,
    )

    if "error" not in metrics:
        model_dir = maml_cfg.get("meta_model_dir", "./models/maml")
        trainer.save_meta_model(model_dir)
        print(f"\nMeta-model saved to {model_dir}")
        print(f"Best meta-loss: {metrics['best_loss']:.6f}")
        print(f"Final meta-loss: {metrics['final_loss']:.6f}")

    if tb_writer:
        tb_writer.close()


def adapt_player(cfg: dict, player_id: str):
    """Adapt meta-model to a specific player and report results."""
    maml_cfg = cfg.get("maml", {})
    replay_dir = cfg.get("transfer", {}).get("replay_dir", "./replays")
    obs_dim = cfg.get("env", {}).get("observation_size", 17)

    trainer = MAMLTrainer(
        obs_dim=obs_dim,
        num_actions=5,
        hidden_size=maml_cfg.get("policy_hidden_size", 64),
        replay_dir=replay_dir,
    )

    model_dir = maml_cfg.get("meta_model_dir", "./models/maml")
    trainer.load_meta_model(model_dir)
    print(f"Loaded meta-model from {model_dir}")

    inner_steps = maml_cfg.get("inner_steps", 3)
    inner_lr = maml_cfg.get("inner_lr", 0.01)

    adapted = trainer.adapt_to_player(
        player_id,
        num_inner_steps=inner_steps,
        inner_lr=inner_lr,
    )

    if adapted is None:
        print(f"No replay data for player '{player_id}'. Cannot adapt.")
        return

    print(f"Adapted to player '{player_id}' in {inner_steps} gradient steps.")

    # Save adapted model
    import torch
    from pathlib import Path
    adapted_dir = Path(model_dir) / "adapted" / player_id
    adapted_dir.mkdir(parents=True, exist_ok=True)
    torch.save(adapted.state_dict(), adapted_dir / "adapted_policy.pt")
    print(f"Adapted policy saved to {adapted_dir}")


def evaluate_player(cfg: dict, player_id: str):
    """Evaluate adaptation quality at each inner step."""
    maml_cfg = cfg.get("maml", {})
    replay_dir = cfg.get("transfer", {}).get("replay_dir", "./replays")
    obs_dim = cfg.get("env", {}).get("observation_size", 17)

    trainer = MAMLTrainer(
        obs_dim=obs_dim,
        num_actions=5,
        hidden_size=maml_cfg.get("policy_hidden_size", 64),
        replay_dir=replay_dir,
    )

    model_dir = maml_cfg.get("meta_model_dir", "./models/maml")
    trainer.load_meta_model(model_dir)

    results = trainer.evaluate_adaptation(
        player_id,
        max_inner_steps=5,
        inner_lr=maml_cfg.get("inner_lr", 0.01),
    )

    if "error" in results:
        print(results["error"])
        return

    print(f"\n=== Adaptation Evaluation for '{player_id}' ===")
    print(f"{'Inner Steps':<15} {'Query Loss':<15} {'Improvement':<15}")
    print("-" * 45)

    base_loss = results[0]
    for steps, loss in sorted(results.items()):
        improvement = ((base_loss - loss) / abs(base_loss) * 100) if base_loss != 0 else 0
        marker = " <-- sweet spot" if steps == 3 else ""
        print(f"{steps:<15} {loss:<15.6f} {improvement:>+10.1f}%{marker}")

    print(f"\nKey insight: loss at step 3 should be close to loss at step 5.")
    print(f"If so, MAML achieves in 3 steps what fine-tuning needs 50k+ for.")


def show_stats(cfg: dict):
    """Show available player data statistics."""
    replay_dir = cfg.get("transfer", {}).get("replay_dir", "./replays")
    maml_cfg = cfg.get("maml", {})
    min_episodes = maml_cfg.get("min_episodes_per_player", 3)

    from replay_buffer_manager import ReplayBufferManager
    mgr = ReplayBufferManager(replay_dir)

    players = mgr.list_players()
    print(f"\n=== Player Data Statistics ===")
    print(f"Replay directory: {replay_dir}")
    print(f"Minimum episodes for MAML: {min_episodes}")
    print(f"\n{'Player ID':<20} {'Episodes':<12} {'MAML Ready':<12}")
    print("-" * 44)

    qualified = 0
    for player_id in sorted(players):
        count = mgr.get_player_episode_count(player_id)
        ready = "Yes" if count >= min_episodes else "No"
        if count >= min_episodes:
            qualified += 1
        print(f"{player_id:<20} {count:<12} {ready:<12}")

    print(f"\nTotal: {len(players)} players, {qualified} qualified for MAML")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MAML meta-training for Boss AI")
    parser.add_argument(
        "command",
        choices=["meta_train", "adapt", "evaluate", "stats"],
        help="Command to run",
    )
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--player-id", type=str, default=None,
                        help="Player ID for adapt/evaluate commands")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.command == "meta_train":
        train_meta(cfg)
    elif args.command == "adapt":
        if not args.player_id:
            print("ERROR: --player-id required for adapt command")
        else:
            adapt_player(cfg, args.player_id)
    elif args.command == "evaluate":
        if not args.player_id:
            print("ERROR: --player-id required for evaluate command")
        else:
            evaluate_player(cfg, args.player_id)
    elif args.command == "stats":
        show_stats(cfg)
