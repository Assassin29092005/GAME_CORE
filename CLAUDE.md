# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Prerequisites

- Unreal Engine 5.8 (source or launcher)
- Git LFS — `.uasset`, `.umap`, `.uexp` files are stored via LFS. Run `git lfs install` before cloning.
- Python 3.10+ for RL training/inference

## Build & Run

Unreal Engine 5.8 C++ project. Module: `GAME_CORE`. Solution: `GAME_CORE.sln` (UBT also emits `GAME_CORE.slnx` and an `Automation_GAME_CORE.sln`/`.slnx` pair; the plain `GAME_CORE.sln` is the one to open, but per the caveat below don't build from any of them — use `Build.bat`).

**Build (preferred — UE Build.bat directly):**
```
"C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat" GAME_COREEditor Win64 Development -Project="D:\GAME_CORE 5.8\GAME_CORE.uproject" -WaitMutex
```
This is the reliable path. Visual Studio / Rider solution build is broken on this machine (see caveat below).

**Build caveats:**
- Close the UE editor before a full rebuild — a running editor locks `GAME_CORE.dll`.
- Live Coding / Hot Reload does NOT pick up new `UPROPERTY` or `UFUNCTION` declarations reliably. Any change to reflected metadata (new BP-callable functions, new `EditAnywhere` properties, new delegates) needs a full rebuild with the editor closed.
- **VS2026 MSBuild SetEnv bug**: Building from the `GAME_CORE.sln` solution under Visual Studio 2026 fails with an environment-variable-too-long error — only metadata projects compile, the actual module silently doesn't, and the editor loads stale code. Always use `Build.bat` directly (above) instead of solution build / Live Coding from VS until this is fixed upstream.

**Python RL setup and training (requires UE editor running with the level open):**

A virtualenv with all dependencies already exists at `Python/venv` — use `Python\venv\Scripts\python.exe` (or activate it) instead of installing into the global interpreter.
```
cd Python
pip install -r requirements.txt        # only for a fresh venv — includes sb3-contrib
                                       # (required: config.yaml defaults training.algorithm
                                       # to MaskablePPO) and onnx (required by export_onnx.py);
                                       # onnxruntime optional for the ORT agreement check
python train.py                        # training (MaskablePPO by default; training.algorithm: PPO for flat)
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

**Unreal MCP bridge (`.mcp.json`):** the repo registers an `unreal-mcp` HTTP MCP server at `http://127.0.0.1:8000/mcp`. Its tools are only reachable when the UE editor is running with the matching MCP plugin/endpoint listening — it lets tooling drive the editor directly. If those tools are absent or connection-refused, the editor (or the endpoint) isn't up; this is separate from the RL bridge on TCP 5555.

## Testing

The RL stack has an automated harness (no editor needed): `cd Python; venv\Scripts\python.exe smoke_test.py` runs the full training loop against a mock UE bridge (`Python/tests/mock_ue_server.py`) in ~3 s, and `Python/tests/` holds the pytest suite (boss_env, rl_algo, wrappers, replay schema). In-game feel/combat testing remains manual: UE editor with the level open + `infer.py`/`train.py`, verified in-game and via TensorBoard.

**Training-bridge gotcha (the "empty TensorBoard" trap):** TWO independent causes kept `tb_logs/PPO_*` at 88 bytes (header only) on every run. (1) **Flush interval** — SB3 PPO only writes scalars to the event file every `log_interval` *rollouts*; the original `config.yaml` `log_interval: 10` × `n_steps=2048` meant the first flush needed ~20k steps (~22+ min). Lowered to `1` so it flushes every rollout (~2.3 min). (2) **Survival** — the trainer must stay alive that long, but the 10s socket timeout (below) crash-looped it. Both had to be fixed; either one alone still yields an empty dashboard. The original `BossEnv` socket `timeout` was 10s — far too tight: UE shader compilation (first run) and game-thread hitches routinely stall an observation past 10s, so `env.step()`/`reset()` raised `socket.timeout`, the trainer crashed, and `run_training.ps1` relaunched it into a still-busy UE (`ConnectionRefused`) — a crash-loop that never logged anything (symptom: every `tb_logs/PPO_*` dir is exactly 88 bytes = header only). Fixed: `env.timeout` now defaults to 60s (config-driven via `config.yaml` `env.timeout`, passed through `train.py`), and `run_training.ps1 -StartupGraceSeconds` defaults to 90. **Pre-warm shaders once** (run the `-game` instance and let it settle) so the DDC is populated before an unattended run. Diagnose bridge health from the UE log (`Saved/Logs/GAME_CORE.log`, timestamps are **UTC**) — look for `RLBridge: Client connection established` followed by sustained combat, not reconnects every ~10s.

## Architecture

A combat game where BP_NeuralHero (player) fights BP_Boss (RL-driven). C++ gameplay components live in `Source/GAME_CORE/`. Python RL scripts live in `Python/`. Communication is via TCP on port 5555 with newline-delimited JSON.

### RL Loop

1. C++ `StateObservationComponent` collects `FRLObservation` (17-dim: hero velocity, combo, attacking, HP, distance, angle, boss HP, 8-dim player profile) → JSON
2. C++ `RLBridgeComponent` sends JSON over TCP at ~15 Hz
3. Python `BossEnv` (gymnasium.Env) receives obs, returns `{"action": 0-4}`
4. C++ `BossActionComponent` executes: 0=Attack, 1=Block, 2=Dodge, 3=Approach, 4=Retreat. The boss has a single `DodgeMontage` slot — no roll variant; the simpler single-evade design covers RL training without a second action.

### Component Layout

```
BP_Boss: CombatComponent, StateObservationComponent, RLBridgeComponent,
         BossActionComponent, HitReactionComponent, HitFeedbackComponent,
         PlayerMemoryComponent, BossExplainabilityComponent,
         EmotionEstimationComponent

BP_NeuralHero: CombatComponent, CombatStateComponent, PlayerProfileComponent,
               HitReactionComponent, HitFeedbackComponent, AutoHeroComponent,
               LockOnComponent
```

`AutoHeroComponent` is the M1 sparring bot — disabled by default; activated by the `-AutoHero=<persona>` launch arg from `Tools/run_training.ps1` (personas: `rusher`, `turtle`, `kiter`, `counter`, `chaotic`). It drives only the public `CombatComponent` API plus Enhanced Input injection (see the Mover gotcha below); training-only behavior, never reached in shipped play.

```
ANPCMinionCharacter (C++, M3 patrol minions): CombatComponent, HitReactionComponent,
         HitFeedbackComponent — ACharacter-based ON PURPOSE (not Mover) so stock
         AIController/BT MoveTo pathing works; CombatComponent supports ACharacter owners.
```

Components find each other at runtime via `FindComponentByClass` (no hard references). `StateObservationComponent` looks up `CombatComponent` on both actors, `PlayerProfileComponent` on the hero, `PlayerMemoryComponent` and `EmotionEstimationComponent` on the boss.

### Mover Plugin Gotchas

BP_NeuralHero and BP_Boss are **APawn-based Mover pawns, not `ACharacter`**. Several patterns across the codebase exist specifically to work around this:

- **Mesh lookup**: `CombatComponent::GetOwnerAnimInstance()` tries `ACharacter::GetMesh()` first, then falls back to `FindComponentByClass<USkeletalMeshComponent>()`. Use this pattern (or `FindComponentByClass` directly) in any new component — never assume `Cast<ACharacter>` succeeds.
- **Input vector**: Mover consumes input through its own buffer (`IMoverInputProducerInterface`), not `APawn::AddMovementInput`. `GetLastMovementInputVector()` / `GetPendingMovementInputVector()` return zero on Mover pawns. `CombatComponent::SetMovementInput(FVector2D)` is the supported hook — the pawn BP calls it from `IA_Move Triggered`, and it transforms the value into world-space using the controller's yaw.
- **`APawn::AddMovementInput` does NOTHING on either Mover pawn** (hero OR boss) — both consume input through Mover's own pipeline, not the standard `ControlInputVector`. The hero must inject through `UEnhancedInputLocalPlayerSubsystem::InjectInputForAction(MoveAction, FInputActionValue(Vec2D), ...)` (`AutoHeroComponent::InjectMove` is the reference). The **boss** has no controller/Enhanced-Input mapping, so `BossActionComponent` drives movement (approach/retreat AND dodge) with **`AddActorWorldOffset(sweep=true)` per tick** and facing with `SetActorRotation`. **Both are "external movement" to Mover**, which by default (`bAcceptExternalMovement=0`) logs an out-of-band warning and *reconciles them away from its sim state next frame* — the boss then visibly never turns to face the hero and travels at ~half speed with jitter. **The fix is `BossActionComponent::BeginPlay` setting `UMoverComponent::bAcceptExternalMovement = true` (and `bWarnOnExternalMovement = false`)** so Mover ingests the per-tick transform changes into its authoritative sim state. Without that flag, neither the boss offset nor its rotation sticks. (The hero's `AddActorWorldOffset` dodge works without the flag only because `CombatComponent` ticks pre-physics; `BossActionComponent` ticks `TG_PostPhysics` for facing, after Mover commits the frame.) Don't reintroduce `AddMovementInput` for Mover pawns.
- **Velocity lag**: `GetVelocity()` lags input by a frame or two because velocity is integrated by Mover *after* input is consumed. Code sampling velocity at "the instant of input" (e.g., attack-time combo selection) should prefer BP-pushed input over sampled velocity.
- **Root motion**: Montages with root-motion flags drive Mover-integrated movement — the motion-warp target must be up to date before `Montage_Play`, which `PlayComboMontage` handles.

