"""
Inference script for running a trained Boss RL model in real-time.
Supports flat PPO, hierarchical, transfer learning, IRL-augmented,
planning (world model), and MAML meta-learned models.

Usage:
    python infer.py [--config config.yaml] [--model path/to/model.zip]
    python infer.py --hierarchical --model checkpoints/hierarchical/
    python infer.py --transfer --player-id player1
    python infer.py --irl --player-id player1
    python infer.py --planning --player-id player1
    python infer.py --maml --player-id player1
"""

import argparse

import numpy as np
import yaml
from stable_baselines3 import PPO

from boss_env import BossEnv


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def _make_env(cfg: dict, player_id: str = "default") -> BossEnv:
    """Create a BossEnv with dynamic observation augmentation from config."""
    env_cfg = cfg["env"]
    return BossEnv(
        host=env_cfg["host"],
        port=env_cfg["port"],
        step_delay=env_cfg.get("step_delay", 0.066),
        player_id=player_id,
        cfg=cfg,
    )


def infer_flat(cfg: dict, model_path: str, deterministic: bool = True,
               player_id: str = "default"):
    """Standard flat PPO inference."""
    env = _make_env(cfg, player_id)

    model = PPO.load(model_path, env=env)
    print(f"Loaded PPO model from {model_path}")

    _run_inference_loop(env, model, deterministic)


def infer_hierarchical(cfg: dict, model_dir: str, deterministic: bool = True,
                       player_id: str = "default"):
    """Hierarchical inference with strategist + tactician."""
    from hierarchical_policy import HierarchicalAgent

    hier_cfg = cfg.get("hierarchical", {})

    env = _make_env(cfg, player_id)

    strategy_interval = hier_cfg.get("strategy_interval", 30)
    agent = HierarchicalAgent.load(model_dir, strategy_interval=strategy_interval)

    action_names = ["Attack", "Block", "Dodge", "Approach", "Retreat"]

    print("Starting hierarchical inference. Press Ctrl+C to stop.")
    print(f"Deterministic: {deterministic}")

    episode = 0
    try:
        while True:
            obs, info = env.reset()
            agent.reset()
            episode += 1
            total_reward = 0.0
            steps = 0
            done = False

            print(f"\n--- Episode {episode} ---")

            while not done:
                action, agent_info = agent.predict(obs, deterministic=deterministic)

                obs, reward, terminated, truncated, info = env.step(action)
                total_reward += reward
                steps += 1
                done = terminated or truncated

                if agent_info.get("strategy_changed"):
                    print(f"  [Strategy] -> {agent_info['strategy_name']}")

                if steps % 50 == 0:
                    print(
                        f"  Step {steps}: {action_names[action]} "
                        f"({agent_info['strategy_name']}), "
                        f"Boss HP: {info['boss_hp']:.1%}, "
                        f"Hero HP: {info['hero_hp']:.1%}, "
                        f"Reward: {reward:.2f}"
                    )

            print(
                f"Episode {episode} finished: {steps} steps, "
                f"Total reward: {total_reward:.2f}, "
                f"Boss HP: {info['boss_hp']:.1%}, "
                f"Hero HP: {info['hero_hp']:.1%}"
            )
    except KeyboardInterrupt:
        print(f"\nStopped after {episode} episodes.")
    finally:
        env.close()


def infer_transfer(cfg: dict, player_id: str, deterministic: bool = True):
    """Transfer learning inference — loads per-player model."""
    from transfer_learning import TransferLearningManager

    transfer_cfg = cfg.get("transfer", {})

    manager = TransferLearningManager(
        base_model_dir=transfer_cfg.get("base_model_dir", "./models/base"),
        player_model_dir=transfer_cfg.get("player_model_dir", "./models/players"),
    )

    env = _make_env(cfg, player_id)

    model, is_new = manager.load_player_model(player_id, env=env)
    if model is None:
        print("No model available. Train a base model first.")
        return

    if is_new:
        print(f"Using base model for new player '{player_id}'")

    _run_inference_loop(env, model, deterministic)


