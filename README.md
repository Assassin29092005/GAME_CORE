# GAME_CORE

> An Unreal Engine 5.7 combat game featuring a **fully adaptive, RL-driven boss AI** — a boss that learns how you fight, remembers you across encounters, and evolves its strategy to counter yours.

---

## Overview

GAME_CORE is a C++ / Python hybrid project built in Unreal Engine 5.7. The player (`BP_NeuralHero`) fights a boss (`BP_Boss`) whose behavior is driven by a live Python reinforcement learning agent. The boss doesn't just scale difficulty — it genuinely learns your playstyle, models your intentions, and plans ahead.

The architecture combines **7 pluggable AI extensions**: hierarchical strategy selection, inverse reinforcement learning, world-model planning, MAML meta-learning, transfer learning per player, emotion-aware constraints, and cross-encounter memory — each independently toggleable from a single config file.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Unreal Engine | 5.7 (source or launcher) |
| Python | 3.10+ |
| Git LFS | Required for `.uasset`, `.umap`, `.uexp` |

```bash
git lfs install   # before cloning
```

---

## Build & Run

### Unreal Engine (C++)

Build via Visual Studio / Rider using `GAME_CORE.sln`, or from the command line:

```bash
UnrealBuildTool GAME_CORE Win64 Development "D:\GAME_CORE\GAME_CORE.uproject"
```

### Python RL Agent

Install dependencies:

```bash
cd Python
pip install gymnasium stable-baselines3 pyyaml tensorboard torch numpy
```

Run training or inference (requires UE editor open with the level loaded):

```bash
# Training
python train.py                         # Flat PPO training
python train_hierarchical.py            # 3-phase hierarchical training
python train_transfer.py train_base     # Transfer learning — base model
python train_world_model.py train       # World model on replay data
python train_maml.py meta_train         # MAML meta-training (5000 iterations)

# Inference
python infer.py                         # Standard
python infer.py --hierarchical          # Hierarchical strategy
python infer.py --irl --planning        # IRL + world model planning
python infer.py --maml --player-id X    # MAML-adapted to player X

# Monitoring
tensorboard --logdir tb_logs
```

All configuration lives in `Python/config.yaml`. Every extension has an `enabled: true/false` toggle.

---

## Architecture

Communication between UE and Python runs over **TCP port 5555** using newline-delimited JSON at ~15 Hz.

```
UE C++ (StateObservationComponent)
    → JSON observation (17+ dims)
    → TCP port 5555
Python BossEnv (gymnasium.Env)
    → action: {"action": 0-4}
    → back over TCP
UE C++ (BossActionComponent)
    → executes: Attack / Block / Dodge / Approach / Retreat
```

### Component Layout

**BP_Boss:**
`CombatComponent` · `StateObservationComponent` · `RLBridgeComponent` · `BossActionComponent` · `HitReactionComponent` · `HitFeedbackComponent` · `PlayerMemoryComponent` · `BossExplainabilityComponent` · `EmotionEstimationComponent`

**BP_NeuralHero:**
`CombatComponent` · `CombatStateComponent` · `PlayerProfileComponent` · `HitReactionComponent` · `HitFeedbackComponent`

Components resolve each other at runtime via `FindComponentByClass` — no hard references.

### Observation Pipeline

Base observation is always **17 dimensions** (hero velocity, combo state, attacking flag, HP, distance, angle, boss HP, 8-dim player profile). Extensions augment this Python-side:

| Config Flag | Extra Dims | Source |
|---|---|---|
| `irl.enabled` | +5 | `MaxEntIRL.predict_action_distribution()` |
| `emotion.enabled` | +3 | `EmotionEstimationComponent` via JSON `"emotion"` field |
| `hierarchical` wrapper | +4 | `HierarchicalBossEnv` strategy one-hot |

`BossEnv.__init__` computes `_obs_size` dynamically. Index offsets (`_irl_start`, `_emotion_start`) track each augmentation.

### Reward Structure

- **Boss HP > 50%** → aggressive phase reward
- **Boss HP ≤ 50%** → reactive/defensive phase reward

---

## Extensions (7 total)

All extensions are loosely coupled and independently toggled in `config.yaml`.

### 1. Player Profiling *(always on)*
8-dimensional EMA behavioral profile computed by `PlayerProfileComponent` in C++. Tracks how you fight and embeds that into every observation the boss receives.

### 2. Cross-Encounter Memory
`PlayerMemoryComponent` persists knowledge about a player between sessions, with per-dimension decay so the boss doesn't become omniscient — just experienced.

### 3. Hierarchical RL
Two-level hierarchy: a **Strategist** (`Discrete(4)` strategies) and a **Tactician** (`Discrete(5)` tactics). Trained in 3 phases. Lets the boss make high-level decisions (e.g., "apply pressure") before choosing specific moves.

### 4. Constrained Learning
`ConstrainedBossEnv` caps the boss win rate via dynamic incompetence epsilon and adds engagement rewards. Keeps the game fun without dumbing the AI down permanently.