### Combat System

`CombatAnimConfig` (UDataAsset) defines combo chains of `FAttackAnimData`. `CombatComponent` manages:

- **Directional combos**: `NeutralComboConfig` / `ForwardComboConfig` / `BackwardComboConfig` / `SideComboConfig`, selected at each chain-start by `SelectComboByDirection()`. Priority: `LastMovementInput` (pushed from the pawn BP via `SetMovementInput` on `IA_Move`) → owner velocity → neutral. The BP hook is required because Mover pawns don't populate `APawn::GetLastMovementInputVector()` (see Mover gotchas above).
- **Input buffering** within a configurable combo window (`CombatConfig->ComboWindowDuration`). Chain ENDS after `ComboLength` steps — there is no wrap-around. To support multi-hit combos, add multiple `FAttackAnimData` entries to the relevant config's `ComboChain` array; otherwise a single-entry config gives one swing per press.
- **Attack cooldown** (`AttackCooldownDuration`) blocks `RequestAttack` after a combo ends, is interrupted, or runs out of configured steps.
- **Per-swing hit guard**: `bHitLandedThisAttack` on the attacker's `CombatComponent`. `UAnimNotifyState` instance variables proved unreliable in UE5, so `ANS_DealDamage` reads/writes this flag on the attacker rather than its own member. The guard is cleared at TRUE swing starts only: `PlayComboMontage` (hero combos) and `BossActionComponent::DoAttack` (boss attacks, which bypass `PlayComboMontage`). **It is deliberately NOT cleared in `ANS_DealDamage::NotifyBegin`** — `HitFeedbackComponent::PauseAttackerAnim` pauses/resumes the attacker's montage on every landed hit, which re-fires `NotifyBegin` mid-swing. Clearing the guard there used to turn one swing into ~25 hits (the M0 one-click-kill bug). If you ever add a new attack-start code path, you must clear the guard there explicitly.
- **Hit-stop + NotifyBegin**: as a corollary, never gate behavior on "NotifyBegin = new swing." Use it for setup that's safe to repeat (debug logs, trace cache init) but never for state that must fire once per swing.
- **Death / round reset**: `ApplyDamage` sets `bIsDead` and broadcasts `OnHealthDepleted`. BPs bind this to play the death montage (boss uses `BossActionComponent::HandleDeath` + `OnBossDied`) and trigger `ResetForNewRound()` + respawn after a delay (the inter-round pause is a BP `Delay` node before `ResetForNewRound`). `CombatComponent::PostResetInvulnerabilityDuration` (default 3s, BP-tunable) blocks damage briefly after reset so in-flight combo hits from the round-ending swing don't immediately re-kill and trigger the death montage twice. `BossActionComponent::ResetForNewRound` also calls `HitReactionComponent::ResetForNewRound` to clear accumulated stagger and the grace timer.
- **Respawn positioning**: `CombatComponent` captures its owner's transform at `BeginPlay` and `ResetForNewRound` teleports back to it, then `StopAllMontages` so the actor leaves its death pose. Toggle with `bRestoreSpawnTransformOnReset` (default true). No BP "move to spawn point" wiring is needed — both hero and boss reset position automatically because both carry a `CombatComponent`. **Mover gotcha**: a plain `SetActorTransform`/`SetActorLocation` does NOT stick on a Mover pawn — Mover holds the authoritative position in its sim state and snaps the actor back the next tick (this is why the first attempt visibly failed). The teleport routes through `UMoverComponent::QueueInstantMovementEffect(FTeleportEffect)` when a `UMoverComponent` is present, falling back to `SetActorTransform(TeleportPhysics)` only for non-Mover actors. Requires the `Mover` module in `GAME_CORE.Build.cs`.
- **Auto round reset (training)**: when `bAutoResetRoundOnDeath` is set, a fighter's death calls `ScheduleRoundReset()` → fires `TriggerRoundReset()` after `RoundResetDelay` (default 2.5s). `TriggerRoundReset` iterates every actor in the world and calls `ResetForNewRound` on its `CombatComponent`, `BossActionComponent`, and (for non-boss combatants) `HitReactionComponent` — so **either** death resets **both** fighters to spawn + full HP for a fresh round, with no cross-Blueprint wiring. All `ResetForNewRound` variants are idempotent. Tick the flag on both hero and boss CombatComponents. Leave it false for shipped play (boss-death = victory, handled in BP). Scheduled from BOTH `CombatComponent::ApplyDamage` (HP→0) and `BossActionComponent::HandleDeath` (insurance; self-gated, harmless redundancy). **Gotcha:** `ResetForNewRound` deliberately does NOT clear `RoundResetTimerHandle` — legacy BP death wiring that resets only the boss would otherwise cancel the pending full-arena reset and the hero would never move (the symptom that motivated this).
- **Death montages**: hero death is animated by `CombatComponent::DeathMontage` (played in `ApplyDamage` when HP→0). The boss leaves that slot EMPTY and animates via `BossActionComponent::HandleDeath` + its own `DeathMontage` — assigning both would double-play on the boss. `ResetForNewRound` calls `StopAllMontages` so the death pose clears on respawn.
- **No-op hit suppression**: `ANS_DealDamage` skips `PlayHitReaction` AND `TriggerHitFeedback` when the target `IsInvulnerable()` (post-reset grace) or `IsDead()` — sampled before `ApplyDamage`. Without this, a hit landing during the 3s post-reset window plays a flinch while HP never moves (the "hit reaction but no damage" confusion). A hit that takes the target to 0 still reacts, because the dead-check is sampled pre-damage.
- **Boss target acquisition**: `BossActionComponent::BeginPlay` auto-assigns `TargetActor = GetPlayerPawn(0)` if BP left it null, so the boss faces/chases the hero without a BP "SetupBossAI" step. Facing uses `RInterpTo` on the owner's rotation at `TG_PostPhysics` with `TeleportPhysics` (so Mover's velocity-driven facing doesn't overwrite it each frame).
- **Hit-reaction lockout**: `HitReactionComponent::IsReacting()` returns true while a flinch montage is playing AND for `HitReactionGracePeriod` seconds (default 0.25s) after it ends. `BossActionComponent::ExecuteActionEnum` checks this before firing any RL action, so the boss can't dodge / attack mid-combo in the gap between montage end and the next bridge action (~67ms cadence).
- **Montage mutation caveat**: `PlayComboMontage`, `RequestDodge`, and `HitReactionComponent::PlayHitReaction` all mutate the shared montage asset (`BlendIn`/`BlendOut` times, root-motion flags) before play. Safe ONLY if each combo step / dodge direction / intensity-direction pair uses a UNIQUE montage asset — sharing a montage across entries OR across characters (hero + boss) causes interleaved writes. Always Ctrl+D to duplicate before assigning a hero montage to the boss or vice versa.

