# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Prerequisites

- Unreal Engine 5.7 (source or launcher)
- Git LFS — `.uasset`, `.umap`, `.uexp` files are stored via LFS. Run `git lfs install` before cloning.
- Python 3.10+ for RL training/inference

## Build & Run

Unreal Engine 5.7 C++ project. Module: `GAME_CORE`. Solution: `GAME_CORE.sln`.

**Build (Developer Command Prompt or shell with UE in PATH):**
```
UnrealBuildTool GAME_CORE Win64 Development "D:\GAME_CORE\GAME_CORE.uproject"
```
Or build via Visual Studio / Rider from the solution file.

**Build caveats:**
- Close the UE editor before a full rebuild — a running editor locks `GAME_CORE.dll`.
- Live Coding / Hot Reload does NOT pick up new `UPROPERTY` or `UFUNCTION` declarations reliably. Any change to reflected metadata (new BP-callable functions, new `EditAnywhere` properties, new delegates) needs a full rebuild with the editor closed.

**Python RL setup and training (requires UE editor running with the level open):**
```
cd Python
pip install gymnasium stable-baselines3 pyyaml tensorboard torch numpy
python train.py                        # flat PPO training
python train_hierarchical.py           # 3-phase hierarchical training
python train_transfer.py train_base    # transfer learning base model
python train_world_model.py train      # world model on replay data
python train_maml.py meta_train        # MAML meta-training (5000 iterations)
python infer.py                        # standard inference
python infer.py --hierarchical         # hierarchical inference
python infer.py --irl --planning       # IRL + world model planning
python infer.py --maml --player-id X   # MAML-adapted inference
tensorboard --logdir tb_logs
```

All Python config is in `Python/config.yaml`. Each extension has an `enabled: true/false` toggle.

## Testing

No automated test suite. Testing is manual: run the UE editor with the level open, then launch the appropriate Python script (`infer.py` or `train.py`). Verify behavior in-game and via TensorBoard metrics.

## Architecture

A combat game where BP_NeuralHero (player) fights BP_Boss (RL-driven). C++ gameplay components live in `Source/GAME_CORE/`. Python RL scripts live in `Python/`. Communication is via TCP on port 5555 with newline-delimited JSON.

### RL Loop

1. C++ `StateObservationComponent` collects `FRLObservation` (17-dim: hero velocity, combo, attacking, HP, distance, angle, boss HP, 8-dim player profile) → JSON
2. C++ `RLBridgeComponent` sends JSON over TCP at ~15 Hz
3. Python `BossEnv` (gymnasium.Env) receives obs, returns `{"action": 0-4}`
4. C++ `BossActionComponent` executes: 0=Attack, 1=Block, 2=Dodge, 3=Approach, 4=Retreat

### Component Layout

```
BP_Boss: CombatComponent, StateObservationComponent, RLBridgeComponent,
         BossActionComponent, HitReactionComponent, HitFeedbackComponent,
         PlayerMemoryComponent, BossExplainabilityComponent,
         EmotionEstimationComponent

BP_NeuralHero: CombatComponent, CombatStateComponent, PlayerProfileComponent,
               HitReactionComponent, HitFeedbackComponent
```

Components find each other at runtime via `FindComponentByClass` (no hard references). `StateObservationComponent` looks up `CombatComponent` on both actors, `PlayerProfileComponent` on the hero, `PlayerMemoryComponent` and `EmotionEstimationComponent` on the boss.

### Mover Plugin Gotchas

BP_NeuralHero and BP_Boss are **APawn-based Mover pawns, not `ACharacter`**. Several patterns across the codebase exist specifically to work around this:

- **Mesh lookup**: `CombatComponent::GetOwnerAnimInstance()` tries `ACharacter::GetMesh()` first, then falls back to `FindComponentByClass<USkeletalMeshComponent>()`. Use this pattern (or `FindComponentByClass` directly) in any new component — never assume `Cast<ACharacter>` succeeds.
- **Input vector**: Mover consumes input through its own buffer (`IMoverInputProducerInterface`), not `APawn::AddMovementInput`. `GetLastMovementInputVector()` / `GetPendingMovementInputVector()` return zero on Mover pawns. `CombatComponent::SetMovementInput(FVector2D)` is the supported hook — the pawn BP calls it from `IA_Move Triggered`, and it transforms the value into world-space using the controller's yaw.
- **Velocity lag**: `GetVelocity()` lags input by a frame or two because velocity is integrated by Mover *after* input is consumed. Code sampling velocity at "the instant of input" (e.g., attack-time combo selection) should prefer BP-pushed input over sampled velocity.
- **Root motion**: Montages with root-motion flags drive Mover-integrated movement — the motion-warp target must be up to date before `Montage_Play`, which `PlayComboMontage` handles.