def infer_irl(cfg: dict, model_path: str, player_id: str = "default",
              deterministic: bool = True):
    """
    IRL-augmented inference: loads IRL model, augments observations with
    predicted player action distribution P(a|s), then runs PPO policy.
    """
    from irl_player_model import MaxEntIRL
    from replay_buffer_manager import ReplayBufferManager

    irl_cfg = cfg.get("irl", {})
    model_dir = irl_cfg.get("model_dir", "./models/irl")

    # Enable IRL in config for BossEnv
    cfg_with_irl = {**cfg, "irl": {**irl_cfg, "enabled": True}}
    env = _make_env(cfg_with_irl, player_id)

    # Train or load IRL model for this player
    irl_path = f"{model_dir}/{player_id}"
    import os
    if os.path.exists(f"{irl_path}/irl_model.npz"):
        irl_model = MaxEntIRL.load(irl_path)
        print(f"Loaded IRL model for player '{player_id}'")
    else:
        print(f"No trained IRL model for '{player_id}'. Training from replay data...")
        replay_dir = cfg.get("transfer", {}).get("replay_dir", "./replays")
        replay_mgr = ReplayBufferManager(replay_dir)
        trajectories = replay_mgr.get_player_trajectories(player_id)

        min_eps = irl_cfg.get("min_episodes_for_irl", 2)
        if len(trajectories) < min_eps:
            print(f"Insufficient data ({len(trajectories)} episodes, need {min_eps}). "
                  f"Running without IRL augmentation.")
            irl_model = None
        else:
            irl_model = MaxEntIRL(
                feature_dim=irl_cfg.get("feature_dim", 20),
                learning_rate=irl_cfg.get("learning_rate", 0.01),
                n_iterations=irl_cfg.get("n_iterations", 200),
            )
            irl_model.train(trajectories)
            irl_model.save(irl_path)
            print(f"IRL model trained and saved to {irl_path}")

    # Inject the IRL model into the env
    env._irl_model = irl_model

    model = PPO.load(model_path, env=env)
    print(f"Loaded PPO model from {model_path}")

    _run_inference_loop(env, model, deterministic)


def infer_planning(cfg: dict, model_path: str, player_id: str = "default",
                   deterministic: bool = True):
    """
    Planning inference: uses world model + IRL for lookahead action selection.
    Falls back to policy when planner is unavailable.
    """
    from planning import BossPlanner
    from world_model import WorldModel
    from irl_player_model import MaxEntIRL

    wm_cfg = cfg.get("world_model", {})
    irl_cfg = cfg.get("irl", {})

    # Enable IRL + world model in config for BossEnv
    cfg_aug = {
        **cfg,
        "irl": {**irl_cfg, "enabled": True},
        "world_model": {**wm_cfg, "record_player_actions": True},
    }
    env = _make_env(cfg_aug, player_id)

    # Load models
    import os
    import torch

    wm_path = f"{wm_cfg.get('model_dir', './models/world_model')}/world_model.pt"
    irl_path = f"{irl_cfg.get('model_dir', './models/irl')}/{player_id}"

    irl_model = None
    if os.path.exists(f"{irl_path}/irl_model.npz"):
        irl_model = MaxEntIRL.load(irl_path)

    world_mod = None
    if os.path.exists(wm_path):
        obs_dim = env.BASE_OBS_SIZE
        world_mod = WorldModel(obs_dim=obs_dim,
                               hidden_size=wm_cfg.get("hidden_size", 128))
        world_mod.load_state_dict(torch.load(wm_path, weights_only=True))
        world_mod.eval()

    model = PPO.load(model_path, env=env)

    planning_weight = wm_cfg.get("planning_weight", 0.5)
    lookahead = wm_cfg.get("lookahead_depth", 2)

    if world_mod and irl_model:
        planner = BossPlanner(
            world_model=world_mod,
            irl_model=irl_model,
            lookahead_depth=lookahead,
        )
        print(f"Planning mode: weight={planning_weight}, depth={lookahead}")
    else:
        planner = None
        print("World model or IRL model not found. Using policy only.")

    _run_inference_loop_with_planner(
        env, model, planner, planning_weight, deterministic
    )


