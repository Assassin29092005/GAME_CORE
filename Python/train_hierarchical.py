"""
Hierarchical RL training script.
3-phase training: pretrain tactician, train strategist, joint fine-tune.

Usage:
    python train_hierarchical.py [--config config.yaml] [--phase A|B|C|all]
"""

import argparse
import os

import gymnasium as gym
import numpy as np
import yaml
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CallbackList, CheckpointCallback
from stable_baselines3.common.monitor import Monitor

from boss_env import BossEnv
from hierarchical_env import HierarchicalBossEnv, StrategistEnv, NUM_STRATEGIES
from rl_algo import load_checkpoint_auto, resolve_algo, wrap_action_masker


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def make_base_env(cfg: dict) -> BossEnv:
    env_cfg = cfg["env"]
    # cfg= keeps obs dims consistent with infer.py --hierarchical (G8).
    env = BossEnv(
        host=env_cfg["host"],
        port=env_cfg["port"],
        timeout=env_cfg.get("timeout", 60.0),
        step_delay=env_cfg.get("step_delay", 0.066),
        player_id=env_cfg.get("player_id", "training"),
        cfg=cfg,
    )
    env._max_steps = env_cfg.get("max_steps", 2000)
    return env


class RandomStrategySwitcher(gym.Wrapper):
    """Randomly switches strategy every N steps during Phase A pretraining.

    Must wrap HierarchicalBossEnv DIRECTLY (not through Monitor) —
    gymnasium 1.2.x wrappers no longer forward attributes, so
    needs_strategy_update() has to be a real attribute of self.env.
    """

    def __init__(self, env: HierarchicalBossEnv):
        super().__init__(env)
        self._step_count = 0

    def step(self, action):
        self._step_count += 1
        if self.env.needs_strategy_update():
            self.env.set_strategy(int(np.random.randint(0, NUM_STRATEGIES)))
        return self.env.step(action)


class StrategistGuidedWrapper(gym.Wrapper):
    """Phase C: strategist picks strategies while the tactician fine-tunes."""

    def __init__(self, env: HierarchicalBossEnv, strat_model):
        super().__init__(env)
        self.strat_model = strat_model

    def step(self, action):
        if self.env.needs_strategy_update():
            base_obs = self.env.get_base_obs(self.env._augment_obs(self.env._prev_obs))
            strat_action, _ = self.strat_model.predict(base_obs, deterministic=False)
            self.env.set_strategy(int(strat_action))
        return self.env.step(action)


def phase_a_pretrain_tactician(cfg: dict):
    """
    Phase A: Pretrain tactician with random strategy assignments.
    The tactician learns all 5 actions conditioned on each strategy archetype.
    """
    hier_cfg = cfg.get("hierarchical", {})
    log_cfg = cfg["logging"]
    strategy_interval = hier_cfg.get("strategy_interval", 30)
    tactician_lr = hier_cfg.get("tactician_lr", 0.0003)
    steps = hier_cfg.get("pretrain_tactician_steps", 200000)

    print(f"=== Phase A: Pretrain Tactician ({steps} steps) ===")

    AlgoCls, algo_name, maskable = resolve_algo(cfg)
    device = cfg["training"].get("device", "cpu")

    base_env = make_base_env(cfg)
    hier_env = HierarchicalBossEnv(base_env, strategy_interval=strategy_interval)
    # Wrapper order (inside->out): hier -> switcher -> Monitor -> ActionMasker.
    # Single Monitor; ActionMasker outermost (G2).
    env = RandomStrategySwitcher(hier_env)
    env = Monitor(env)
    if maskable:
        env = wrap_action_masker(env)

    tactician = AlgoCls(
        "MlpPolicy",
        env,
        learning_rate=tactician_lr,
        n_steps=2048,
        batch_size=64,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        n_epochs=10,
        device=device,
        tensorboard_log=log_cfg["tensorboard_dir"],
        verbose=1,
    )
    print(f"Tactician algorithm: {algo_name}")

    save_dir = os.path.join(log_cfg["checkpoint_dir"], "hierarchical")
    os.makedirs(save_dir, exist_ok=True)

    checkpoint_cb = CheckpointCallback(
        save_freq=10000,
        save_path=save_dir,
        name_prefix="tactician",
    )

    tactician.learn(
        total_timesteps=steps,
        callback=checkpoint_cb,
        log_interval=10,
    )

    tactician.save(os.path.join(save_dir, "tactician"))
    print(f"Phase A complete. Tactician saved to {save_dir}/tactician.zip")

    env.close()
    return tactician