### Player Defensive Combat (Dodge / Block)

`CombatComponent` also owns the player-side defensive moves. All hold/play state lives here; the bot uses these same entry points so behavior matches a human player exactly. Roll was considered as a slower second-tier evade but cut — dodge alone covers the design without doubling the surface area.

- **Dodge** (`RequestDodge`): single backstep. One slot (`DodgeMontage`), always plays backward along -ActorForward regardless of WASD — the souls-like default. Near-instant (`DodgeBlendInTime` default 0.05s). Displacement is **code-driven, not animation-driven**: the montage plays for visuals with root motion OFF, and `TickComponent` pushes the actor via `AddActorWorldOffset(sweep=true)` for `DodgeDistance` cm over `DodgeDuration` s (defaults 350cm / 0.35s). This sidesteps Mover's root-motion plumbing and motion-warping setup — the actor moves a guaranteed distance even if the source anim has zero authored translation. Hook IA_Dodge → Started → RequestDodge. i-frames are implemented via `ANS_Invulnerable` (separate `bDodgeInvulnerable` flag — never reuses `bIsInvulnerable`), placed at 10–60% of the dodge by `Tools/place_feel_notifies.py` (see Game-Feel Layer).
- **Block** (`SetBlocking(bool)`): hold-state. `SetBlocking(true)` plays `BlockStartMontage`, then `OnBlockMontageEnded` chains into `BlockIdleMontage` repeatedly (delegate-driven loop, NOT a montage section loop, NOT notify-driven — the M0 hit-stop lesson generalizes). `SetBlocking(false)` plays `BlockEndMontage`. On a frontal hit while blocking, `ApplyDamage` branches on the attack's `FAttackAnimData::DamageType` (passed through from `ANS_DealDamage`): **Light** → reduce damage by `BlockDamageMultiplier` (default 0.25) and play `BlockHitMontage`; **Heavy** → play `BlockBreakMontage`, drop `bIsBlocking`, and let **full damage** through. The flinch is **always suppressed** on blocked hits (`ANS_DealDamage` samples `IsBlockingAgainst(attacker)` BEFORE `ApplyDamage` runs, so the break-montage isn't double-stacked with a flinch).
- **AnimGraph requirement for block-while-walking**: block montages must play in an upper-body-only slot (project convention: `UpperBody.Block`) layered over the locomotion state machine via `Layered blend per bone` at the spine. If block montages stay in `DefaultGroup.DefaultSlot`, they override the legs and the hero slides when walking with block held. The fix is BP-side: create the slot in the Skeleton's Anim Slot Manager, reassign every block montage to it, then insert a Layered Blend Per Bone node before Output Pose with Branch Filter `spine_01` / Blend Depth 4.
- **State gates**: `RequestAttack` and `RequestDodge` both refuse while `bIsDodging` is true. `SetBlocking(true)` refuses while attacking/dodging/dead. Cancel windows are implemented via `ANS_CancelWindow` (guide.md Phase 3.2): attacks cancel into buffered dodge/block inside the window; outside it everything commits fully (see Game-Feel Layer).
- **Damage instigator**: `ApplyDamage(DamageAmount, AActor* Instigator = nullptr)`. The instigator enables both the block check above and caches `LastHitDirection` (world-space, 2D, BlueprintReadOnly) for knockback/ragdoll impulses when guide.md Phase 6.2/6.3 lands. Always pass the attacker; `ANS_DealDamage::NotifyTick` already does.
- **Boss block damage reduction**: `BossActionComponent::DoBlock` calls `SetBlocking(true)` on the boss's `CombatComponent` so block isn't visual-only; `OnActionMontageEnded` releases it when `BlockMontage` finishes. The boss's RL "Block" action is a momentary defensive window, not a permanent stance.

