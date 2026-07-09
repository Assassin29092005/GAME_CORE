# paper.md — Research Brief for GAME_CORE

> **Purpose of this document.** This is a self-contained brief written so that another
> research-focused AI (or a human co-author) can draft a journal or conference paper
> from it without needing to read the source tree. It captures the problem, the
> contributions, the system, the methods, the experimental protocol, the results
> we already have, and the figures/screenshots we can supply. Where a claim depends
> on a code path, the file:line reference is included so it can be verified.
>
> Deep architectural detail is in `CLAUDE.md`. Ordered milestone status is in
> `ROADMAP.md`. Ship-readiness ledger is in `NEXTSTEP.md`. Website + Firestore
> schema is in `Website/README.md`. This file assumes all four are also available.

---

## 1. Working title candidates

Pick one when framing the paper — each frames a different contribution as primary.

1. **"Player-Adaptive Boss AI at Ship Scale: Behavioral Profiling, Cross-Encounter
   Memory, and Archetype-Matched ONNX Policies in a Real-Time Combat Game."**
   (Systems + deployment framing. Best fit for CoG / AIIDE / TOG.)
2. **"Persona-Diverse Reinforcement Learning with Measured Behavior Centroids
   for Player-Matched Opponent Selection."**
   (Method framing. Best fit for TCIAIG / TOG.)
3. **"An Emotion-Aware, Modular RL Architecture for Combat Boss AI: Nine
   Composable Extensions on a Shared Observation Space."**
   (Architecture framing. Best fit for CoG or a systems venue.)
4. **"From Trainer to Runtime: Zero-Python Deployment of Player-Adaptive RL
   Bosses via ONNX and a Community-Scale Difficulty Loop."**
   (Deployment / engineering-research framing. Best fit for GDC/CoG industry
   track or a games-engineering journal.)

## 2. One-paragraph abstract (seed)

> Boss opponents in commercial action games either follow hand-authored behavior
> trees (predictable, cheap) or use reinforcement learning in restricted training
> settings that never reach players. We present GAME_CORE, a real-time third-person
> combat game in which a reinforcement-learning boss is trained against
> persona-scripted sparring bots (rusher, turtle, kiter, counter, chaotic),
> exported to ONNX, and deployed inside Unreal Engine 5.8 via the NNE runtime
> at 15 Hz with a strict shipping-vs-training arbitration path. At runtime the
> boss selects one of several archetype-specialised policies by matching the
> player's cross-encounter behavior profile (an 8-dimensional EMA vector) against
> measured centroids using mean-centered cosine similarity. Nine composable
> extensions — behavioral profiling, decaying cross-encounter memory,
> hierarchical strategy/tactics, constrained learning for engagement, transfer
> learning, maximum-entropy inverse RL for player modelling, a world model with
> short-horizon planning, an emotion estimator, and MAML meta-learning — share
> a single dynamic observation space (17–29 dims) and can be toggled independently.
> A player-facing dashboard (Firebase-backed) closes the loop with a behavior radar,
> emotion timeline, fight log, contextual taunts, and a "one mind, many encounters"
> community aggregate. We report training curves, offline archetype evaluation results,
> integration/latency measurements, and a system-level description that we
> believe is the first end-to-end account of shipping player-adaptive RL boss
> AI into a real UE5 title with a live analytics loop.

Refine numbers and framing before submission.

## 3. Problem statement

Combat action games — Dark Souls, Sekiro, God of War, Bloodborne, Elden Ring —
build reputation on *boss encounters*. In practice these bosses are behavior
trees or state machines authored by designers. This has three well-known
weaknesses.

1. **Predictability.** Once the pattern is learned, replay value collapses.
2. **Non-adaptivity.** A rusher and a turtle player see the same fight; the
   boss cannot exploit either style.
3. **Content cost.** Every new archetype is designer time.

Reinforcement learning offers an alternative, but the literature and industry
practice diverges on two axes:

- **Where the policy lives at ship time.** Most academic RL work either runs
  the trainer in the loop (unshippable) or exports a policy but stops short of
  wiring it into an engine, an input pipeline, arbitration with a human-facing
  build, and a cook step. We commit end-to-end.