def infer_maml(cfg: dict, player_id: str = "default",
               deterministic: bool = True):
    """
    MAML inference: loads meta-model, adapts to player in 2-3 gradient steps,
    runs adapted PyTorch policy directly (bypasses SB3).
    """
    import torch
    from maml_policy import MamlPolicy
    from maml_trainer import MAMLTrainer
    from replay_buffer_manager import ReplayBufferManager

    maml_cfg = cfg.get("maml", {})
    meta_model_dir = maml_cfg.get("meta_model_dir", "./models/maml")
    inner_steps = maml_cfg.get("inner_steps", 3)
    inner_lr = maml_cfg.get("inner_lr", 0.01)
    replay_dir = cfg.get("transfer", {}).get("replay_dir", "./replays")

    env = _make_env(cfg, player_id)
    obs_dim = env.OBS_SIZE

    # Load meta-model
    trainer = MAMLTrainer(
        obs_dim=obs_dim,
        num_actions=5,
        hidden_size=maml_cfg.get("policy_hidden_size", 64),
        replay_dir=replay_dir,
    )
    trainer.load_meta_model(meta_model_dir)
    print(f"Loaded MAML meta-model from {meta_model_dir}")

    # Adapt to this player
    adapted_policy = trainer.adapt_to_player(
        player_id, num_inner_steps=inner_steps, inner_lr=inner_lr
    )

    if adapted_policy is None:
        print(f"No replay data for '{player_id}'. Using unadapted meta-model.")
        adapted_policy = trainer.meta_policy

    adapted_policy.eval()
    print(f"Adapted with {inner_steps} gradient steps for player '{player_id}'")

    _run_inference_loop_maml(env, adapted_policy, deterministic)


def _run_inference_loop(env, model, deterministic: bool):
    """Generic inference loop for flat SB3 models."""
    action_names = ["Attack", "Block", "Dodge", "Approach", "Retreat"]

    print("Starting inference. Press Ctrl+C to stop.")
    print(f"Deterministic: {deterministic}")

    episode = 0
    try:
        while True:
            obs, info = env.reset()
            episode += 1
            total_reward = 0.0
            steps = 0
            done = False

            print(f"\n--- Episode {episode} ---")

            while not done:
                action, _ = model.predict(obs, deterministic=deterministic)
                action = int(action)

                obs, reward, terminated, truncated, info = env.step(action)
                total_reward += reward
                steps += 1
                done = terminated or truncated

                if steps % 50 == 0:
                    print(
                        f"  Step {steps}: {action_names[action]}, "
                        f"Boss HP: {info['boss_hp']:.1%}, "
                        f"Hero HP: {info['hero_hp']:.1%}, "
                        f"Reward: {reward:.2f}"
                    )

            print(
                f"Episode {episode} finished: {steps} steps, "
                f"Total reward: {total_reward:.2f}, "
                f"Boss HP: {info['boss_hp']:.1%}, "
                f"Hero HP: {info['hero_hp']:.1%}"
            )
    except KeyboardInterrupt:
        print(f"\nStopped after {episode} episodes.")
    finally:
        env.close()


def _run_inference_loop_with_planner(env, model, planner, planning_weight: float,
                                     deterministic: bool):
    """Inference loop that blends policy with world model planner."""
    action_names = ["Attack", "Block", "Dodge", "Approach", "Retreat"]

    print("Starting planning inference. Press Ctrl+C to stop.")
    plan_count = 0
    policy_count = 0

    episode = 0
    try:
        while True:
            obs, info = env.reset()
            episode += 1
            total_reward = 0.0
            steps = 0
            done = False

            print(f"\n--- Episode {episode} ---")

            while not done:
                use_planner = (
                    planner is not None
                    and np.random.random() < planning_weight
                )

                if use_planner:
                    base_obs = obs[:env.BASE_OBS_SIZE]
                    action = planner.plan(base_obs)
                    plan_count += 1
                    source = "PLAN"
                else:
                    action, _ = model.predict(obs, deterministic=deterministic)
                    action = int(action)
                    policy_count += 1
                    source = "PPO"

                obs, reward, terminated, truncated, info = env.step(action)
                total_reward += reward
                steps += 1
                done = terminated or truncated

                if steps % 50 == 0:
                    print(
                        f"  Step {steps}: {action_names[action]} [{source}], "
                        f"Boss HP: {info['boss_hp']:.1%}, "
                        f"Hero HP: {info['hero_hp']:.1%}, "
                        f"Reward: {reward:.2f}"
                    )

            total = plan_count + policy_count
            plan_pct = (plan_count / total * 100) if total else 0
            print(
                f"Episode {episode} finished: {steps} steps, "
                f"Total reward: {total_reward:.2f}, "
                f"Planner usage: {plan_pct:.0f}%"
            )
    except KeyboardInterrupt:
        print(f"\nStopped after {episode} episodes.")
    finally:
        env.close()


