"""
Training script for Boss RL agent using Stable Baselines3.
Supports flat PPO / MaskablePPO training with optional constrained learning
wrapper (training.algorithm selects; see rl_algo.py).

For hierarchical training, use train_hierarchical.py instead.
For transfer learning, use train_transfer.py instead.

Usage: python train.py [--config config.yaml] [--resume [path|auto]] [--seed N]
"""

import argparse
import os

import gymnasium as gym
import numpy as np
import yaml
from stable_baselines3.common.callbacks import (
    BaseCallback,
    CallbackList,
    CheckpointCallback,
)
from stable_baselines3.common.monitor import Monitor

from boss_env import BossEnv
from rl_algo import (
    checkpoint_is_maskable,
    find_latest_checkpoint,
    resolve_algo,
    wrap_action_masker,
)


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


class MaskMetricsCallback(BaseCallback):
    """
    Mask-restriction-rate + dropped-decision-proxy TensorBoard logger.

    bridge/dropped_per_step and bridge/exec_mismatch_rate stay 0.0 until the
    C++ telemetry pass lands (exec/dropped JSON fields) — the TB channels
    exist from day one so dashboards don't need re-plumbing later.
    """

    def __init__(self, verbose=0):
        super().__init__(verbose)
        self._zero_accumulators()

    def _zero_accumulators(self):
        self._n_steps = 0
        self._restricted_steps = 0
        self._masked_off_total = 0
        self._illegal_choice = 0
        self._dropped_total = 0
        self._exec_mismatch = 0
        self._eps_subst = 0

    def _on_step(self) -> bool:
        info = self.locals["infos"][0]
        action = int(np.asarray(self.locals["actions"]).flatten()[0])

        mask = info.get("action_mask")
        if mask is None:
            mask = np.ones(5, dtype=bool)

        self._n_steps += 1
        n_legal = int(mask.sum())
        if n_legal < 5:
            self._restricted_steps += 1
        self._masked_off_total += 5 - n_legal
        # Must stay 0 under MaskablePPO — sanity metric for the legacy path.
        # Compare against the PRE-step mask (the one the policy sampled
        # under): info["action_mask"] is the POST-step mask, and legality
        # flipping between consecutive bridge observations (range/facing
        # changes) would otherwise count false positives.
        pre_mask = info.get("action_mask_pre")
        if pre_mask is None:
            pre_mask = mask
        if not pre_mask[action]:
            self._illegal_choice += 1

        self._dropped_total += int(info.get("dropped_actions", 0))
        exec_action = int(info.get("exec_action", -1))
        if exec_action >= 0 and exec_action != action:
            self._exec_mismatch += 1
        if info.get("epsilon_substituted"):
            self._eps_subst += 1
        return True

    def _on_rollout_end(self) -> None:
        n = max(self._n_steps, 1)
        self.logger.record("mask/restriction_rate", self._restricted_steps / n)
        self.logger.record("mask/mean_masked_off", self._masked_off_total / (5 * n))
        self.logger.record("mask/illegal_choice_rate", self._illegal_choice / n)
        self.logger.record("bridge/dropped_per_step", self._dropped_total / n)
        self.logger.record("bridge/exec_mismatch_rate", self._exec_mismatch / n)
        self.logger.record("bridge/epsilon_subst_rate", self._eps_subst / n)
        self._zero_accumulators()


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def make_env(cfg: dict, maskable: bool) -> gym.Env:
    env_cfg = cfg["env"]
    base_env = BossEnv(
        host=env_cfg["host"],
        port=env_cfg["port"],
        timeout=env_cfg.get("timeout", 60.0),
        step_delay=env_cfg.get("step_delay", 0.066),
        player_id=env_cfg.get("player_id", "training"),
        cfg=cfg,  # obs-dim consistency: irl/emotion flags shape the space here too
        heartbeat_interval=env_cfg.get("heartbeat_interval", 0.0),
    )
    base_env._max_steps = env_cfg.get("max_steps", 2000)
    env: gym.Env = base_env

    # Record replays per player_id (persona) for MAML / IRL / world-model /
    # transfer training. Innermost wrapper on purpose: raw rewards, and the
    # action recorded is the one actually executed.
    transfer_cfg = cfg.get("transfer", {})
    if transfer_cfg.get("record_replays", False):
        from replay_recorder import ReplayRecorder

        replay_dir = transfer_cfg.get("replay_dir", "./replays")
        player_id = env_cfg.get("player_id", "training")
        env = ReplayRecorder(env, replay_dir=replay_dir, player_id=player_id)
        print(f"Replay recording enabled -> {replay_dir}/{player_id}/")

    # Wrap with constrained learning if enabled
    constraints_cfg = cfg.get("constraints", {})
    if constraints_cfg.get("enabled", False):
        from constrained_wrapper import ConstrainedBossEnv

        emotion_enabled = cfg.get("emotion", {}).get("enabled", False)
        env = ConstrainedBossEnv(
            env,
            target_win_rate=constraints_cfg.get("target_win_rate", 0.45),
            win_rate_window=constraints_cfg.get("win_rate_window", 100),
            max_epsilon=constraints_cfg.get("max_epsilon", 0.3),
            lead_change_bonus=constraints_cfg.get("lead_change_bonus", 0.5),
            close_fight_bonus=constraints_cfg.get("close_fight_bonus", 0.1),
            close_fight_threshold=constraints_cfg.get("close_fight_threshold", 0.2),
            emotion_enabled=emotion_enabled,
            emotion_obs_start=base_env._emotion_start if emotion_enabled else -1,
        )
        print("Constrained learning enabled "
              f"(target win rate: {constraints_cfg.get('target_win_rate', 0.45):.0%})")

    env = Monitor(env)

    # ActionMasker OUTSIDE Monitor: DummyVecEnv.env_method("action_masks")
    # getattrs the outermost env and gymnasium 1.2.x wrappers no longer
    # forward attributes (G2). Monitor's info["episode"] is unaffected.
    if maskable:
        env = wrap_action_masker(env)

    return env