- **How the policy responds to individual players.** Player modelling and
  IRL exist as isolated papers; hierarchical RL, MAML, and world models exist
  as isolated papers; commercial "dynamic difficulty" is usually a scalar
  scaling of enemy HP/damage. Very few systems compose modelling → memory →
  policy selection → observable in-engine behavior → analytic dashboard as
  one closed loop.

**Research question.** Can a real-time combat game ship a player-adaptive RL
boss whose behavior is *individually* shaped by the player's behavioral
history, using techniques from the RL/player-modelling literature, on
consumer hardware, without a Python runtime dependency on the player's machine?

**Our answer.** Yes; this paper documents the architecture, the training
protocol, and the trade-offs.

## 4. Contributions

Each contribution is stated as a defensible claim tied to a code artifact.

1. **An end-to-end pipeline** from persona-scripted sparring, through
   MaskablePPO training against a TCP-bridged Unreal client, through ONNX
   export with agreement verification, through headless import to a UE
   `UNNEModelData` asset, through eval-gated promotion, to in-engine inference
   at 15 Hz using the NNE runtime with a `-rlbridge`-outranks-NNE arbitration
   rule so the training loop never fights the shipped brain.
   *Files:* `Python/train.py`, `Python/export_onnx.py`, `Python/eval_archetypes.py`,
   `Tools/import_onnx_model.py`, `Source/GAME_CORE/Private/NNEBossPolicyComponent.cpp`,
   `Source/GAME_CORE/Private/GameFeelSubsystem.cpp`.

2. **Persona-diverse training via scripted opponents.** Five scripted personas
   (`rusher`, `turtle`, `kiter`, `counter`, `chaotic`) drive `AutoHeroComponent`
   during training. Replays are keyed per-persona, and each persona is trained
   in a separate run so the resulting checkpoints specialise for different
   play styles. The measurement pipeline (`Python/measure_centroids.py`)
   turns those replays into 8-dimensional behavior centroids consumed by
   the runtime selector. Centroids are re-measurable after every new batch
   of overnight runs — the paper reports the current set (see §9).

3. **Behavioral EMA profiling** with a designer-tunable time constant. The
   8-dim `FPlayerProfile` (`AggressionScore`, `DodgeTendency`, `BlockTendency`,
   `OpenerAggression`, `PressureResponse`, `KitingScore`,
   `ComboCompletionRate`, `PositionalVariance`) is updated by
   `PlayerProfileComponent` from combat events (`ANS_DealDamage`,
   `RequestDodge`/`SetBlocking`, movement input, combo commit) and appended
   to the RL observation. This gives the policy access to who is playing.

4. **Cross-encounter memory with per-dimension decay.**
   `PlayerMemoryComponent` persists the profile between rounds/sessions
   with `decay_encounter_threshold`, `decay_rate`, and
   `active_threshold` parameters (config.yaml `memory:`), so the boss is
   never omniscient after one round and never forgets who you are after
   twenty. Persistence is Firebase-UID-keyed when logged in and `guest`
   when not (`GameFeelSubsystem::BeginPlay`).