def phase_b_train_strategist(cfg: dict, tactician: PPO | None = None):
    """
    Phase B: Train strategist with frozen tactician.
    Each strategist 'step' = N tactician steps.
    """
    hier_cfg = cfg.get("hierarchical", {})
    log_cfg = cfg["logging"]
    strategy_interval = hier_cfg.get("strategy_interval", 30)
    strategist_lr = hier_cfg.get("strategist_lr", 0.0001)
    steps = hier_cfg.get("train_strategist_steps", 100000)
    save_dir = os.path.join(log_cfg["checkpoint_dir"], "hierarchical")

    print(f"=== Phase B: Train Strategist ({steps} steps) ===")

    # Load tactician if not provided (legacy PPO or MaskablePPO zips both load)
    if tactician is None:
        tactician_path = os.path.join(save_dir, "tactician.zip")
        tactician, _ = load_checkpoint_auto(tactician_path)
        print(f"Loaded tactician from {tactician_path}")

    base_env = make_base_env(cfg)
    hier_env = HierarchicalBossEnv(base_env, strategy_interval=strategy_interval)
    # StrategistEnv handles tactician masks internally; the strategist itself
    # is plain PPO on Discrete(4) — never masked, no ActionMasker.
    strat_env = StrategistEnv(hier_env, tactician)
    env = Monitor(strat_env)

    strategist = PPO(
        "MlpPolicy",
        env,
        learning_rate=strategist_lr,
        n_steps=512,  # fewer steps since each step is N tactician steps
        batch_size=32,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.02,  # higher entropy for strategy exploration
        n_epochs=10,
        device="cpu",
        tensorboard_log=log_cfg["tensorboard_dir"],
        verbose=1,
    )

    checkpoint_cb = CheckpointCallback(
        save_freq=5000,
        save_path=save_dir,
        name_prefix="strategist",
    )

    strategist.learn(
        total_timesteps=steps,
        callback=checkpoint_cb,
        log_interval=10,
    )

    strategist.save(os.path.join(save_dir, "strategist"))
    print(f"Phase B complete. Strategist saved to {save_dir}/strategist.zip")

    env.close()
    return strategist


def phase_c_joint_finetune(cfg: dict, tactician: PPO | None = None, strategist: PPO | None = None):
    """
    Phase C: Joint fine-tuning with alternating frozen periods.
    Fine-tune tactician with strategist providing strategies, then vice versa.
    """
    hier_cfg = cfg.get("hierarchical", {})
    log_cfg = cfg["logging"]
    strategy_interval = hier_cfg.get("strategy_interval", 30)
    steps = hier_cfg.get("joint_finetune_steps", 200000)
    save_dir = os.path.join(log_cfg["checkpoint_dir"], "hierarchical")

    print(f"=== Phase C: Joint Fine-tune ({steps} steps) ===")

    _, _, want_maskable = resolve_algo(cfg)

    # Load models if not provided
    if tactician is None:
        tactician, tac_maskable = load_checkpoint_auto(
            os.path.join(save_dir, "tactician.zip")
        )
    else:
        tac_maskable = tactician.__class__.__name__ == "MaskablePPO"
    # Mixed-algo fine-tune is invalid — same rule as transfer.
    if tac_maskable != want_maskable:
        raise SystemExit(
            "tactician checkpoint algo != training.algorithm — legacy PPO "
            "tacticians fine-tune only under algorithm: PPO (and vice versa)"
        )
    if strategist is None:
        strategist = PPO.load(os.path.join(save_dir, "strategist.zip"))

    # Fine-tune tactician with strategist providing strategies
    half_steps = steps // 2

    print(f"  Fine-tuning tactician ({half_steps} steps)...")
    base_env = make_base_env(cfg)
    hier_env = HierarchicalBossEnv(base_env, strategy_interval=strategy_interval)

    guided_env = StrategistGuidedWrapper(hier_env, strategist)
    env = Monitor(guided_env)
    if tac_maskable:
        env = wrap_action_masker(env)

    # Continue training tactician with lower LR
    tactician.set_env(env)
    tactician.learning_rate = hier_cfg.get("tactician_lr", 0.0003) * 0.5

    tactician.learn(
        total_timesteps=half_steps,
        log_interval=10,
    )

    env.close()

    # Fine-tune strategist with updated tactician
    print(f"  Fine-tuning strategist ({half_steps} steps)...")
    base_env2 = make_base_env(cfg)
    hier_env2 = HierarchicalBossEnv(base_env2, strategy_interval=strategy_interval)
    strat_env = StrategistEnv(hier_env2, tactician)
    env2 = Monitor(strat_env)

    strategist.set_env(env2)
    strategist.learning_rate = hier_cfg.get("strategist_lr", 0.0001) * 0.5

    strategist.learn(
        total_timesteps=half_steps // strategy_interval,  # each step is N steps
        log_interval=10,
    )

    env2.close()

    # Save final models
    tactician.save(os.path.join(save_dir, "tactician"))
    strategist.save(os.path.join(save_dir, "strategist"))
    print(f"Phase C complete. Models saved to {save_dir}")


def train_all(cfg: dict):
    """Run all 3 phases sequentially."""
    tactician = phase_a_pretrain_tactician(cfg)
    strategist = phase_b_train_strategist(cfg, tactician=tactician)
    phase_c_joint_finetune(cfg, tactician=tactician, strategist=strategist)
    print("\n=== All phases complete! ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hierarchical Boss RL Training")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--phase", type=str, default="all",
                        choices=["A", "B", "C", "all"],
                        help="Training phase: A (tactician), B (strategist), C (joint), all")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.phase == "A":
        phase_a_pretrain_tactician(cfg)
    elif args.phase == "B":
        phase_b_train_strategist(cfg)
    elif args.phase == "C":
        phase_c_joint_finetune(cfg)
    else:
        train_all(cfg)