### 5. Transfer Learning
`TransferLearningManager` trains a shared base model, then fine-tunes per player using `ReplayBufferManager`. The boss has a personal model for each player it has fought.

### 6. IRL Player Modeling
`MaxEntIRL` (Ziebart 2008) recovers the player's implicit reward function from observed trajectories and predicts the probability distribution over their next action. Used to augment boss observations and feed the planner.

### 7. World Model & Planning
`WorldModel` (MLP dynamics) predicts next state + reward. `BossPlanner` uses 1-2 step lookahead, combining world model rollouts with IRL action predictions to select actions that are good not just now but also in response to what the player is likely to do next.

### 8. Emotion-Aware AI
`EmotionEstimationComponent` estimates **frustration / flow / boredom** from behavioral signals in C++. On the Python side, this modulates the win-rate cap (epsilon) and adjusts strategy preferences — so the boss backs off when you're frustrated and ramps up when you're bored.

### 9. MAML Meta-Learning
`MamlPolicy` with differentiable inner adaptation (`create_graph=True`). `MAMLTrainer` meta-trains across multi-player data so the boss can adapt to a brand-new player in **2–3 gradient steps** at inference time.

---

## Data Flow Between Extensions

```
ReplayBufferManager ──→ MaxEntIRL          (trajectories for IRL training)
                    ──→ WorldModelTrainer   (supervised dynamics training)
                    ──→ MAMLTrainer         (support/query task splits)

MaxEntIRL ──→ BossEnv      (augments obs with P(a|s))
          ──→ BossPlanner   (predicts player responses)

WorldModel ──→ BossPlanner  (predicts next state + reward)

EmotionEstimationComponent ──→ StateObservationComponent  (JSON field)
                           ──→ ConstrainedBossEnv          (epsilon modulation)
                           ──→ strategy_reward             (strategy preferences)
                           ──→ BossExplainabilityComponent (emotion-aware taunts)
```

---

## Python Files by Extension

| Extension | Files |
|---|---|
| Core | `boss_env.py`, `train.py`, `infer.py`, `config.yaml` |
| Hierarchical RL | `hierarchical_env.py`, `hierarchical_policy.py`, `train_hierarchical.py` |
| Constrained Learning | `constrained_wrapper.py` |
| Transfer Learning | `transfer_learning.py`, `train_transfer.py`, `replay_buffer_manager.py` |
| IRL | `irl_player_model.py`, `irl_feature_engineering.py` |
| World Model | `world_model.py`, `planning.py`, `train_world_model.py` |
| MAML | `maml_policy.py`, `maml_trainer.py`, `train_maml.py`, `maml_data_utils.py` |
| Shared | `strategy_reward.py` |

---

## Replay Data Format

Episodes are stored as `.npz` files under `replays/{player_id}/episode_NNNN.npz`:

| Array | Description |
|---|---|
| `obs` | Observations |
| `actions` | Boss actions taken |
| `rewards` | Reward signal |
| `next_obs` | Next-state observations |
| `dones` | Episode termination flags |
| `player_actions` | *(optional)* Player actions for IRL |

---

## Architecture Diagrams

PlantUML source files in `Docs/`:

| File | Focus |
|---|---|
| `system_architecture.puml` | Full system — all components, structs, extensions |
| `uml_ue_perspective.puml` | Unreal Engine / C++ focus |
| `uml_python_perspective.puml` | Python RL pipeline focus |
| `uml_player_perspective.puml` | Player-facing view |

---

## C++ Conventions

Follows standard Unreal Engine naming (enforced via `.editorconfig`):

| Entity | Prefix | Example |
|---|---|---|
| UObject subclass | `U` | `UCombatComponent` |
| AActor subclass | `A` | `ABossCharacter` |
| Struct | `F` | `FRLObservation` |
| Enum | `E` | `EBossPhase` |
| Template | `T` | `TArray<...>` |
| Boolean | `b` | `bIsAttacking` |

All identifiers use PascalCase.

**Module dependencies** (`GAME_CORE.Build.cs`): `Core`, `CoreUObject`, `Engine`, `InputCore`, `EnhancedInput`, `MotionWarping`, `Sockets`, `Networking`, `Json`, `JsonUtilities`

**Enabled plugins**: Mover, MotionWarping, MotionTrajectory, PoseSearch, AnimationWarping, AnimationLocomotionLibrary, Chooser, LiveLinkControlRig

---

## Python Conventions

- All config in `Python/config.yaml` with per-extension sections
- Core RL uses **Stable Baselines3** (PPO). MAML uses raw **PyTorch**
- `BossEnv` observation space: **17–29 dims** (dynamic). Action space: `Discrete(5)`
- World model and MAML bypass SB3 entirely and use PyTorch directly
- `infer.py` supports runtime mode flags: `--hierarchical`, `--transfer`, `--irl`, `--planning`, `--maml`

---

## Testing

There is no automated test suite. Testing is manual:

1. Open the UE editor with the level loaded
2. Launch the appropriate Python script (`infer.py` or `train.py`)
3. Observe behavior in-game
4. Monitor training metrics via TensorBoard (`tensorboard --logdir tb_logs`)