### Game-Feel Layer (guide.md implementation — M2)

- **`UGameFeelSettings`** (UDeveloperSettings → Project Settings → Game → Game Feel; persisted in `Config/DefaultGame.ini`) owns all cross-cutting feel numbers: camera (FOV/arm/lag/lock-on), telegraph colors (red unblockable `#FF2A1A` / yellow parryable `#FFC400`), boss-bar chip timing, plus `bEnableBossStatusHUD` / `bEnableCombatCamera` / `bApplyCameraDefaults` toggles. Tune here, never rebuild.
- **`UGameFeelSubsystem`** (world subsystem) **auto-injects** `UCombatCameraComponent` onto the player pawn and `UBossStatusHUDComponent` onto the boss (actor with `BossActionComponent` — never minions) at world start. No BP component adding needed; kill via the settings toggles.
- **Boss execution layer** (`BossActionComponent`): `ExecuteActionEnum` gate order is fixed — dead → commitment → recovery lockout → reacting → hysteresis → mask → dispatch. Includes: per-action min durations, `MovementFlipVotes`/`DirectionCommitmentSeconds` hysteresis, C++ action mask (Attack→Approach substitute; `GetLegalActionMask()` also ships a `"mask"` array in the obs JSON, consumed Python-side by MaskablePPO — sb3-contrib 2.9.0, default via config.yaml `training.algorithm`; `rl_algo.py` sniffs legacy plain-PPO checkpoints and loads them unmasked), windup slow-in 0.6× (0.45× when `WasRecentlyRendered` false) restored by `AN_RestoreRate`, `AttackRecoveryDuration` lockout, and the **fallback scripted brain** (watchdog: 1.5 s when disconnected, 45 s when connected-but-silent — SB3's `learn()` gradient pauses must NOT trigger it). `OnBossTelegraph(bIsHeavyUnblockable, WindupSeconds)` broadcasts at every attack start — the HUD's unblockable indicator listens.
- **Player feel** (`CombatComponent`): single-slot buffered-action queue (`ECombatActionType`, latest-press-wins, `BufferedActionExpiry` 0.3 s) replaces `bInputBuffered`; `ANS_CancelWindow` / `ANS_Invulnerable` (separate `bDodgeInvulnerable` — never reuse `bIsInvulnerable`) / `ANS_HyperArmor` all keep state on the owner component (ANS_DealDamage pattern). **Parry**: block press within `ParryWindow` (0.15 s) of a frontal hit = zero damage + attacker forced Heavy stagger (`DamageType "Parry"` maps to Heavy in `DetermineStaggerIntensity` and pierces hyper-armor, without polluting `CurrentStagger`). `BossActionComponent::BeginPlay` forces `bParryEnabled=false` on the boss — RL Block stays chip-block only. `FAttackAnimData` gained per-attack `HitStopDuration`/`CameraShakeScale`/`KnockbackImpulse`; `UCS_HitLight`/`UCS_HitHeavy` are code-built shake fallbacks when `HitCameraShake` is unset.
- **Boss status HUD** is pure Slate (`SBossStatusWidget`, no UMG assets): top-center HP bar with GoW-style damage chip, poise bar, hit-confirm flash, and the red/yellow telegraph indicator projected at the boss.
- **Debug**: `combat.DebugHUD 1` — boss commitment/lockout lines (keys 101-102) + player buffer/cancel/i-frame lines (111-113).
- **`Tools/place_feel_notifies.py`** — batch-places ANS_CancelWindow / ANS_Invulnerable / ANS_HyperArmor / AN_RestoreRate windows on the montages (idempotent; run headless via `-ExecutePythonScript` or editor `py`).

### Ship Path (M5/M6 layer)

- **`UNNEBossPolicyComponent`** (auto-injected on the boss via `UGameFeelSubsystem` when `UGameFeelSettings::bEnableNNEBoss`): in-engine ONNX inference (NNERuntimeORTCpu) at 15 Hz — mirrors `StateObservationComponent`'s exact 17-dim obs, applies `GetLegalActionMask()` to the logits, argmax → `ExecuteAction`. **Arbitration: `-rlbridge` or a live TCP client always outranks NNE** (training never fights the shipped brain; `run_training.ps1` passes `-rlbridge -NoTelemetry`). Model wiring: `GameFeelSettings::NNEBossModelData` (currently the untrained `NNM_BossUntrained` — replace with a real checkpoint via `Python/make_test_onnx.py`-style export + `Tools/import_onnx_model.py`). Archetype bank: `TMap<FName, UNNEModelData>` + cosine profile match. Self-test: `boss.NNESelfTest` console command.
- **M6 subsystems**: `UFirebaseAuthSubsystem` (identitytoolkit REST, tokens in `Saved/Auth/`, guest mode, Slate `SLoginScreen`; unconfigured keys ⇒ guest-only + loud log), `UTelemetryUploadSubsystem` (one JSON per round to `Saved/Telemetry/pending/`, offline-first; uploads profile + emotion + `BossExplainabilityComponent` insights/taunts per the **Website/README.md schema — the contract**; atomically increments `meta/global` via Firestore fieldTransforms — no Cloud Functions, free tier), `UCommunityDifficultySubsystem` (GET meta/global → `GetGlobalDifficultyScalar()`).
- **Combat audio hooks** (guide 7.1): `HitFeedbackComponent::ImpactSound/HeavyImpactSound`, `CombatComponent::ParrySound`, `BossActionComponent::TelegraphSound` (+2D fallback when unrendered); whoosh `PlaySound` notifies on attack montages. Placeholder CC0 picks in `/Game/Arena/Audio` (wired by `Tools/import_combat_audio.py`).
- **Vendored packs are gitignored** (23 GB, re-addable from the Fab library) — `/Game/Arena/**` and `Retargeted_Animations/**` reference them, so fresh clones must re-add the packs before those assets resolve.

### NPC Minions (M3 layer)

BT-driven patrols whose only secret job is feeding the boss's dossier (`PlayerProfileComponent` on the hero updates vs any opponent; `PlayerMemoryComponent` carries it into the arena). C++: `ANPCMinionCharacter` (ACharacter; tags itself `Enemy` so lock-on works; forces `bAutoResetRoundOnDeath=false`; death = StopLogic + no-collision + `SetLifeSpan(CorpseLifetime)`), `AMinionAIController` (runs `BehaviorTreeAsset`; BB keys as `static const FName`s: `TargetActor`, `DistanceToTarget`, `bCanAct`, `bTargetDead`, `HomeLocation`, `PatrolLocation`), `UBTService_MinionCombatState` (0.2s; also cycles `PatrolPoints`→`PatrolLocation` so stock MoveTo patrols), `UBTTask_MinionAttack` (routes through `CombatComponent::RequestAttack` ONLY — hit-guard safety), `UBTDecorator_MinionCanAct` (live component check, not stale BB), `AMinionEncounterSpawner` (ring-spawn, nav-projected). Build.cs gained AIModule/NavigationSystem/GameplayTasks.

**Faction rules (cross-cutting changes to be aware of):** the `Enemy` actor tag IS the faction. `ANS_DealDamage` now sweeps `SweepMultiByChannel`, ignores same-faction pawns, and only lands hits on hostile targets with a `CombatComponent` — minion↔minion and minion↔boss friendly fire is impossible by construction. Minion corpses remove their `Enemy` tag and (deferred one tick) destroy their combat components, so tag/component scans never find dead combatants; `LockOnComponent` also drops dead targets pre-hysteresis. `TriggerRoundReset` skips any actor with `GetLifeSpan() > 0` (corpse pending despawn) — don't "fix" that skip, it prevents round resets reviving ghost minions.

**Minion BP setup requirement:** each minion BP needs its OWN duplicated montages + its own `CombatAnimConfig` (montage mutation caveat above — never share montage assets with hero/boss/other minion types).

### Player Lock-On (`LockOnComponent`)

Soft auto-lock on BP_NeuralHero. On tick it finds the nearest actor tagged `EnemyTag` (default `"Enemy"`) within `LockOnRange` (800cm), then `RInterpTo`-rotates the owning pawn's **controller yaw** (`YawInterpRate` 8.0, pitch untouched) to face it; it drops the target past the wider `DisengageRange` (1100cm) hysteresis band so the lock doesn't flicker at the boundary. Because WASD is already controller-yaw-relative (see the Mover input notes), turning the camera to the enemy makes strafe-keys orbit it for free — no separate strafe code. **Setup is BP-side**: add the `Enemy` tag to BP_Boss (and any future NPC enemy) under Class Defaults → Actor → Tags, or nothing locks on. Mover-safe: reads only the PlayerController and writes `ControlRotation`, no `ACharacter` assumption. Query state via `IsLockedOn()` / `GetLockedTarget()`.

Motion warping positions the attacker via `UMotionWarpingComponent`; `UpdateMotionWarpTarget` sets the warp target's location/rotation toward `WarpTargetActor` at each attack start. Hit feedback uses **per-actor `CustomTimeDilation`** for hit stop (not global time dilation) so the RL bridge timer is unaffected; attacker anim is paused via `Montage_Pause`/`Montage_Resume`.

### Enhanced Input setup (Pressed trigger + Started pin)

One-shot combat intents (Attack, Dodge) MUST be configured both ways or they double-fire:
- **On the `IA_*` asset**: Triggers array must contain a single `Pressed` trigger. With no trigger entry, Enhanced Input fires `Started` every frame the key is held, not once per press.
- **In the BP**: wire the action's `Started` execution pin (NOT `Triggered`). `Triggered` fires repeatedly while held even with a Pressed trigger.

Hold intents (Block, Move) are the opposite — leave Triggers empty so the default Down behavior gives `Started` on press and `Completed` on release, and wire both pins. We burned a long debug session (the "one click = full combo" symptom) before settling this — it's an easy way to lose hours.

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
| Core | `boss_env.py`, `train.py`, `infer.py`, `config.yaml`, `rl_algo.py` (algorithm resolve / checkpoint sniffing / ActionMasker), `requirements.txt` |
| Tests | `smoke_test.py` (end-to-end vs mock bridge), `tests/` (mock_ue_server.py + pytest suite) |
| Hierarchical RL | `hierarchical_env.py`, `hierarchical_policy.py`, `train_hierarchical.py` |
| Constrained Learning | `constrained_wrapper.py` |
| Transfer Learning | `transfer_learning.py`, `train_transfer.py`, `replay_buffer_manager.py`, `replay_recorder.py` |
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
- Core RL uses Stable Baselines3 2.9 — MaskablePPO (sb3-contrib) by default, flat PPO selectable via `training.algorithm`; `rl_algo.py` resolves the class and auto-detects legacy checkpoints. MAML uses raw PyTorch
- `BossEnv` observation space is dynamic (17-29 dims). Action space: `Discrete(5)`
- Reward is phase-based: aggressive when boss HP > 50%, reactive when <= 50%
- World model and MAML use PyTorch directly (not SB3)
- `infer.py` supports multiple modes via flags: `--hierarchical`, `--transfer`, `--irl`, `--planning`, `--maml`

## Project Planning Docs

- `ROADMAP.md` — **the master plan**: ordered milestones M0–M8 from current state to release (bug fixes → training automation → feel → NPCs → visuals → ONNX/NNE boss → Firebase sync → website → packaging), with done-criteria. Start here when deciding what to work on; update milestone status at session end.
- `guide.md` — gameplay-feel manual (9 phases, click-level editor steps).
- `visuals.md` — rendering/lighting/art/Blender-terrain manual, budgeted for the dev laptop (RTX 4050 6 GB / 16 GB RAM).
- `Website/` — the player dashboard ("Subject Dossier": Firebase auth, profile radar, emotion timeline, fight log, download page). React + Vite; builds clean; demo mode works without Firebase. Setup + the **canonical Firestore schema** (the contract the game's uploader must write) live in `Website/README.md`.
- `Tools/run_training.ps1` — unattended overnight training supervisor (UE standalone + train.py, crash-restart). Passes the persona to both sides: `-AutoHero=<persona>` to UE, `--player-id <persona>` to `train.py`, so replays land in `replays/<persona>/`.
- `Tools/set_combo_damage.py` — editor Python script that batch-sets `DamageAmount`/`DamageType` on every entry of every `CombatAnimConfig` asset (10/15/20/25 with Heavy on the chain finisher). Run via Tools → Execute Python Script… or `py "D:\GAME_CORE 5.8\Tools\set_combo_damage.py"` from the **Cmd** console (not Python — that's a common misfire).
- `Tools/build_arena_level.py` — re-runnable headless level builder (imports SourceArt FBXs with Nanite, builds M_Terrain, assembles /Game/Maps/BossArena incl. lighting/blocking/nav/minion bootstrap). Run via `-ExecutePythonScript` — the `-run=pythonscript` commandlet crashes on level ops.
- `Tools/batch_retarget_anims.py` — IK-Retargeter batch retarget for Fab anim packs → mannequin (and later mannequin → MetaHuman); edit the constants block at the top, run from the editor Cmd console.
- `Tools/place_feel_notifies.py` — batch-places the guide.md notify windows (cancel/i-frames/hyper-armor/rate-restore) on montages; idempotent; force-saves and verifies on-disk mtimes.
- `Python/replay_recorder.py` — gymnasium wrapper that calls `ReplayBufferManager.start_episode/record_step/end_episode` during live training. The write API existed before but nothing called it; `train.py` now wraps `BossEnv` with this when `transfer.record_replays` is on (default: true), so overnight runs actually produce the `replays/<player_id>/episode_NNNN.npz` files that MAML / IRL / world-model / transfer training read.
- `Python/train.py --player-id <name>` — CLI override for `env.player_id` so the harness can key replays per persona without editing config.yaml.
- `Python/export_onnx.py` — SB3 checkpoint → ONNX for in-engine NNE inference, with agreement verification.

## Architecture Diagrams

PlantUML diagrams in `Docs/` (rendered `.png` exports sit alongside each `.puml`):
- `system_architecture.puml` — full system (all components, structs, extensions)
- `uml_ue_perspective.puml` — Unreal Engine / C++ focus
- `uml_python_perspective.puml` — Python RL pipeline focus
- `uml_player_perspective.puml` — player-facing view
- `simple_*.puml` — simplified versions of the above plus SRS deliverables (use case, activity, class, system overview) for coursework documentation

`Docs/` also contains a Node.js toolchain (`create_presentation.js`, `create_report.js`, `node_modules/`) used to generate the project `.pptx`/`.docx` deliverables. Exclude `Docs/node_modules` when searching the repo — it pollutes Glob/Grep results. `Python/venv` and `Website/node_modules` likewise.