def _run_inference_loop_maml(env, policy, deterministic: bool):
    """Inference loop for raw PyTorch MAML policy (no SB3)."""
    import torch

    action_names = ["Attack", "Block", "Dodge", "Approach", "Retreat"]

    print("Starting MAML inference. Press Ctrl+C to stop.")
    print(f"Deterministic: {deterministic}")

    episode = 0
    try:
        while True:
            obs, info = env.reset()
            episode += 1
            total_reward = 0.0
            steps = 0
            done = False

            print(f"\n--- Episode {episode} ---")

            while not done:
                obs_tensor = torch.FloatTensor(obs).unsqueeze(0)
                with torch.no_grad():
                    action_logits, _ = policy(obs_tensor)

                if deterministic:
                    action = int(torch.argmax(action_logits, dim=-1).item())
                else:
                    probs = torch.softmax(action_logits, dim=-1)
                    action = int(torch.multinomial(probs, 1).item())

                obs, reward, terminated, truncated, info = env.step(action)
                total_reward += reward
                steps += 1
                done = terminated or truncated

                if steps % 50 == 0:
                    print(
                        f"  Step {steps}: {action_names[action]}, "
                        f"Boss HP: {info['boss_hp']:.1%}, "
                        f"Hero HP: {info['hero_hp']:.1%}, "
                        f"Reward: {reward:.2f}"
                    )

            print(
                f"Episode {episode} finished: {steps} steps, "
                f"Total reward: {total_reward:.2f}, "
                f"Boss HP: {info['boss_hp']:.1%}, "
                f"Hero HP: {info['hero_hp']:.1%}"
            )
    except KeyboardInterrupt:
        print(f"\nStopped after {episode} episodes.")
    finally:
        env.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run trained Boss RL model")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--model", type=str, default=None,
                        help="Model path (.zip or directory)")
    parser.add_argument("--stochastic", action="store_true",
                        help="Use stochastic actions")
    parser.add_argument("--hierarchical", action="store_true",
                        help="Use hierarchical agent")
    parser.add_argument("--player-id", type=str, default="default",
                        help="Player ID")
    parser.add_argument("--transfer", action="store_true",
                        help="Use transfer learning per-player model")
    parser.add_argument("--irl", action="store_true",
                        help="Use IRL-augmented observations")
    parser.add_argument("--planning", action="store_true",
                        help="Use world model planning")
    parser.add_argument("--maml", action="store_true",
                        help="Use MAML meta-learned model")
    args = parser.parse_args()

    cfg = load_config(args.config)
    deterministic = not args.stochastic

    if args.maml:
        infer_maml(cfg, player_id=args.player_id, deterministic=deterministic)
    elif args.planning:
        model_path = args.model or cfg["inference"]["model_path"]
        infer_planning(cfg, model_path, player_id=args.player_id,
                       deterministic=deterministic)
    elif args.irl:
        model_path = args.model or cfg["inference"]["model_path"]
        infer_irl(cfg, model_path, player_id=args.player_id,
                  deterministic=deterministic)
    elif args.hierarchical:
        model_dir = args.model or cfg.get("hierarchical", {}).get(
            "model_dir", "./checkpoints/hierarchical")
        infer_hierarchical(cfg, model_dir, deterministic,
                           player_id=args.player_id)
    elif args.transfer:
        infer_transfer(cfg, args.player_id, deterministic)
    else:
        model_path = args.model or cfg["inference"]["model_path"]
        infer_flat(cfg, model_path, deterministic, player_id=args.player_id)