### Combat System

`CombatAnimConfig` (UDataAsset) defines combo chains of `FAttackAnimData`. `CombatComponent` manages:

- **Directional combos**: `NeutralComboConfig` / `ForwardComboConfig` / `BackwardComboConfig` / `SideComboConfig`, selected at each chain-start by `SelectComboByDirection()`. Priority: `LastMovementInput` (pushed from the pawn BP via `SetMovementInput` on `IA_Move`) → owner velocity → neutral. The BP hook is required because Mover pawns don't populate `APawn::GetLastMovementInputVector()` (see Mover gotchas above).
- **Input buffering** within a configurable combo window (`CombatConfig->ComboWindowDuration`).
- **Attack cooldown** (`AttackCooldownDuration`) blocks `RequestAttack` after a combo ends or is interrupted.
- **Per-swing hit guard**: `bHitLandedThisAttack` on the attacker's `CombatComponent`. `UAnimNotifyState` instance variables proved unreliable in UE5, so `ANS_DealDamage` reads/writes this flag on the attacker rather than its own member. `MarkHitLanded()` sets it; `PlayComboMontage` clears it per swing.
- **Death / round reset**: `ApplyDamage` sets `bIsDead` and broadcasts `OnHealthDepleted`. BPs bind this to play the death montage (boss uses `BossActionComponent::HandleDeath` + `OnBossDied`) and trigger `ResetForNewRound()` + respawn after a delay.
- **Montage mutation caveat**: `PlayComboMontage` and `HitReactionComponent::PlayHitReaction` mutate the shared montage asset (`BlendIn`/`BlendOut` times, root-motion flags) before play. Safe ONLY if each combo step / intensity-direction pair uses a UNIQUE montage asset — sharing a montage across entries causes interleaved writes.

Motion warping positions the attacker via `UMotionWarpingComponent`; `UpdateMotionWarpTarget` sets the warp target's location/rotation toward `WarpTargetActor` at each attack start. Hit feedback uses **per-actor `CustomTimeDilation`** for hit stop (not global time dilation) so the RL bridge timer is unaffected; attacker anim is paused via `Montage_Pause`/`Montage_Resume`.

### Observation Pipeline

Base observation is always 17 dims. Extensions add dimensions Python-side by parsing extra JSON fields:

| Config Flag | Extra Dims | Source |
|---|---|---|
| `irl.enabled` | +5 (player action probs) | `MaxEntIRL.predict_action_distribution()` |
| `emotion.enabled` | +3 (frustration/flow/boredom) | C++ `EmotionEstimationComponent` via JSON `"emotion"` field |
| hierarchical wrapper | +4 (strategy one-hot) | `HierarchicalBossEnv` |

`BossEnv.__init__` computes `_obs_size` dynamically from config flags. Index offsets (`_irl_start`, `_emotion_start`) track where each augmentation begins.

### Extension Architecture (9 extensions total)

Extensions are loosely coupled. Each can be toggled independently in `config.yaml`:

- **Player Profiling** (always on): 8-dim EMA profile computed by C++ `PlayerProfileComponent`
- **Cross-Encounter Memory**: `PlayerMemoryComponent` with per-dimension decay to prevent all-knowing boss
- **Hierarchical RL** (`hierarchical`): `StrategistEnv` (Discrete(4) strategies) + `HierarchicalBossEnv` (Discrete(5) tactics). 3-phase training
- **Constrained Learning** (`constraints`): `ConstrainedBossEnv` wrapper — win-rate cap via dynamic incompetence epsilon + engagement rewards
- **Transfer Learning** (`transfer`): `TransferLearningManager` — base model + per-player fine-tuning via `ReplayBufferManager`
- **IRL Player Modeling** (`irl`): `MaxEntIRL` (MaxEnt IRL, Ziebart 2008) recovers player reward function, predicts P(action|state)
- **World Model & Planning** (`world_model`): `WorldModel` (MLP dynamics) + `BossPlanner` (1-2 step lookahead using IRL predictions)
- **Emotion-Aware AI** (`emotion`): C++ `EmotionEstimationComponent` estimates frustration/flow/boredom from behavioral signals. Python-side: `ConstrainedBossEnv` modulates epsilon, `strategy_reward` adjusts strategy preferences
- **MAML Meta-Learning** (`maml`): `MamlPolicy` with differentiable inner adaptation (`create_graph=True`). `MAMLTrainer` meta-trains on multi-player data. Adapts to new players in 2-3 gradient steps

### Python Files by Extension

| Extension | Files |
|---|---|
| Core | `boss_env.py`, `train.py`, `infer.py`, `config.yaml` |
| Hierarchical RL | `hierarchical_env.py`, `hierarchical_policy.py`, `train_hierarchical.py` |
| Constrained Learning | `constrained_wrapper.py` |
| Transfer Learning | `transfer_learning.py`, `train_transfer.py`, `replay_buffer_manager.py` |
| IRL | `irl_player_model.py`, `irl_feature_engineering.py` |
| World Model | `world_model.py`, `planning.py`, `train_world_model.py` |
| MAML | `maml_policy.py`, `maml_trainer.py`, `train_maml.py`, `maml_data_utils.py` |
| Shared | `strategy_reward.py` (emotion-based strategy preference modulation) |

### Key Data Flow Between Extensions

```
ReplayBufferManager ──→ MaxEntIRL (trajectories for IRL training)
                    ──→ WorldModelTrainer (supervised dynamics training)
                    ──→ MAMLTrainer (support/query task splits)

MaxEntIRL ──→ BossEnv (augments obs with P(a|s))
          ──→ BossPlanner (predicts player responses)

WorldModel ──→ BossPlanner (predicts next state + reward)

EmotionEstimationComponent ──→ StateObservationComponent (JSON field)
                           ──→ ConstrainedBossEnv (epsilon modulation)
                           ──→ strategy_reward (strategy preferences)
                           ──→ BossExplainabilityComponent (emotion-aware taunts)
```

### Replay Data Format

`ReplayBufferManager` stores episodes as `.npz` files under `replays/{player_id}/episode_NNNN.npz` containing arrays: `obs`, `actions`, `rewards`, `next_obs`, `dones`, and optionally `player_actions`.

## C++ Conventions

Follow Unreal Engine naming (enforced via `.editorconfig`):
- Classes: `U` prefix (UObject), `A` prefix (AActor), `S` prefix (SWidget)
- Structs: `F` prefix, enums: `E` prefix, templates: `T` prefix
- Booleans: `b` prefix (e.g., `bIsAttacking`)
- All PascalCase

Module dependencies in `GAME_CORE.Build.cs`: Core, CoreUObject, Engine, InputCore, EnhancedInput, MotionWarping, Sockets, Networking, Json, JsonUtilities

Enabled plugins (in `.uproject`): Mover (+ MoverExamples, MoverIntegrations), MotionWarping, MotionTrajectory, PoseSearch, AnimationWarping, AnimationLocomotionLibrary, Chooser, LiveLinkControlRig

## Python Conventions

- All config in `Python/config.yaml` with per-extension sections
- Core RL uses Stable Baselines3 (PPO). MAML uses raw PyTorch
- `BossEnv` observation space is dynamic (17-29 dims). Action space: `Discrete(5)`
- Reward is phase-based: aggressive when boss HP > 50%, reactive when <= 50%
- World model and MAML use PyTorch directly (not SB3)
- `infer.py` supports multiple modes via flags: `--hierarchical`, `--transfer`, `--irl`, `--planning`, `--maml`

## Architecture Diagrams

PlantUML diagrams in `Docs/`:
- `system_architecture.puml` — full system (all components, structs, extensions)
- `uml_ue_perspective.puml` — Unreal Engine / C++ focus
- `uml_python_perspective.puml` — Python RL pipeline focus
- `uml_player_perspective.puml` — player-facing view