5. **Archetype-matched policy selection via mean-centered cosine similarity,
   fired per encounter.** At each encounter start (a player-triggered event
   in the streamed open world — an `ABossEncounterVolume` overlap in Tier 4
   of this codebase; a single-arena world-load in earlier milestones),
   `UNNEBossPolicyComponent` matches the stored player profile against
   per-persona measured centroids in a settings-driven archetype bank
   (`Config/DefaultGame.ini` `+NNEArchetypeBank`). Mean-centering at 0.5
   (the neutral profile value) is the key methodological detail: raw cosine
   on all-positive profiles saturates near 1 and barely discriminates. A
   BP-authored `ArchetypeProfiles` asset overrides the ini bank when present.
   The encounter-triggered form multiplies the match evidence per session
   (multiple biomes → multiple resolutions against a profile the previous
   encounter just mutated). The lifecycle (LoadMemory before injection;
   RecordEncounterEnd + SaveMemory on round end, debounced; skipped under
   `-rlbridge`) is owned by `GameFeelSubsystem` — without this, the bank is
   dead code in shipped play. When the cosine match has no signal (new /
   guest player, zero encounters), the encounter volume's declared
   `PreferredPersonaFallback` (a biome-level intent — e.g., "desert biome
   prefers rusher") wins over the settings-driven global default.

6. **MaskablePPO with a C++-authored legal-action mask travelling in the
   observation JSON.** `BossActionComponent::GetLegalActionMask` computes a
   5-bit mask (Attack/Block/Dodge/Approach/Retreat) accounting for
   cooldowns, distance, HP, block/dodge state; the observation ships it as
   `"mask"`. Python resolves the algorithm via `Python/rl_algo.py`
   (default MaskablePPO from sb3-contrib 2.9.0, falls back to plain PPO on
   legacy checkpoints via signature sniff). The mask restriction rate is
   logged as a TensorBoard scalar.

7. **Nine composable extensions on a single dynamic observation space.**
   Behavioral profiling, cross-encounter memory, hierarchical RL,
   constrained-learning-for-engagement, transfer learning,
   maximum-entropy IRL, MLP world model + short-horizon planning,
   emotion estimator, MAML. Each has an `enabled` flag in
   `Python/config.yaml`; the observation size (17–29 dims) is computed
   dynamically from active flags with index offsets tracked
   (`_irl_start`, `_emotion_start`). This modularity is itself a
   contribution — an ablation lattice by design.

8. **Emotion-aware constrained RL.** `EmotionEstimationComponent`
   estimates `frustration`, `flow`, `boredom` from behavioral signals and
   ships them as an observation field. `ConstrainedBossEnv` modulates
   the incompetence epsilon by these emotions; `strategy_reward` modulates
   the hierarchical strategist's preference; `BossExplainabilityComponent`
   uses them to select contextual taunts. The system is win-rate
   *targeted*, not win-rate-maximising: default target is 0.45.

9. **In-game "why did the boss do that" explainability + player-facing
   dashboard.** `BossExplainabilityComponent` surfaces a short human-readable
   reason for each executed action; `TelemetryUploadSubsystem` writes it
   into per-round JSON that the Firestore-backed dashboard renders as a
   taunt panel alongside the profile radar, emotion timeline, and fight log.
   The community `meta/global` document aggregates statistics across all
   uploads for a "one mind, many encounters" world-page counter — the
   pitch: one policy space (bank + resolver) fights every player, and its
   picks are logged.

10. **A shipping arbitration policy that keeps training and deployment
    honest.** A live TCP RL client on port 5555, or a `-rlbridge` launch
    argument, unconditionally outranks the shipped NNE brain
    (`GameFeelSubsystem::ShouldInjectNNEBoss` returns false when either is
    present). Overnight training also passes `-NoTelemetry` so bot rounds
    never pollute the community dossier. This is small but essential — it
    lets the *same build* be the training target and the shipped title.

## 5. Related work

Frame the paper by grouping the literature into four buckets and positioning
against each.

### 5.1 Combat/fighting-game RL benchmarks

FightingICE (Yoshida & Thawonmas), StreetFighterAI in academic contexts,
DeepMind's StarCraft II work, OpenAI Five for Dota, and the various
Pommerman/MicroRTS studies. **Differentiator:** these are research
environments; the environment *is* the platform. Our contribution is
end-to-end shipping into a UE5 combat game, with the artist-authored
combat feel (guide.md phases 0–8) intact.

### 5.2 Player modelling and dynamic difficulty

Yannakakis & Togelius (survey), FORZA Drivatar, Left 4 Dead's AI Director,
Alien Isolation's Xenomorph AI. **Differentiator:** those systems either
model the population (Drivatar aggregates over all players; Director scales
scalars) or rely on scripted behavior; ours composes measured behavioral
EMA + decayed cross-encounter memory + selection over trained RL
policies. The archetype bank + measured centroids + centered-cosine
matching is the specific mechanism we advocate.

### 5.3 Techniques

- **MaskablePPO / action masking:** the sb3-contrib line; our contribution
  is bridging the mask across a language/process boundary (C++ computes,
  JSON transports, Python enforces).
- **Maximum-entropy IRL:** Ziebart 2008; our contribution is using it not
  to imitate but to *predict* the player's next-action distribution as
  input to a short-horizon world-model planner.
- **MAML:** Finn 2017; our contribution is the framing — new player = new
  task, adapted in 2–3 gradient steps on their own replay.
- **World models for planning:** Ha & Schmidhuber, PlaNet-line work; ours
  is intentionally shallow (MLP dynamics) because the horizon is 1–2 steps
  and inference must remain real-time.

### 5.4 Explainability + player-facing analytics

Little precedent inside game AI research: most XAI work is generic ML.
Ours is domain-specific — "why did the boss dodge that combo?" surfaced as
short text at the moment it happens, and again in the dashboard.

## 6. System architecture

### 6.1 Training-time loop

```
┌───────────────────────────────────────────────────────────────┐
│  Unreal Engine 5.8 editor / standalone (-game -rlbridge)      │
│                                                               │
│   BP_NeuralHero  ← AutoHeroComponent (persona: rusher/turtle) │
│                    injects Enhanced Input via Move action      │
│                                                               │
│   BP_Boss       → StateObservationComponent (17-dim + mask)   │
│                   RLBridgeComponent (TCP JSON, port 5555)     │
│                   BossActionComponent (exec 0-4)              │
└───────────────────────────────────────────────────────────────┘
                              │
                     JSON, newline-delimited
                              │
┌───────────────────────────────────────────────────────────────┐
│  Python trainer                                               │
│                                                               │
│   BossEnv (gymnasium)  ─→ ActionMasker (rl_algo) ─→ Maskable  │
│                                                       PPO     │
│   ReplayRecorder wraps env → replays/<persona>/*.npz          │
│   TensorBoard scalars flushed every rollout                   │
└───────────────────────────────────────────────────────────────┘
```

`Tools/run_training.ps1` supervises unattended overnight runs (launches
UE `-game -AutoHero=<persona> -rlbridge -NoTelemetry`, waits for the
shader-compile grace period, launches `train.py --player-id <persona>`,
restarts on crash).

### 6.2 Ship-time loop

```
┌───────────────────────────────────────────────────────────────┐
│  Unreal Engine 5.8 packaged game                              │
│                                                               │
│  GameFeelSubsystem (world subsystem, on-start):               │
│     1. LoadMemory  ← Firebase UID (or "guest")                │
│     2. If NOT -rlbridge and no live TCP client:               │
│        Inject UNNEBossPolicyComponent on the boss             │
│        → resolves archetype: cosine-match player profile      │
│           to centroid → picks ONNX brain from bank            │
│        → NNE runtime (NNERuntimeORTCpu) infers at 15 Hz       │
│  On round end:                                                │
│     RecordEncounterEnd + SaveMemory, debounced 2s             │
│     TelemetryUploadSubsystem writes JSON to                   │
│       Saved/Telemetry/pending/, uploads to Firestore          │
└───────────────────────────────────────────────────────────────┘
                                     │
                       (offline-first, atomic increments)
                                     │
┌───────────────────────────────────────────────────────────────┐
│  Firestore + Website (Vite/React dashboard)                   │
│                                                               │
│    users/{uid}/rounds/{roundId}   ← per-round JSON            │
│    users/{uid}/profile            ← latest 8-dim + emotion    │
│    meta/global                    ← aggregate, One-Boss stats │
│                                                               │
│    Pages: Login, Dashboard (radar, timeline, fight log,       │
│           taunt panel), World (community), Download           │
└───────────────────────────────────────────────────────────────┘
```

### 6.3 Component map (concise)

- **`StateObservationComponent`** — assembles the 17-dim base obs; queries
  `CombatComponent` on hero and boss, `PlayerProfileComponent` on hero,
  `PlayerMemoryComponent` and `EmotionEstimationComponent` on boss;
  appends `mask` from `BossActionComponent`.
- **`RLBridgeComponent`** — TCP JSON at ~15 Hz; connection watchdogs
  (1.5 s disconnected, 45 s connected-but-silent) chosen to survive
  MaskablePPO's checkpoint pauses without letting a truly dead trainer
  strand the boss.
- **`BossActionComponent`** — action dispatch with a fixed gate order:
  *dead → commitment → recovery lockout → reacting → hysteresis → mask →
  dispatch*. Facing on `TG_PostPhysics` (Mover reconciliation).
- **`NNEBossPolicyComponent`** — in-engine ONNX inference at 15 Hz;
  argmax over masked logits; mirrors `StateObservationComponent`'s exact
  17-dim obs; obeys the `-rlbridge`/live-TCP arbitration rule.
- **`PlayerProfileComponent`** / **`PlayerMemoryComponent`** — behavioral
  EMA + persistence with decay.
- **`EmotionEstimationComponent`** — three-dim frustration/flow/boredom
  estimate.
- **`BossExplainabilityComponent`** — reason string per action.
- **`GameFeelSubsystem`** — auto-injects CameraComponent, HUD, NNE brain,
  and owns the memory lifecycle.
- **`TelemetryUploadSubsystem`** — round JSON to Firestore, offline-first,
  atomic aggregate increments via `fieldTransforms`.
- **`FirebaseAuthSubsystem`** / **`CommunityDifficultySubsystem`** —
  authentication and global-difficulty scalar.

## 7. Methods, extension by extension

Each extension has a config section in `Python/config.yaml` and a canonical
file set (see CLAUDE.md "Python Files by Extension"). Summarise per module:

### 7.1 Behavioral profiling
8-dim EMA (see §4 point 3). Update rules live in `PlayerProfileComponent`.
The paper should state the exact update formula per dimension and the
time constants (they are BP-tunable UPROPERTYs).

### 7.2 Cross-encounter memory
Per-dimension decay parametrised by `decay_encounter_threshold` (default 5),
`decay_rate` (0.15), `active_threshold` (0.15). Persistence keyed by
Firebase UID (or `guest`).

### 7.3 Hierarchical RL
Strategist (Discrete(4): rush / attrition / hit-and-run / counter) chosen
every `strategy_interval=30` steps; tactician (Discrete(5), same as the
flat action space) executes. Three-phase training: tactician pretrain
200k, strategist train 100k, joint finetune 200k.

### 7.4 Constrained learning for engagement
`ConstrainedBossEnv` wraps the base env. Introduces a dynamic
incompetence epsilon that grows when the rolling win rate exceeds
`target_win_rate` (default 0.45) and shrinks below it. Adds a
`close_fight_bonus` and `lead_change_bonus`. Emotion signals (see §7.8)
modulate the epsilon further — high frustration relaxes the boss.

### 7.5 Transfer learning
`TransferLearningManager` fine-tunes a base checkpoint on per-player
replays via `ReplayBufferManager`. Enables archetype-conditioned or
per-user tuning without full retraining.

### 7.6 IRL player modelling
`MaxEntIRL` recovers a linear reward function over hand-designed player
features (`irl_feature_engineering.py`) using expert trajectories from
replays. Output: `predict_action_distribution(state)` — 5-dim
categorical over the same action space the boss uses. This distribution
is (a) appended to the boss obs (+5 dims when `irl.enabled`) and (b)
consumed by the planner.

### 7.7 World model + planning
`WorldModel` is a small MLP predicting `(next_obs, reward)` trained
supervised on replays. `BossPlanner` does 1–2-step lookahead: rolls each
candidate boss action forward, uses the IRL `predict_action_distribution`
to weight expected player replies, picks the argmax expected return.

### 7.8 Emotion estimation
C++ `EmotionEstimationComponent` produces `(frustration, flow, boredom)`
from behavioral signals — death streak, near-death survival, action
diversity, engagement rate. Ships as an `"emotion"` JSON field consumed by
the Python side (+3 obs dims when `emotion.enabled`).

### 7.9 MAML meta-learning
`MamlPolicy` supports differentiable inner adaptation
(`create_graph=True`). `MAMLTrainer` meta-trains on multi-player replay
data. `infer.py --maml --player-id X` adapts to a new player in 2–3
gradient steps at load time.

## 8. Training protocol

1. **Persona rotation.** One overnight run per persona. Command:
   `powershell -File Tools\run_training.ps1 -Persona <persona>
   -MapName BossArena`. Editor closed; harness passes `-rlbridge` and
   `-NoTelemetry`.
2. **Pipeline sanity check.** `python smoke_test.py` runs end-to-end
   against a mock UE server in ~3 s. Must pass before any overnight run.
3. **Export.** `python export_onnx.py --checkpoint <path>` writes ONNX and
   runs an SB3-vs-ONNX agreement check (>= 99% argmax match on a random
   observation batch). Fails loud on divergence.
4. **Eval gate.** `python eval_archetypes.py` scores the exported brain
   against a seeded scripted duel. Reports reward, W/L/D, action
   distribution, entropy, mask-violation count (must be 0), rusher-vs-turtle
   divergence verdict. Turtle was promoted on a 40-0 result; rusher was
   banked but not defaulted; kiter is pending a longer re-train.
5. **Import.** `Tools/import_onnx_model.py` headlessly turns the ONNX into
   a `UNNEModelData` asset under `/Game/Arena/Models`.
6. **Wire.** Either set as `GameFeelSettings.NNEBossModelData` (default
   brain) or append as a `+NNEArchetypeBank` row keyed by persona.
7. **Re-measure centroids.** `python measure_centroids.py` recomputes the
   all-steps mean profile per persona and prints ready-to-paste ini rows.

## 9. Experimental results — what we already have

For the paper, ship the following as pre-generated artifacts:

- **`SourceArt/Models/`** — three trained ONNX checkpoints (turtle 110k,
  rusher 41k, kiter early) plus the untrained baseline. Total four
  policies for ablation.
- **`Python/tb_logs/MaskablePPO_{1,2,3}/`** — the corresponding
  TensorBoard event files. Reward, entropy, KL, mask-restriction rate,
  loss curves. Suitable for direct inclusion.
- **`Python/replays/{turtle,rusher,kiter}/episode_*.npz`** — per-episode
  arrays (`obs`, `actions`, `rewards`, `next_obs`, `dones`, and
  `player_actions` where applicable). Turtle: 160 eps / 112k steps;
  rusher: 201 eps / 41k steps; kiter: TBD.
- **`Python/eval_archetypes.py` output** — the promotion table
  (turtle 40-0, rusher dodge-only, action distributions per brain,
  entropy, mask-violation gate = 0 for all). Regenerable on demand.
- **Measured centroids** — printed by `measure_centroids.py`; current
  values live at `Config/DefaultGame.ini` `+NNEArchetypeBank=`. Include
  the mean-centered cosine separation matrix (also printed).

## 10. Experimental results — what to run for a stronger submission

Depending on target venue, the following extra runs will strengthen claims.

1. **Ablation lattice on the nine extensions.** With the shared obs
   space, each extension's contribution is testable by flipping the
   `enabled` flag in `config.yaml`. Report offline eval (as in §9) and,
   where possible, human-participant engagement metrics (see §11).
2. **Centered-cosine vs raw-cosine ablation.** Report separation matrices
   for both variants on the same measured centroids — this is a two-line
   change in `NNEBossPolicyComponent`. It quantifies the design choice.
3. **Watchdog / crash-loop mitigation study.** Report the failure mode
   diagnosed in `CLAUDE.md` (`env.timeout=10s` + tight `log_interval` →
   88-byte-empty TensorBoard trap) as a systems lesson with before/after
   numbers.
4. **Latency budget.** Measure NNE inference tick vs total frame budget
   at 15 Hz on the RTX 4050 dev machine (the ship-target). Report the
   distribution and worst-case tail.
5. **Human study.** Small (n ≈ 20) player study comparing (a) baseline
   scripted BT boss, (b) a single RL brain, (c) archetype-matched RL
   brains. Engagement measured via emotion estimator + self-report on a
   short questionnaire + survival time + retry rate.
6. **Community "one mind, many encounters" longitudinal read.** Assuming
   the site goes live (NEXTSTEP Part 0 item 5), the `meta/global` counter
   across N weeks is an interesting field observation to report — global
   win rate, most-frequent archetype match, per-biome archetype
   distribution (Tier 4 overworld only).

## 11. Figures and screenshots we can supply

Categorised for the paper's figure budget.

### 11.1 Architecture diagrams (renderable now)

- `Docs/system_architecture.puml` → `.png` (full system)
- `Docs/uml_ue_perspective.puml` → C++ side
- `Docs/uml_python_perspective.puml` → training pipeline
- `Docs/uml_player_perspective.puml` → user view
- `Docs/simple_srs_activity_diagram.puml` → activity diagram
- `Docs/simple_srs_use_case.puml` → use case
- `Docs/simple_srs_class_diagram.puml` → class diagram

All PlantUML sources exist; pre-rendered PNGs live next to them.
Best candidates for Figure 1 (system overview) and Figure 2
(training loop).

### 11.2 In-game screenshots (capturable from the packaged build)

- **Overworld map wide shot** — high-oblique of the 2 km streamed
  World-Partition-partitioned landscape with all five biomes visible
  (castle plateau + moat, W marsh, NE desert, SW mountains, plains). Doubles
  as Figure 1 (system overview illustration).
- **Per-biome mid-shot × 5** — one for each biome, with the biome's
  matched boss brain telegraphing in the foreground (paper.md §4 point 5
  mechanism illustrated at each stop).
- **Encounter-volume transition** — first frame of exploration cam,
  first frame of combat cam (arm length + FOV interp between them makes
  a clean two-panel figure).
- **Arena wide shot** (legacy `BossArena.umap`, retained for
  before/after comparison) — dressed environment, floor ring, backdrop,
  ash motes.
- Boss telegraph — red unblockable / yellow parryable indicators.
- Boss status HUD — HP bar with GoW-style damage chip, poise bar.
- Combat close-up — combo hit landing with camera shake + hit-stop.
- Minion patrol encounter — golem-bodied minions, BT-driven,
  scattered across biomes.
- Dodge i-frame moment (motion-warp target visualised via
  `combat.DebugHUD 1`).

### 11.3 Dashboard screenshots

- `Website/` (`npm run dev`) already renders demo mode without Firebase.
  Capture:
  - Login screen (`Login.jsx`)
  - Dashboard: player profile radar (8-dim), emotion timeline
    (frustration/flow/boredom over time), fight log, taunt panel
    (`Dashboard.jsx`)
  - World page — community-evolution (`World.jsx`)
  - Download page (`Download.jsx`)

### 11.4 Plots (generate from replay/tb data)

- Training curves: reward, entropy, KL, mask-restriction rate
- Per-persona action distribution histogram (from replays)
- Centroid separation matrix (heatmap, both raw and centered cosine)
- Emotion estimator time series overlaid on player HP over a full round
- Ablation bar chart (once §10 point 1 is run)

## 12. Ethics and responsible-AI

- **No player data leaves the machine without consent.** The build
  supports guest mode entirely; Firebase login is opt-in, and unset
  Firebase keys make the game guest-only (with a loud log).
- **Public identifiers, not secrets.** The Firebase `WebApiKey` is a
  public client identifier (documented as such in
  `Config/DefaultGame.ini`); we never ship a secret.
- **Player-facing explainability.** The dashboard shows *what the boss
  learned about you* (radar, timeline, taunts). Players can see their
  own dossier.
- **Community aggregate is opt-out.** Overnight training runs pass
  `-NoTelemetry`; the arbitration rule prevents scripted-bot rounds
  from ever counting.
- **No adversarial or personal manipulation objective.** The reward is
  win-rate *targeted* (default 0.45), not win-rate *maximising*.

## 13. Limitations

Anticipate reviewer questions.

- The action space is small (Discrete(5)). This is intentional for
  MaskablePPO stability but limits behavioral surface area vs a
  continuous-control alternative.
- Persona-scripted training partners are hand-authored (`AutoHero`
  personas). If a persona is missing from the bank, the runtime
  selection collapses to the default brain — currently `NNM_BossTurtle`.
- The world model horizon is 1–2 steps; longer planning would require a
  more expressive dynamics model.
- Emotion labels are behaviorally inferred, not self-reported. We do not
  claim they map to psychological ground truth.
- Human-study N is small; results should be reported with appropriate
  effect-size framing.
- All numbers reported are single-machine (RTX 4050 / 16 GB). Cross-hardware
  generalisation of latency claims is out of scope.
- **World-perf budget is single-machine.** The streamed 2 km overworld
  (World Partition, 1 km cells, 5 km HLOD1 cull) has been perf-tuned on
  the same RTX 4050 dev target as the arena — GPU budget ≤ 14 ms per
  frame at 1080p Medium. On different targets (or with the full
  Nanite-on dressing pass enabled), foliage draw distances and cloud
  view-sample counts are likely to need re-tuning. Cross-target
  generalisation is future work; the paper reports single-target
  numbers only.

## 14. Reproducibility appendix

Everything below is what the paper's supplementary should link to.

- **Repo layout.** See `CLAUDE.md` and `Docs/` diagrams.
- **Build.** UE 5.8, `Build.bat` incantation in CLAUDE.md's "Build & Run".
- **Python env.** `Python/venv` (pinned via `Python/requirements.txt`,
  including `sb3-contrib` and `onnx`).
- **Config.** All hyperparameters in `Python/config.yaml`, all
  designer-tunables in `Config/DefaultGame.ini` under
  `[/Script/GAME_CORE.GameFeelSettings]` and
  `[/Script/GAME_CORE.FirebaseAuthSubsystem]`.
- **Pipeline sanity check.** `python smoke_test.py` (mock UE bridge,
  no editor needed).
- **Offline eval.** `python eval_archetypes.py --all` (~10–20 s per
  brain, no UE, no onnxruntime).
- **Replays.** `Python/replays/<persona>/episode_NNNN.npz`.
- **Trained ONNX.** `SourceArt/Models/boss_{turtle,rusher,kiter,untrained}.onnx`.
- **TensorBoard.** `Python/tb_logs/MaskablePPO_*/`.
- **Website (demo mode).** `cd Website && npm install && npm run dev`.

## 15. Target venues

Ranked by fit.

1. **IEEE Conference on Games (CoG)** — the natural home. Track: AI in Games.
2. **AAAI AIIDE** (Artificial Intelligence for Interactive Digital
   Entertainment) — track: full papers on player experience or AI systems.
3. **IEEE Transactions on Games (TOG, formerly TCIAIG)** — journal
   version, longer form.
4. **ACM CHI PLAY** — if leading with the player-facing dashboard and
   emotion axis.
5. **FDG** (Foundations of Digital Games) — the systems track.
6. **GDC AI Summit** — industry track if leading with the shipping story.

## 16. Suggested paper outline

Adjust to venue length. This is a CoG/AIIDE full-paper shape.

1. Introduction and contributions (§3–§4).
2. Related work (§5).
3. System overview and data flow (§6).
4. Behavioral profiling and cross-encounter memory (§7.1–§7.2).
5. Persona-diverse training and archetype selection (§4 point 2, §7.3).
6. Composable extensions and shared observation space (§7.3–§7.9).
7. Deployment: ONNX + NNE + arbitration (§6.2, §4 point 10).
8. Experimental setup and results (§8, §9, §10).
9. Dashboard + community loop (§4 point 9, §11.3).
10. Discussion, limitations, ethics (§12, §13).
11. Conclusion.

## 17. Notes for the drafting AI

- **Preserve the specificity of file paths.** The paper's reproducibility
  argument depends on being able to point at
  `Source/GAME_CORE/Private/NNEBossPolicyComponent.cpp`, not "a component
  in the C++ side." Keep them.
- **Do not overclaim novelty on the individual techniques** (MAML, IRL,
  world models, MaskablePPO). Novelty is in the *composition*, the
  *shipping pipeline*, and the *archetype-matched runtime selection*.
- **Do not restate the design conventions** from `CLAUDE.md` (Mover
  gotchas, hit-guard trap, Enhanced Input Pressed-trigger trap). Those
  are engineering lessons for future maintainers, not paper content —
  unless the paper explicitly claims a systems-lessons section, in which
  case cite them tightly.
- **Numbers reported must be re-runnable.** Every number in the paper
  should trace back to `smoke_test.py`, `eval_archetypes.py`, a
  TensorBoard scalar, or a Firestore query. If a number cannot be
  reproduced by a reader in under an hour, either remove it or point at
  the artifact that produced it.
- **Sanity-check dates.** The project started fresh in this repo state;
  do not hallucinate a longer history than the git log supports.

---

*End of brief.*