def train(cfg: dict, resume_path: str | None = None, seed: int | None = None):
    train_cfg = cfg["training"]
    log_cfg = cfg["logging"]

    os.makedirs(log_cfg["tensorboard_dir"], exist_ok=True)
    os.makedirs(log_cfg["checkpoint_dir"], exist_ok=True)

    AlgoCls, algo_name, maskable = resolve_algo(cfg)
    device = train_cfg.get("device", "cpu")

    if seed is None:
        seed = train_cfg.get("seed")
    if seed is not None:
        # SB3 seeds torch/np/random + action_space; ConstrainedBossEnv uses
        # global np.random for epsilon substitution, so seed that too.
        np.random.seed(seed)

    env = make_env(cfg, maskable)
    checkpoint_dir = log_cfg["checkpoint_dir"]

    if resume_path is not None:
        if resume_path == "auto":
            resume_path = find_latest_checkpoint(checkpoint_dir)
            if resume_path is None:
                raise SystemExit(
                    f"--resume auto: no *.zip checkpoints in {checkpoint_dir}"
                )
        if checkpoint_is_maskable(resume_path) != maskable:
            raise SystemExit(
                "checkpoint algo != training.algorithm — legacy PPO checkpoints "
                "resume only under algorithm: PPO"
            )
        model = AlgoCls.load(
            resume_path,
            env=env,
            device=device,
            tensorboard_log=log_cfg["tensorboard_dir"],
        )
        if seed is not None:
            # .load() ran _setup_model(), which re-seeded torch/np/random
            # with the seed STORED IN THE CHECKPOINT — clobbering the
            # CLI/config seed applied above. Re-apply so --seed is honored
            # on resume too (including the global np.random stream used by
            # ConstrainedBossEnv epsilon substitution).
            model.set_random_seed(seed)
            np.random.seed(seed)
        print(f"Resuming {algo_name} from {resume_path}")
        reset_num_timesteps = False
    else:
        model = AlgoCls(
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
            device=device,
            seed=seed,
            verbose=1,
        )
        reset_num_timesteps = True

    # Callbacks
    checkpoint_cb = CheckpointCallback(
        save_freq=log_cfg["checkpoint_freq"],
        save_path=checkpoint_dir,
        name_prefix="boss_rl",
    )

    callback_list = [checkpoint_cb, MaskMetricsCallback()]

    # Add win rate logging if constrained learning is enabled
    if cfg.get("constraints", {}).get("enabled", False):
        callback_list.append(WinRateCallback())

    callbacks = CallbackList(callback_list)

    print(f"Starting {algo_name} training for {train_cfg['total_timesteps']} timesteps...")
    print(f"TensorBoard: tensorboard --logdir {log_cfg['tensorboard_dir']}")

    try:
        model.learn(
            total_timesteps=train_cfg["total_timesteps"],
            callback=callbacks,
            log_interval=log_cfg["log_interval"],
            reset_num_timesteps=reset_num_timesteps,
        )

        # Save final model
        final_path = os.path.join(checkpoint_dir, "final_model")
        model.save(final_path)
        print(f"Training complete. Model saved to {final_path}")
    except (KeyboardInterrupt, Exception) as e:
        # Crash-autosave: an overnight run that dies (socket, UE crash, ^C)
        # still leaves a resumable checkpoint behind.
        autosave_path = os.path.join(checkpoint_dir, "autosave_on_exit")
        model.save(autosave_path)
        print(f"Training interrupted ({type(e).__name__}). Autosaved to {autosave_path}")
        if not isinstance(e, KeyboardInterrupt):
            raise
    finally:
        env.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Boss RL Agent")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config file")
    parser.add_argument(
        "--player-id",
        type=str,
        default=None,
        help="Override env.player_id (e.g. an AutoHero persona name) so replay/"
             "transfer data is keyed per persona: replays/<player_id>/",
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="auto",
        default=None,
        help="Resume from a checkpoint .zip; bare --resume picks the newest "
             "zip in logging.checkpoint_dir",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Override training.seed (pins net init + sampling; the live UE "
             "env itself is not reproducible)",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.player_id:
        cfg["env"]["player_id"] = args.player_id
        print(f"player_id overridden to '{args.player_id}'")
    train(cfg, resume_path=args.resume, seed=args.seed)
