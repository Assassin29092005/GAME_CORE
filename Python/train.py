"""
Training script for Boss RL agent using Stable Baselines3.
Supports flat PPO training with optional constrained learning wrapper.

For hierarchical training, use train_hierarchical.py instead.
For transfer learning, use train_transfer.py instead.

Usage: python train.py [--config config.yaml]
"""

import argparse
import os

import yaml
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import (
    BaseCallback,
    CallbackList,
    CheckpointCallback,
)
from stable_baselines3.common.monitor import Monitor

from boss_env import BossEnv


class WinRateCallback(BaseCallback):
    """Logs constrained learning metrics (win rate, epsilon) to TensorBoard."""

    def __init__(self, verbose=0):
        super().__init__(verbose)

    def _on_step(self) -> bool:
        # Unwrap to find ConstrainedBossEnv
        env = self.training_env.envs[0]
        unwrapped = env
        while hasattr(unwrapped, "env"):
            if hasattr(unwrapped, "get_win_rate"):
                self.logger.record("boss/win_rate", unwrapped.get_win_rate())
                self.logger.record("boss/incompetence_epsilon", unwrapped.get_epsilon())
                break
            unwrapped = unwrapped.env
        return True


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def make_env(cfg: dict) -> Monitor:
    env_cfg = cfg["env"]
    env = BossEnv(
        host=env_cfg["host"],
        port=env_cfg["port"],
        step_delay=env_cfg.get("step_delay", 0.066),
        player_id=env_cfg.get("player_id", "training"),
    )
    env._max_steps = env_cfg.get("max_steps", 2000)

    # Wrap with constrained learning if enabled
    constraints_cfg = cfg.get("constraints", {})
    if constraints_cfg.get("enabled", False):
        from constrained_wrapper import ConstrainedBossEnv

        env = ConstrainedBossEnv(
            env,
            target_win_rate=constraints_cfg.get("target_win_rate", 0.45),
            win_rate_window=constraints_cfg.get("win_rate_window", 100),
            max_epsilon=constraints_cfg.get("max_epsilon", 0.3),
            lead_change_bonus=constraints_cfg.get("lead_change_bonus", 0.5),
            close_fight_bonus=constraints_cfg.get("close_fight_bonus", 0.1),
            close_fight_threshold=constraints_cfg.get("close_fight_threshold", 0.2),
        )
        print("Constrained learning enabled "
              f"(target win rate: {constraints_cfg.get('target_win_rate', 0.45):.0%})")

    return Monitor(env)


def train(cfg: dict):
    train_cfg = cfg["training"]
    log_cfg = cfg["logging"]

    os.makedirs(log_cfg["tensorboard_dir"], exist_ok=True)
    os.makedirs(log_cfg["checkpoint_dir"], exist_ok=True)

    env = make_env(cfg)

    # Select algorithm
    algo_name = train_cfg["algorithm"].upper()

    if algo_name == "PPO":
        model = PPO(
            "MlpPolicy",
            env,
            learning_rate=train_cfg["learning_rate"],
            n_steps=train_cfg["n_steps"],
            batch_size=train_cfg["batch_size"],
            gamma=train_cfg["gamma"],
            gae_lambda=train_cfg["gae_lambda"],
            clip_range=train_cfg["clip_range"],
            ent_coef=train_cfg["ent_coef"],
            n_epochs=train_cfg["n_epochs"],
            tensorboard_log=log_cfg["tensorboard_dir"],
            verbose=1,
        )
    else:
        raise ValueError(
            f"Unsupported algorithm: {algo_name}. "
            "Use PPO for discrete action spaces."
        )

    # Callbacks
    checkpoint_cb = CheckpointCallback(
        save_freq=log_cfg["checkpoint_freq"],
        save_path=log_cfg["checkpoint_dir"],
        name_prefix="boss_rl",
    )

    callback_list = [checkpoint_cb]

    # Add win rate logging if constrained learning is enabled
    if cfg.get("constraints", {}).get("enabled", False):
        callback_list.append(WinRateCallback())

    callbacks = CallbackList(callback_list)

    print(f"Starting {algo_name} training for {train_cfg['total_timesteps']} timesteps...")
    print(f"TensorBoard: tensorboard --logdir {log_cfg['tensorboard_dir']}")

    model.learn(
        total_timesteps=train_cfg["total_timesteps"],
        callback=callbacks,
        log_interval=log_cfg["log_interval"],
    )

    # Save final model
    final_path = os.path.join(log_cfg["checkpoint_dir"], "final_model")
    model.save(final_path)
    print(f"Training complete. Model saved to {final_path}")

    env.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Boss RL Agent")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config file")
    args = parser.parse_args()

    cfg = load_config(args.config)
    train(cfg)
