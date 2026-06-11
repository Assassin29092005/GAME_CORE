# GAME_CORE — AAA Gameplay Feel Guide

A step-by-step roadmap to take the current prototype to gameplay that *feels* like
God of War (2018) / AC Valhalla. **Scope: gameplay feel only** — responsiveness, animation
flow, boss readability, camera, hit physicality, frame pacing. Cinematic visuals (lighting,
VFX fidelity, cutscenes) are out of scope here — that's what **visuals.md** covers, at an
indie bar sized for this machine.

Everything here is grounded in the existing codebase: `CombatComponent`,
`HitReactionComponent`, `HitFeedbackComponent`, `BossActionComponent`, the RL bridge,
and the Mover-based pawns. Steps that add `UPROPERTY`/`UFUNCTION` need a full
Build.bat rebuild with the editor closed (see CLAUDE.md build caveats) — the step blocks
call this out, and it pays to batch reflected-code changes within a phase.

---

## How to use this guide

Work the phases **in order** — each builds on the previous. Phase 0–1 are foundations;
skipping them makes everything after feel worse no matter how good the animation work is.
Each phase ends with a **"Feels right when"** check — don't move on until it passes.

Every numbered step now carries a **"Step by step"** block: the exact menu path or asset
editor panel, the property name, a concrete starting value, and — for code work — the file,
the function, and what to add. Paths marked *(verify in your 5.7 build)* are stable in
UE 5.4–5.6 but worth a glance in 5.7 before hunting for a missing button.

What makes GoW/Valhalla combat feel AAA, distilled:

1. **Input is never eaten.** Every press does something, immediately or buffered.
2. **Animations commit, but cancel windows exist.** Attacks have weight because you're
   locked in — but recovery frames can be canceled into dodge/block.
3. **The enemy is readable.** Every dangerous attack telegraphs; recovery windows invite punishes.
4. **Hits land with physicality.** Hit stop, shake, reactions, knockback — all scaled to attack weight.
5. **The camera works for you.** It frames the fight, never fights you.
6. **Frame rate never hitches.** 60 fps with consistent frame *pacing* — smoothness is a
   frame-time property before it's an animation property.

---

## Phase 0 — Lock the technical foundation

Smoothness dies at the frame level first. Do this before touching any animation.

**0.1 — Set a 60 fps target and measure honestly.**
- In PIE: `stat unit`, `stat fps`. GameThread, RenderThread, and GPU all need headroom below 16.6 ms.
- Profile a full fight with **Unreal Insights** (`-trace=default`). Find hitches, not just averages —
  one 80 ms spike during a boss attack reads as "janky" even if the average is 60.
- Usual suspects in this project: synchronous work on the RL bridge tick, montage asset
  mutation in `PlayComboMontage` (it dirties shared assets), and any `LogTemp` spam left
  from debug sessions (there are known diagnostic logs to strip — see memory notes).

**Step by step:**

1. **Open the console.** Press the backtick key (`` ` ``) during PIE — once for the one-line console, twice for the console with log history. The same command field exists at the bottom of Window -> Output Log. If backtick does nothing (non-US keyboard layouts), set the key under Edit -> Project Settings -> Engine -> Input -> Console -> Console Keys.
2. **Cap and uncap deliberately.** Type `t.MaxFPS 60` to cap at the target, and `r.VSync 0` to take the display's sync out of the measurement (VSync hides whether you actually have headroom — a frame that takes 17 ms and one that takes 9 ms both show "60" with VSync on). Profile with VSync off; turn it back on (`r.VSync 1`) for normal play if you get tearing.
3. **Disable frame-rate smoothing so it can't lie to you.** Edit -> Project Settings -> Engine -> General Settings -> Framerate -> uncheck **Smooth Frame Rate**. It is on by default and clamps the frame rate into the Min/Max Smoothed Framerate band, which masks real performance. Leave **Use Fixed Frame Rate** off — fixed timestep is for offline rendering, not gameplay.
4. **Make the cap stick across sessions.** Add to `D:\GAME_CORE\Config\DefaultEngine.ini`:

   ```ini
   [SystemSettings]
   t.MaxFPS=60
   r.VSync=0
   ```

   CVars in `[SystemSettings]` apply at startup in both PIE and standalone, so your numbers are comparable day to day.
5. **Read `stat unit` correctly.** Type `stat unit` in the console. Columns: **Frame** is total frame time (target ≤ 16.6 ms at 60 fps); **Game** is the game thread; **Draw** is the render thread; **GPU** is GPU time; **RHIT** is the RHI thread; **DynRes** is dynamic resolution (should be off on this hardware). Whichever of Game/Draw/GPU sits closest to Frame is your bottleneck. On the RTX 4050 at 1080p, aim for Game and GPU both under ~14 ms so spikes don't break the cap. `stat fps` shows fps plus ms; `stat unitgraph` adds a scrolling graph of the same values — what you want is a flat line, and any vertical spike is a hitch worth chasing. `stat gpu` breaks the GPU frame into passes (BasePass, Shadows, Lumen, PostProcessing) — on 6 GB VRAM, Lumen and shadows are the passes to watch.
6. **Pin scalability while profiling.** Viewport toolbar -> Settings (the gear) -> Engine Scalability Settings -> pick one level (High is realistic for the 4050 at 1080p) and leave it there. Auto-scaling mid-session makes before/after comparisons meaningless.
7. **Trace a full fight with Unreal Insights.** In the editor, the **Trace** widget lives in the **bottom status bar** (bottom-right corner): click Trace -> **Start Trace** before the fight, fight through at least one death/respawn cycle, then **Stop Trace**. The `default` channel preset (cpu, gpu, frame, log, bookmark) is enough. For a standalone run, launch with the trace argument instead:

   ```
   "C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe" "D:\GAME_CORE\GAME_CORE.uproject" -game -windowed -resx=1920 -resy=1080 -trace=default -statnamedevents
   ```

   `-statnamedevents` adds named scopes so more of the game thread is legible. Standalone numbers are more honest than PIE — the editor itself costs game-thread time.
8. **Open the trace.** `UnrealInsights.exe` lives at `C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealInsights.exe` (you can also launch it from the same Trace status-bar menu: Trace -> Insights -> Unreal Insights (Session Browser) — verify exact menu wording in your 5.7 build). The session browser lists every trace in the local trace store automatically. Open yours, then in Timing Insights: the **Frames** track along the top shows every frame as a bar — long red bars are hitches. Click one, then read the **GameThread** track below it: the widest scope inside the spike is your culprit. The **Timers** tab (sortable by Inclusive time) tells you what's expensive *on average*; the Frames track tells you what *hitches* — you need both. Docs: [Trace Quick Start](https://dev.epicgames.com/documentation/en-us/unreal-engine/trace-quick-start-guide-in-unreal-engine) and [Unreal Insights](https://dev.epicgames.com/documentation/unreal-engine/unreal-insights-in-unreal-engine?lang=en-US).
9. **Check the known suspects first.** Search the Timers tab for montage and bridge scopes, and grep the Output Log for per-frame `LogTemp` lines — logging inside a 60 Hz tick is itself a measurable game-thread cost, and the leftover diagnostic logs should be stripped regardless.

**0.2 — Audit the RL bridge for frame-time impact.**
- `RLBridgeComponent` runs TCP at ~15 Hz. Confirm socket reads are non-blocking and JSON
  parsing never stalls the game thread. If `FTSTicker`/timer work shows up in Insights, move
  parsing to a worker thread and marshal only the resulting action back to the game thread.
- Add a **disconnect fallback now** (fully specified in Phase 4.6): the game must never
  freeze or soft-lock when Python isn't running. This is also a prerequisite for shipping
  anything — players won't have a Python process.

**Step by step:**

1. **Know what actually runs where.** Read `Source/GAME_CORE/Private/RLBridgeComponent.cpp` alongside this. The connection accept (`OnConnectionAccepted`) runs on the `FTcpListener` thread and only writes `PendingClientSocket` under `PendingSocketMutex`; `TickComponent` adopts it on the game thread. That handoff is already correct — don't touch it. Everything else — `ProcessIncomingData`, `ProcessMessage`, `HandleObserveRequest`, `SendObservation`, `SendReward` — runs on the **game thread**, throttled by `TickAccumulator` against `TickRate` (default 15; editable on BP_Boss's RLBridgeComponent under Details -> RLBridge).
2. **Verify the read can't block.** `ProcessIncomingData` calls `ClientSocket->HasPendingData(PendingDataSize)` before `ClientSocket->Recv(...)`, so the recv only fires when data is already buffered — effectively non-blocking. The blockable call is the *send* path: `FSocket::Send` in `SendObservation`/`SendReward` can stall if the OS send buffer fills. At 15 Hz to a localhost client it never will in practice, but make it explicit: in `TickComponent`, right after `ClientSocket = PendingClientSocket;`, add `ClientSocket->SetNonBlocking(true);`.
3. **Measure before moving anything.** The per-message cost is `FJsonSerializer::Deserialize` in `ProcessMessage` plus, on `"observe"` commands, `HandleObserveRequest` -> `StateObservationComponent::GetObservationJson()` (observation collection does several `FindComponentByClass` lookups, then serializes). Wrap it so Insights can see it — first line of `ProcessIncomingData` in `RLBridgeComponent.cpp`:

   ```cpp
   TRACE_CPUPROFILER_EVENT_SCOPE(RLBridge_ProcessIncomingData);
   ```

   Rebuild (Build.bat, editor closed), retrace a fight, and search `RLBridge_ProcessIncomingData` in the Timers tab.
4. **Only thread it if the numbers say so.** Tiny single-line JSON at 15 Hz should cost well under 0.5 ms. If Insights shows more (e.g., a burst of queued messages parsed in one tick inside the `while (ReceiveBuffer.FindChar(...))` loop), move the `Deserialize` call to the thread pool with `Async(EAsyncExecution::ThreadPool, ...)` and marshal only the parsed result back via `AsyncTask(ENamedThreads::GameThread, ...)`. The hard rule: `OnRLActionReceived.Broadcast(...)` and everything in the `HandleResetRequest` path touch actors and components — those must execute on the game thread only.
5. **Confirm disconnect doesn't freeze anything today.** The component already degrades: a failed `Recv` or `Send` logs "Client disconnected"/"Send failed", destroys the socket, and nulls `ClientSocket`, after which `TickComponent` early-outs. Test it: start a fight with `infer.py` running, kill the Python process mid-swing, and confirm the Output Log shows the warning and the frame rate doesn't blip. The boss will just stand there — that's the gap Phase 4.6's fallback brain fills. Wire the trigger now: poll `IsClientConnected()` (already exists, `BlueprintPure`) plus a "seconds since last action" timestamp set in `ProcessMessage`, and treat either *disconnected* or *> 2 s silent* as "switch to fallback."

**0.3 — Fix tick ordering.**
- Combat code that reads input must run after Enhanced Input processes it and before Mover
  consumes it. You already learned this the hard way (`SetMovementInput` BP hook exists
  because of it). Document tick dependencies in code wherever a component reads another
  component's per-frame state, and use tick prerequisites (`AddTickPrerequisiteComponent`)
  instead of hoping on ordering.

**Step by step:**

1. **Map who ticks in this project.** `URLBridgeComponent::TickComponent` (receives actions) and `UBossActionComponent::TickComponent` (rotation interp toward the hero, movement) both tick every frame on BP_Boss. `UCombatComponent` and `UStateObservationComponent` don't tick — they're timer- and request-driven — so they need no prerequisites.
2. **Make the boss act on this frame's decision, not last frame's.** Without a declared dependency, `BossActionComponent` may tick before `RLBridgeComponent` in the same frame, adding up to one frame (16.6 ms) of latency on every bridge action. Fix it with a prerequisite. `UBossActionComponent` has no `BeginPlay` override yet — add one to `Source/GAME_CORE/Public/BossActionComponent.h` (declare `virtual void BeginPlay() override;` in the `protected:` section) and in `Source/GAME_CORE/Private/BossActionComponent.cpp`:

   ```cpp
   void UBossActionComponent::BeginPlay()
   {
       Super::BeginPlay();
       // Tick after the bridge so an action received this frame executes this frame.
       if (URLBridgeComponent* Bridge = GetOwner()->FindComponentByClass<URLBridgeComponent>())
       {
           AddTickPrerequisiteComponent(Bridge);
       }
   }
   ```

   This follows the project's no-hard-references convention (`FindComponentByClass`, null-checked). Include `RLBridgeComponent.h` in the .cpp.
3. **Document every cross-component per-frame read.** Wherever one component reads another's per-frame state (`BossActionComponent` reading `HitReactionComponent::IsReacting()`, anything reading `LastMovementInput`), leave a one-line comment naming the dependency and whether a prerequisite enforces it. Future-you debugging a one-frame-late dodge will thank present-you.
4. **Rebuild properly.** A new `BeginPlay` override is a code change the editor must reload — close the editor and run the Build.bat command from CLAUDE.md. Don't trust Live Coding for this.

**Feels right when:** `stat unit` stays green through an entire fight including death/respawn,
and killing the Python process mid-fight degrades gracefully instead of freezing the boss.

---

## Phase 1 — Input responsiveness (the 100 ms rule)

Target: visible response to any combat input within ~100 ms (6 frames at 60 fps). GoW lives
around here — attacks *start* fast even when the swing itself is slow.

**1.1 — Extend input buffering beyond attacks.**
- `CombatComponent` already buffers attack presses inside the combo window. Generalize it:
  a small **buffered-action queue** (attack / dodge / block, with a timestamp and a ~0.3 s
  expiry). Any press during a non-cancelable animation gets queued and fires on the first
  frame it's legal. Latest-press-wins within the same action type.
- Rule of thumb from AAA action games: a press that does nothing is a bug. Either it acts,
  it buffers, or it's intentionally rejected with feedback (e.g., out-of-stamina sound).

**Step by step:**

1. **Start from what exists.** In `Source/GAME_CORE/Public/CombatComponent.h`, the current buffering is attack-only: `RequestAttack()` sets the private `bInputBuffered` flag when `bComboWindowOpen` is true, and the combo window machinery (`OpenComboWindow()` / `CloseComboWindow()` / `ComboWindowTimerHandle`, window length from `UCombatAnimConfig::ComboWindowDuration`) drains it. You're replacing that single bool with a typed slot.
2. **Add the types** to `CombatComponent.h`, above the class:

   ```cpp
   UENUM(BlueprintType)
   enum class ECombatActionType : uint8 { None, Attack, Dodge, Block };

   USTRUCT()
   struct FBufferedAction
   {
       GENERATED_BODY()
       ECombatActionType Type = ECombatActionType::None;
       double Timestamp = -1.0;   // FPlatformTime::Seconds() at press
   };
   ```

3. **Add the members** to `UCombatComponent` — a public tunable and a private slot:

   ```cpp
   /** Buffered presses older than this are dropped (seconds). */
   UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Input",
             meta = (ClampMin = "0.0", ClampMax = "1.0"))
   float BufferedActionExpiry = 0.3f;
   ```

   plus private `FBufferedAction BufferedAction;`, `void BufferAction(ECombatActionType Type);` and `bool TryConsumeBufferedAction();`. A single slot that `BufferAction` overwrites on every press *is* the latest-press-wins rule — no array needed.
4. **Wire the producers.** Any request that can't legally fire right now buffers instead of returning: `RequestAttack()` calls `BufferAction(ECombatActionType::Attack)` where it currently sets `bInputBuffered` (then delete `bInputBuffered`), and the new `RequestDodge()` / block request (1.3, Phase 3.5) buffer their own types when mid-animation. A press is only *silently* rejected if a rejection is the design — and then it gets feedback audio, not nothing.
5. **Wire the consumers.** `TryConsumeBufferedAction()` checks `FPlatformTime::Seconds() - BufferedAction.Timestamp <= BufferedActionExpiry`, clears the slot, and dispatches to `RequestAttack()` / `RequestDodge()` / the block path. Call it from every "first legal frame" site: `OpenComboWindow()` (replaces today's `bInputBuffered` drain), `OnMontageEnded` / `OnMontageBlendingOut`, `ClearCooldown()`, and — once Phase 3.2 exists — `ANS_CancelWindow`'s begin. 0.3 s is the right starting expiry: long enough to survive a swing's recovery, short enough that a stale press never fires "by itself."
6. **Rebuild.** New `UPROPERTY`/`UENUM`/`USTRUCT` means a full Build.bat rebuild with the editor closed — Live Coding will not pick up reflected metadata (CLAUDE.md build caveats). Then set `BufferedActionExpiry` on BP_NeuralHero: select the CombatComponent in the Components panel -> Details -> Combat -> Input.

**1.2 — Cut startup frames on player attacks.**
- First visible movement of each attack montage should occur within 3–5 frames of the press.
  If retargeted UEFN combo anims have slow wind-ups, trim with montage start-section offsets
  or bump the early play-rate (you already have per-attack rate in `FAttackAnimData`) —
  fast-in, normal-out preserves weight while killing perceived latency.

**Step by step:**

1. **Tune in the data asset, not the montage asset.** `FAttackAnimData` (in `Source/GAME_CORE/Public/CombatAnimConfig.h`) carries `Montage`, `PlayRate` (default 0.9), `BlendInTime` (default 0.2), `BlendOutTime` (default 0.25), `StartSection`, `bEnableRootMotion`, `DamageAmount`, and `DamageType`. `PlayComboMontage` writes the blend and rate values onto the montage at play time (the known asset-mutation behavior), so the data asset values win — editing Blend In on the montage asset itself does nothing for player combos.
2. **Find your configs.** Instances of `UCombatAnimConfig` are created via Content Browser right-click -> Miscellaneous -> Data Asset -> pick **CombatAnimConfig**. The four in use are assigned on BP_NeuralHero: select the CombatComponent in the Components panel -> Details -> Combat -> Animation -> Directional (`NeutralComboConfig`, `ForwardComboConfig`, `BackwardComboConfig`, `SideComboConfig`). Open each and expand the `ComboChain` array.
3. **Kill the blend latency first.** `BlendInTime = 0.2` is ~12 frames of cross-fade before the attack pose fully takes over — that alone blows the 100 ms budget. For the **first entry** of each `ComboChain`, drop `BlendInTime` to **0.05–0.10**. Later entries in the chain blend montage-to-montage and can stay near 0.2. Leave `BlendOutTime` alone — fast-in, normal-out.
4. **Then the rate.** If the opener still winds up slowly, raise its `PlayRate` from 0.9 to **1.1–1.2** (the field clamps at 2.0). Resist rating-up the whole chain; speed everywhere reads as weightless.
5. **Then, only if needed, skip dead frames with a section.** Double-click the offending montage in the Content Browser to open the Animation Montage editor. The montage-level properties (Blend In/Out, Rate Scale) live in the **Asset Details** panel on the left — remember those are overwritten per 1.2.1, so ignore them here. The **Sections** row sits at the top of the Montage timeline area: right-click it -> New Montage Section, name it `Strike`, and drag it to the first frame of actual forward weapon motion. If the section playback order looks wrong afterward, fix the chain in the Montage Sections panel inside the same editor (verify the exact panel name in your 5.7 build). Then set `StartSection = Strike` in that attack's `FAttackAnimData` entry — `PlayComboMontage` jumps there on play.
6. **Re-check the damage window.** The `ANS_DealDamage` notify state lives on the **Notifies** track at the bottom of the montage timeline. Notify timing scales with `PlayRate` automatically, but if you used `StartSection`, confirm the notify window still falls inside the played range — a damage window sitting in skipped frames means an attack that never hits.
7. **Measure honestly.** In PIE, type `slomo 0.2` in the console, press attack, and count frames from press to first visible movement (then `slomo 1` to restore). Target: 3–5 frames at full speed, i.e., the swing visibly *starts* within ~50–83 ms.

**1.3 — Dodge is sacred.**
- Dodge must be the single most responsive input in the game: instant from idle/locomotion,
  and available in attack recovery via cancel windows (Phase 3.2). When playtesters say
  "controls feel unresponsive," 80 % of the time they mean dodge.

**Step by step:**

1. **Create the input action.** Content Browser right-click -> Input -> Input Action, name it `IA_Dodge`, leave Value Type as Digital (bool). Open the Input Mapping Context that BP_NeuralHero already uses (the same IMC that maps `IA_Move`), click **+** under Mappings, pick `IA_Dodge`, and bind a key — Space or Left Shift on keyboard, B/Circle on gamepad.
2. **Add the code path.** In `Source/GAME_CORE/Public/CombatComponent.h`, add a dodge montage property and a request function:

   ```cpp
   UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Dodge")
   TObjectPtr<UAnimMontage> DodgeMontage;

   UFUNCTION(BlueprintCallable, Category = "Combat|Dodge")
   void RequestDodge();
   ```

3. **Implement the priority rules** in `RequestDodge()` (`Source/GAME_CORE/Private/CombatComponent.cpp`):
   - `bIsDead` -> ignore.
   - **Not attacking** -> play `DodgeMontage` immediately. Dodge must **ignore `bInAttackCooldown`** — `AttackCooldownDuration` gates attacks, never escapes. There is no acceptable "dodge on cooldown."
   - **Attacking, cancel window open** (Phase 3.2's `ANS_CancelWindow`) -> `Montage_Stop(0.05f)` on the current combo montage, then dodge immediately.
   - **Attacking, no cancel window** -> `BufferAction(ECombatActionType::Dodge)` into the 1.1 queue; it fires the frame the window opens or the montage ends.
4. **Respect the Mover gotchas.** Dodge direction comes from `LastMovementInput` (fed by the existing `SetMovementInput` BP hook), falling back to actor-backward when it's zero — never from `GetVelocity()`, which lags input on Mover pawns. The dodge montage should carry root motion so Mover integrates the displacement; reuse `PlayComboMontage`'s root-motion flag handling rather than writing a second variant, and give the dodge its own unique montage asset (the shared-asset mutation caveat applies here too).
5. **Make it instant.** Play the dodge with blend-in **0.0–0.05 s**. A dodge that cross-fades for a tenth of a second is a dodge that gets you hit.
6. **Wire the Blueprint.** BP_NeuralHero Event Graph -> add the `IA_Dodge` Triggered event -> drag the CombatComponent reference -> call **Request Dodge**. New `UFUNCTION`/`UPROPERTY` means a full Build.bat rebuild with the editor closed before the node appears.
7. **Verify the rule that matters.** From idle, dodge must start within 1–2 frames of the press (use the `slomo 0.2` counting trick from 1.2). Mid-attack, the press must never vanish — it buffers and fires at the first legal frame, every time.

**Feels right when:** mashing buttons mid-animation never produces a "dead" press, and a
dodge out of a finished swing comes out the frame the cancel window opens.

---

## Phase 2 — Locomotion (player and boss)

This is the largest visible gap between a prototype and GoW. Both pawns are Mover-based,
which constrains the options — plan around it.

**2.1 — Choose the locomotion architecture (player first).**
- **Option A — Motion Matching.** PoseSearch, MotionTrajectory, and Chooser are already
  enabled in the .uproject. Motion matching gives the GoW/Valhalla-class start/stop/pivot
  quality essentially for free *if* you have a dense locomotion dataset. Check the
  MoverExamples content for a pose-search-driven Mover pawn to copy from — most public
  motion-matching material (e.g., the Game Animation Sample) is CharacterMovementComponent-
  based, so verify trajectory generation works against Mover before committing. Budget a
  spike of 1–2 days to prove it on this project's pawns.
- **Option B — Authored blendspace + transition anims.** `BS_Boss_Locomotion` already exists
  for the boss. To reach AAA quality this way you need, per character: idle↔walk↔run blend,
  **start anims** (per direction), **stop anims** (plant feet, don't slide to a halt),
  **pivot anims** (180° turns), and **turn-in-place** for when the camera rotates while standing.
- Recommendation: Option A for the hero (it's where the player stares all game),
  Option B is acceptable for the boss (its locomotion is coarser — approach/retreat/strafe).

**Step by step (Option A spike — timebox it to 1–2 days):**

1. **Find the existence proof first.** Content Browser -> Settings (top-right of the panel) ->
   check **Show Plugin Content**, then browse to the Mover Examples Content folder under
   Plugins. Open its example maps and play them; when one of the sample pawns moves the way
   you want, open its Animation Blueprint and note how it feeds trajectory into pose search.
   What ships varies by engine version — if no pose-search-driven Mover pawn exists in your
   5.7 MoverExamples, treat that as a strong signal to take Option B (verify in your 5.7 build).
2. **Get the animation data.** The **Game Animation Sample** (Epic Games Launcher -> Fab ->
   search "Game Animation Sample", free) ships 500+ locomotion animations — idles, starts,
   stops, pivots, turn-in-place — on the UE5 Mannequin skeleton. Create it as a separate
   project, then migrate the animation folders (right-click folder -> Asset Actions ->
   Migrate, target `D:\GAME_CORE\Content`). BP_NeuralHero's mesh is UEFN/UE5-Mannequin
   family, so the anims either work directly or are one retarget away: select the imported
   sequences -> right-click -> **Retarget Animations**, pick source and target mesh — UE 5.4+
   auto-generates the IK rigs for Mannequin-family skeletons.
3. **Build the pose-search assets.** Content Browser right-click -> Animation -> Motion
   Matching -> **Pose Search Schema** (if it isn't there, search "Pose Search" in the
   right-click menu — the category moved across 5.x versions). In the schema add a
   Trajectory channel (positions + velocities, sample times like −0.3/0/+0.3/+0.6 s) and a
   Pose channel sampling both feet and the pelvis. Then create a **Pose Search Database**
   referencing the schema and drag the locomotion set into it (idle, starts, cycles, stops,
   pivots). Tag looping cycles as loops in the database entry settings.
4. **Wire the AnimGraph — this is the risk item.** In the hero AnimBP's AnimGraph, place a
   **Motion Matching** node (right-click search) pointing at the database. It needs a
   trajectory input, and the stock trajectory providers were written against
   CharacterMovementComponent. On a Mover pawn you must either use the Mover-side trajectory
   source from MoverExamples (if your build ships one — step 1 told you) or populate the
   trajectory yourself from Mover's reported velocity plus the BP-pushed input
   (`CombatComponent::SetMovementInput` — remember `GetVelocity()` lags and
   `GetLastMovementInputVector()` is dead on Mover pawns, per the CLAUDE.md gotchas).
5. **Call the verdict at the timebox.** Adopt if starts/stops/pivots visibly plant feet with
   no Blueprint band-aids. If making trajectory work requires forking plugin code, take
   Option B for both characters without guilt — authored transitions at 60 fps beat a
   half-working motion matcher every time.

**Step by step (Option B for the hero, if the spike fails):**

1. Create the blendspace: Content Browser right-click -> Animation -> **Blend Space**, pick
   the hero skeleton. In Asset Details set Horizontal Axis = Direction (−180..180),
   Vertical Axis = Speed (0..600). Drop in idle at speed 0 and the walk/run cycles at their
   natural speeds (match each anim's authored speed or feet will skate — play the anim, read
   its root displacement per second).
2. Build the locomotion state machine in the hero AnimBP: states Idle -> Start -> Cycle ->
   Stop (+ Pivot), transitions on speed and on **Time Remaining (ratio)** < 0.1 for the
   authored transitions. The start/stop/pivot anims come from the Game Animation Sample
   migration in Option A step 2 — that work is reusable either way.
3. Turn-in-place: in the Idle state, when the yaw delta between control rotation and actor
   rotation exceeds ~60°, play a 90° turn anim (left/right) with root-motion yaw. The Game
   Animation Sample ships TIP anims to retarget.

**2.2 — Movement model tuning (Mover settings).**
- Acceleration/deceleration: snappy start (high accel), slightly soft stop. Instant velocity
  changes read as "video-gamey"; long accel ramps read as "ice."
- Rotation rate: the hero should visibly *turn*, not snap — but keep it fast (500–720°/s).
  Remember `GetVelocity()` lags input on Mover pawns; drive anim direction from the
  BP-pushed input (`SetMovementInput`) like the combo selector already does.

**Step by step:**

1. Open BP_NeuralHero (Content/Blueprints) and select the **CharacterMover** component in
   the Components panel (the Mover plugin's pawn movement component).
2. In the Details panel, ground movement numbers live in the Mover component's shared
   settings object — in the 5.4–5.6 plugin this is **Common Legacy Movement Settings**,
   listed on the component alongside the Movement Modes map (verify the exact grouping in
   your 5.7 build; the property names below are from the plugin source). Set:

   | Property | Hero value | Why |
   |---|---|---|
   | Max Speed | 600 | walk/run ceiling; matches the 2.1 blendspace axis |
   | Acceleration | 4000 | snappy start — input answers within ~2–3 frames |
   | Deceleration | 2000 | slightly soft stop, so stop anims have something to do |
   | Turning Rate | 500–720 (deg/s) | visible turn, never a snap |
   | Ground Friction | default | touch only if stops feel floaty after the above |

3. On BP_Boss, the same component must have **Max Speed ≥ 400** — `BossActionComponent`
   feeds movement intent at `ApproachSpeed = 400` / `RetreatSpeed = 300` (its Details ->
   BossAction -> Movement), and Mover clamps to its own ceiling. If the boss approaches
   slower than 400, this clamp is the first thing to check.
4. Re-verify the anim-side rule after tuning: any animation logic reading "how fast am I
   moving" should read Mover's reported state or the BP-pushed input, never raw
   `GetVelocity()` at input time (one-to-two-frame lag, per CLAUDE.md).
5. Test loop: run figure-eights in PIE. Tune Acceleration first (start feel), Deceleration
   second (stop feel), Turning Rate last. Change one number per run — same discipline as
   Phase 8.

**2.3 — Grounding passes.**
- Foot IK on both characters (AnimationWarping plugin is enabled — use Foot Placement /
  leg IK nodes). Floating or sliding feet are the #1 "this is a student project" tell.
- Slope/stairs handling: verify the Mover pawns don't pogo or jitter on the arena's actual
  collision. Fix the collision, not the animation.

**Step by step:**

1. **Foot Placement node (the modern path).** Open the hero AnimBP -> AnimGraph -> right
   before Output Pose, right-click -> search **Foot Placement** (engine node, UE 5.2+). In
   its Details define the feet: FK bones `foot_l`/`foot_r`, IK bones `ik_foot_l`/`ik_foot_r`
   (the Mannequin-family skeleton has them), pelvis = `pelvis`. Defaults trace and plant
   correctly on near-flat ground, which is what a fight arena floor should be anyway.
2. Repeat in ABP_Boss. If the boss skeleton lacks IK bones, the fallback is two **Two Bone
   IK** nodes (one per leg) driven by per-foot line traces — more work, only if Foot
   Placement misbehaves on that skeleton.
3. **Slope audit.** Walk both pawns over every slope and step in the arena in PIE. Pogo or
   jitter means bad collision under the surface — open the offending mesh and simplify its
   collision (or use the arena guidance in visuals.md: keep the fight floor near-flat by
   construction). Check the Mover walking mode's max-slope setting only after collision is
   clean.
4. **Verify in slow motion.** Console -> `slomo 0.25`, walk a circle, watch the feet: no
   skating, no floating, plants on stop. Then `slomo 1`.

**2.4 — Boss locomotion personality.**
- Wire `BS_Boss_Locomotion` so Approach/Retreat/strafe come through the blendspace with
  proper lean and footwork — the boss should *walk with intent*, not glide.
- Cap boss rotation rate (no instant 180° snaps toward the player) and add turn-in-place
  for large heading changes. A boss that physically turns to face you is half of what makes
  it feel like a creature instead of a turret. This also interacts with Phase 4 action
  smoothing — a rotation cap makes the 15 Hz action stream look deliberate.

**Step by step:**

1. **Feed the blendspace from the boss's intent, not its velocity.** `BossActionComponent`
   already exposes exactly the right API (all BlueprintPure): `IsMoving()`,
   `GetIntendedMoveSpeed()` (returns 0 when idle, `ApproachSpeed`/`RetreatSpeed` when
   moving), and `GetIntendedMoveDirection()` (world-space). In ABP_Boss's Event Graph,
   each tick: Speed = **FInterpTo**(current, `GetIntendedMoveSpeed()`, DeltaTime, 6.0) —
   the interpolation is what makes decelerate-plant-turn visible (Phase 4.2 step 4 relies
   on this same node); Direction = **Calculate Direction**(`GetIntendedMoveDirection()` ×
   current interp speed as a velocity, owner's actor rotation) — gives the signed −180..180
   the blendspace wants.
2. **Set the blendspace axes.** Open `BS_Boss_Locomotion` (Content/Blueprints) -> Asset
   Details: Horizontal = Direction (−180..180), Vertical = Speed (0..400, matching
   `ApproachSpeed`). Place: idle at (0,0), walk-forward at (0, 300–400), strafes at
   (±90, 300), walk-back at (±180, 300) — `RetreatSpeed = 300` means the boss backs away
   *facing you*, which is correct boss body language.
3. **State machine.** ABP_Boss AnimGraph: Idle <-> Moving states; enter Moving on
   `IsMoving()`, leave when the interpolated speed drains below ~5. The blendspace plays
   inside Moving.
4. **Rotation cap already exists** — `RotationInterpSpeed = 8.0` on BossActionComponent
   (Details -> BossAction -> Movement) drives the facing interp in `TickComponent`. Drop to
   5–6 if 180° turns still read snappy; big creatures turn slower and look heavier for it.
5. **Turn-in-place.** When idle with yaw error > 60°, an interp-rotated idle pose looks like
   a statue on a turntable. Minimum viable fix: two root-motion turn montages (left/right
   90°, retargeted from the Game Animation Sample) triggered from ABP_Boss when
   (not `IsMoving()`) AND (not `IsPerformingAction()`) AND abs(yaw delta) > 60°. Gate on
   `HitReactionComponent::IsReacting()` too so a turn can't interrupt a flinch.
6. **Watch a fight muted.** Approach -> stop -> strafe -> retreat should read as footwork
   with intent. If any transition still reads as velocity-flip gliding, the fix is in
   step 1's interp speed, not in more animation.

**Feels right when:** you can run circles, stop, and pivot with no foot sliding, and the
boss visibly plants and turns rather than rotating like a tank turret.

---

## Phase 3 — Player combat feel

The combo skeleton (directional combos, buffering, motion warping, hit stop) already exists.
This phase is about commitment, cancels, and weight.

**3.1 — Define the attack frame model.**
Every attack has three windows; make them explicit per `FAttackAnimData` entry instead of implicit:
- **Startup** (no cancel — commitment is what gives weight),
- **Active** (the `ANS_DealDamage` window),
- **Recovery** (cancelable into dodge/block, and into the next combo input).

**Step by step:**

1. **Audit what you have.** For each player attack montage (the `Montage` entries inside the
   four `UCombatAnimConfig` data assets' `ComboChain` arrays): open it, read total length
   from the timeline, and note where the `ANS_DealDamage` bar sits on the **Notifies**
   track. Startup = 0 to window start; Active = the window; Recovery = window end to montage
   end. Write the table down — Phases 3.2–3.5 fill these windows with mechanics, and you
   can't place a cancel window without knowing where recovery begins.
2. **The active window is already data.** `ANS_DealDamage` exposes `TraceRadius = 80` and
   `TraceForwardOffset = 120` per placement — select the notify bar in the montage and tune
   them in the Details panel per attack (a lunging stab wants more forward offset than a
   close slash).
3. **Sanity targets at 60 fps:** lights — startup 0.15–0.25 s, active 0.1–0.15 s, recovery
   0.3–0.4 s. Heavies — up to double the startup and recovery. If an audit row is wildly
   off, fix it with the Phase 1.2 tools (play rate, start sections) before adding mechanics
   on top.

**3.2 — Add cancel windows via a new notify state.**
- Create `ANS_CancelWindow` (mirror the `ANS_DealDamage` pattern — operate on the owner's
  `CombatComponent`, not notify-state members, for the same UE5 reliability reason).
- While active: dodge and block requests cancel the montage immediately; the buffered-action
  queue (1.1) drains here. Place it over recovery frames of every player attack.
- GoW calibration: light attacks cancel generously, heavies commit hard and cancel late.
  This asymmetry *is* the light/heavy feel difference.

**Step by step:**

1. **Create the class.** Tools -> New C++ Class -> All Classes -> search **AnimNotifyState**
   -> name it `ANS_CancelWindow` (or copy the `ANS_DealDamage.h/.cpp` pair in
   `Source/GAME_CORE/` and strip the trace logic — the file layout is the template).
2. **State lives on the attacker, not the notify.** Add to
   `Source/GAME_CORE/Public/CombatComponent.h`: a private `bool bCancelWindowOpen = false;`
   plus public `void SetCancelWindowOpen(bool bOpen);` and
   `UFUNCTION(BlueprintPure) bool IsCancelWindowOpen() const;`. The notify's `NotifyBegin`
   does `MeshComp->GetOwner()->FindComponentByClass<UCombatComponent>()` ->
   `SetCancelWindowOpen(true)`; `NotifyEnd` sets false. This mirrors `ANS_DealDamage`
   exactly — its own private `bHasHitThisSwing` member survives only as a vestige; the
   working guard lives on the component because notify-state instance members proved
   unreliable in UE5 (the comment in `ANS_DealDamage.cpp` documents it).
3. **Clear defensively.** Montage interruption can skip `NotifyEnd`, so also force the flag
   false in `PlayComboMontage` (each new swing) and `OnMontageEnded` in
   `Source/GAME_CORE/Private/CombatComponent.cpp`. A stuck-open cancel window is an
   everything-cancels bug you'll chase for an evening.
4. **Consume it.** `RequestDodge()` checks it per Phase 1.3 step 3. And make
   `SetCancelWindowOpen(true)` call `TryConsumeBufferedAction()` — a dodge pressed during
   startup fires the exact frame the window opens. That hookup is the single most
   feel-critical line in this phase.
5. **Place the windows.** Open each player attack montage -> Notifies track -> right-click ->
   Add Notify State -> **Cancel Window** -> drag the bar over recovery: from just after the
   `ANS_DealDamage` bar ends to ~85% of the montage. Lights: generous (window opens right
   after damage). Heavies: last quarter only. Don't let any window reach 100% — the last
   ~15% should blend to idle through the normal path or the combo chain link.
6. **Rebuild** (new `UFUNCTION` — Build.bat, editor closed), then re-run the Phase 1 mash
   tests; the "dead press" count should now be zero across all timings.

**3.3 — Soft-lock targeting and attack steering.**
- GoW uses aggressive soft-lock: attacks magnetize toward the enemy the stick is biased
  toward. You have the pieces — `UpdateMotionWarpTarget` already aims the warp. Add target
  *selection* (score candidates by stick direction · angle · distance) and allow small
  rotation toward the target during startup frames only.
- **Clamp warp distance** (e.g., max 250–400 cm depending on attack) and warp translation
  speed. Unclamped warps produce the "vacuum slide" that instantly reads as janky. Out of
  range → attack whiffs in place; that's correct and fair.

**Step by step:**

1. **Know today's behavior.** `UCombatComponent::UpdateMotionWarpTarget()`
   (`Source/GAME_CORE/Private/CombatComponent.cpp`, ~line 424) sets the warp target to
   `WarpTargetActor->GetActorLocation()` *exactly*, rotation toward it, no distance limit.
   With root motion plus a Motion Warping window, that is a vacuum slide from any range.
2. **Add the tunables** to `CombatComponent.h` under `Category = "Combat|Warping"`:

   ```cpp
   /** Beyond this distance the attack plays in place (whiff) instead of warping. */
   UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Warping")
   float MaxWarpDistance = 350.0f;

   /** The warp stops this far short of the target so the attacker never clips inside it. */
   UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Warping")
   float WarpStopDistance = 120.0f;
   ```

3. **Clamp in `UpdateMotionWarpTarget()`** — replace the location assignment:

   ```cpp
   const FVector OwnerLoc = Owner->GetActorLocation();
   const FVector ToTarget = WarpTargetActor->GetActorLocation() - OwnerLoc;
   const float Dist = ToTarget.Size2D();

   FVector WarpLocation = OwnerLoc;            // default: attack in place (whiff)
   if (Dist > KINDA_SMALL_NUMBER && Dist <= MaxWarpDistance)
   {
       WarpLocation = WarpTargetActor->GetActorLocation()
                    - ToTarget.GetSafeNormal2D() * WarpStopDistance;
   }
   WarpTarget.Location = WarpLocation;
   // keep the existing rotation line — facing the target on a whiff still looks right
   ```

4. **Steer only toward intent.** Don't warp to a target behind the player's input: if
   `LastMovementInput` is non-zero and `FVector::DotProduct(LastMovementInput.GetSafeNormal(),
   ToTarget.GetSafeNormal2D()) < 0`, treat it as out of range (whiff in place). Attacks
   magnetize toward where you're steering — never yank you backward.
5. **Confirm the montage side.** Each attack montage needs a **Motion Warping** notify state
   window (Notifies track -> Add Notify State -> Motion Warping) covering the approach
   frames, with **Warp Target Name = AttackTarget** — matching `WarpTargetName`'s default on
   CombatComponent — and `bEnableRootMotion = true` in that attack's `FAttackAnimData`
   (already the default). No window, no warp, regardless of the C++.
6. **Target selection.** `SetWarpTarget()` is BlueprintCallable and BP_NeuralHero currently
   pins it to the boss — fine with one enemy. When adds exist, add a `SelectWarpTarget()`
   that scores candidates by `0.6 × stick-direction dot + 0.4 × (1 − Dist / 800)` using
   `LastMovementInput` — the same input-priority chain `SelectComboByDirection()` already
   uses, for the same Mover reason.
7. **Verify both ends:** attack from 10 m — swing in place, zero slide. Attack from 3 m —
   glide to ~1.2 m and stop. Attack while steering away from the boss — whiff, no yank.

**3.4 — Scale hit feedback to attack weight.**
- You already do per-actor `CustomTimeDilation` hit stop and camera shake via
  `HitFeedbackComponent`. Move the magic numbers into `FAttackAnimData`: per-attack hit-stop
  duration (lights ~0.05–0.08 s, heavies/finishers ~0.10–0.15 s), shake tier, and knockback
  impulse. Combo finishers should *visibly* hit harder than openers.
- Add a tiny FOV kick or camera punch on heavy hits — it's a camera behavior, not a visual
  effect, and it's a large fraction of "weight."

**Step by step:**

1. **Add the per-attack fields** to `FAttackAnimData` in
   `Source/GAME_CORE/Public/CombatAnimConfig.h` (new `Category = "Feedback"` block):

   ```cpp
   UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Feedback",
             meta = (ClampMin = "0.0", ClampMax = "0.3"))
   float HitStopDuration = 0.08f;     // matches HitFeedbackComponent's current global

   UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Feedback",
             meta = (ClampMin = "0.0", ClampMax = "2.0"))
   float CameraShakeScale = 1.0f;

   UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Feedback")
   float KnockbackImpulse = 0.0f;     // consumed in Phase 6.3
   ```

2. **The plumb-through point already exists.** `ANS_DealDamage::NotifyTick`
   (`Source/GAME_CORE/Private/ANS_DealDamage.cpp`) already looks up the attack —
   `AttackerCombatGuard->CombatConfig->GetAttackData(AttackerCombatGuard->GetComboStep())` —
   for damage, then a few lines later calls `TargetFeedback->TriggerHitFeedback(OwnerActor)`.
   Add an overload in `Source/GAME_CORE/Public/HitFeedbackComponent.h`:
   `void TriggerHitFeedback(AActor* Attacker, float StopDuration, float ShakeScale);`
   (the existing fields `HitStopTimeDilation = 0.05`, `HitStopDuration = 0.08`,
   `CameraShakeScale = 1.0` stay as the no-argument defaults), and pass
   `AttackData->HitStopDuration` / `AttackData->CameraShakeScale` at that existing call site.
3. **Starting values per chain position:** opener 0.05 s / scale 0.7 -> mid-chain 0.08 / 1.0
   -> finisher 0.12–0.15 / 1.5. The finisher should also route through the already-existing
   `TriggerHeavyHitFeedback()` (it's real, on HitFeedbackComponent) — branch on
   `GetComboStep() == ComboChain.Num() - 1` at the same call site.
4. **FOV punch rides the shake asset.** Create the shake: Content Browser right-click ->
   Blueprint Class -> search **DefaultCameraShakeBase** -> `CS_HitLight` / `CS_HitHeavy`.
   In its Details set **Root Shake Pattern = Perlin Noise Camera Shake Pattern**, Duration
   0.15–0.25, small rotation amplitudes (Pitch/Yaw 0.3–0.6), and on the heavy variant an
   **FOV amplitude of 1.5–2** (the pattern has Location/Rotation/FOV sections — verify the
   exact property layout in your 5.7 build). Assign to **HitCameraShake** on each pawn's
   HitFeedbackComponent (Details -> HitFeedback -> CameraShake).
5. **Rebuild** (struct change — Build.bat, editor closed), set values in the four data
   assets, and tune in Phase 8's 20-minute loops. These numbers are exactly why the fields
   are data, not constants.

**3.5 — Dodge i-frames and block/parry.**
- Dodge: invulnerability through an `ANS`-driven window on `CombatComponent` (reuse the
  invulnerability flag pattern from `PostResetInvulnerabilityDuration` — make it a counter
  or enum source so reset-invuln and dodge-invuln don't fight over one bool).
- Block: damage reduction + a dedicated block-impact reaction (not the flinch montage).
- Parry: block pressed within ~0.15 s before impact → attacker gets a heavy stagger
  (you have stagger intensity in `HitReactionComponent`) + a longer hit stop. A working
  parry against a *learning* boss is a headline feature — the RL agent will actually adapt
  its attack timing around player parry habits, which no scripted boss does.

**Step by step (i-frames):**

1. **Do not reuse `bIsInvulnerable`.** `ResetForNewRound()` owns it via `InvulnTimerHandle`
   (`CombatComponent.h` documents the why) — a second owner of that bool will clear or be
   cleared by the reset window. Add a separate private `bool bDodgeInvulnerable = false;`
   with a setter, and extend the early-out at the top of `ApplyDamage`:
   `if (bIsDead || bIsInvulnerable || bDodgeInvulnerable) return;`. Clear it in
   `ResetForNewRound()` too (a dodge interrupted by death must not leak i-frames into the
   next round).
2. **Create `ANS_Invulnerable`** — copy `ANS_CancelWindow` from 3.2, swap the calls to
   `SetDodgeInvulnerable(true/false)`. Same owner-side-state pattern, same defensive clears.
3. **Place it on the dodge montage** covering roughly 10%–60% of the roll (≈0.3 s of
   i-frames in a 0.7 s dodge). The shape matters: i-frames start a beat *after* the press
   and end *before* recovery — that's dodge timing as a skill, not dodge spam as a defense.

**Step by step (block, then parry on top):**

1. **Input.** Content Browser right-click -> Input -> Input Action -> `IA_Block` (Digital).
   Add to the hero's Input Mapping Context. In BP_NeuralHero: `IA_Block` **Started** ->
   `SetBlocking(true)`, **Completed** -> `SetBlocking(false)` (new BlueprintCallable on
   CombatComponent alongside `bIsBlocking` and
   `UPROPERTY(EditAnywhere) float BlockDamageMultiplier = 0.25f;`).
2. **Give damage an instigator.** `ApplyDamage(float)` currently has no attacker parameter —
   extend it with a default so nothing else breaks:
   `void ApplyDamage(float DamageAmount, AActor* Instigator = nullptr);` and pass
   `OwnerActor` at the one real call site — `ANS_DealDamage::NotifyTick`, the
   `TargetCombat->ApplyDamage(DamageAmount)` line. Cache
   `LastHitDirection = (GetOwner()->GetActorLocation() - Instigator->GetActorLocation()).GetSafeNormal2D();`
   while you're in there — Phase 6.2's ragdoll impulse needs it.
3. **Block math in `ApplyDamage`**, after the early-outs: if `bIsBlocking` and the hit comes
   from the front (`FVector::DotProduct(Owner forward, ToInstigator) > 0.3`), multiply
   damage by `BlockDamageMultiplier` and play a dedicated `BlockImpactMontage` (new
   `UPROPERTY`) — do **not** route through `PlayHitReaction`, or blocking inherits stagger
   accumulation and flinches, which defeats the point of blocking.
4. **Parry is block-press recency.** `SetBlocking(true)` stamps
   `LastBlockStartTime = GetWorld()->GetTimeSeconds();`. In the front-hit branch, before the
   block math: if `Now - LastBlockStartTime <= ParryWindow` (new `UPROPERTY`, 0.15 s) —
   parry: take zero damage, and punish the attacker:

   ```cpp
   if (UHitReactionComponent* AttackerReaction =
           Instigator->FindComponentByClass<UHitReactionComponent>())
   {
       // >= HeavyStaggerThreshold (60) forces a heavy reaction in one hit
       AttackerReaction->PlayHitReaction(GetOwner(), 61.0f, FName(TEXT("Parry")));
   }
   if (UHitFeedbackComponent* AttackerFeedback =
           Instigator->FindComponentByClass<UHitFeedbackComponent>())
   {
       AttackerFeedback->TriggerHeavyHitFeedback(GetOwner());   // the long freeze
   }
   ```

5. **Parry pierces hyper-armor — by design.** Phase 4.5 adds hyper-armor that eats Light
   reactions during boss heavies; exempt `DamageType == "Parry"` in that early-out so parry
   stays the counterplay to armored attacks. (The 61-damage stagger hit also fills the
   boss's poise bar — correct: a parried boss should be one hit from a Medium stagger.)
6. **Feedback completes it:** the parry *ting* (Phase 7.1) plus the heavy freeze make the
   0.15 s window learnable. Verify with `slomo 0.2`: block raised early = chip damage;
   block pressed inside 0.15 s = boss staggers, you don't.

**Feels right when:** light combos flow and cancel freely, heavies feel like a deliberate
bet, every landed hit has obviously different weight by attack, and dodge-through-attack
is reliable and readable.

---

## Phase 4 — Boss feel: making the RL agent read like a hand-authored AAA boss

This is the project's unique problem. A policy emitting discrete actions at ~15 Hz looks
twitchy and arbitrary by default. AAA bosses feel great because of an *execution layer*
between "decision" and "animation." Build that layer in `BossActionComponent` — the RL
policy stays untouched; you're changing how decisions get performed.

Know the real pipeline before touching it: the bridge fires `OnRLActionReceived` →
`UBossActionComponent::ExecuteAction(int32)` → `ExecuteActionEnum(EBossAction)`, which
currently has exactly two gates — `if (bIsDead || bIsPerformingAction) return;` and the
`HitReaction->IsReacting()` lockout — then dispatches to `DoAttack` / `DoBlock` /
`DoDodge` / `DoApproach` / `DoRetreat`. Everything below slots new gates into that one
function, in a fixed order: dead → committed/locked-out → reacting → hysteresis → mask →
dispatch. Most steps add `UPROPERTY` members, so budget a full Build.bat rebuild with the
editor closed per the CLAUDE.md caveats — batch them.

**4.1 — Action commitment (minimum durations).**
- Once an action starts, ignore new bridge actions until it completes its minimum duration
  (Attack: full montage — already true; Dodge: full roll; Approach/Retreat: ≥ 0.4–0.6 s;
  Block: ≥ 0.5 s hold). The `IsReacting()` lockout already does this for hit reactions —
  generalize the same gating to all five actions.
- Good news: you're closer than the guide's framing suggests. `bIsPerformingAction` already
  holds for the full montage on Attack/Block/Dodge (cleared in `OnActionMontageEnded`) and
  for `MoveDuration` (default 0.5 s) on Approach/Retreat (cleared in `StopMovement`). The
  real gaps: Block's commitment is whatever the `BlockMontage` happens to last — a 0.3 s
  block flinch releases early — and none of it is per-action tunable.

**Step by step:**

1. In `Source/GAME_CORE/Public/BossActionComponent.h`, add tunables (e.g. below
   `MoveDuration` in the `BossAction|Movement` block, new category `BossAction|Commitment`):

   ```cpp
   /** Minimum hold time for Block, even if BlockMontage is shorter. */
   UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Commitment")
   float MinBlockDuration = 0.5f;
   ```

   Approach/Retreat already commit via `MoveDuration = 0.5f` — that's inside the 0.4–0.6 s
   band, so keep it and treat it as the movement entry in the table below. Add private
   state next to `bIsPerformingAction`:

   ```cpp
   EBossAction CurrentAction = EBossAction::Count;  // Count == none
   double ActionStartTime = 0.0;
   float CurrentMinDuration = 0.0f;
   ```

2. The minimum-duration table you're implementing:

   | Action | Minimum duration | Enforced by |
   |---|---|---|
   | Attack | full montage length | existing `bIsPerformingAction` + `OnActionMontageEnded` |
   | Dodge | full roll montage | same as Attack |
   | Block | `max(BlockMontage->GetPlayLength(), MinBlockDuration)` (0.5 s) | new time check |
   | Approach / Retreat | `MoveDuration` (0.5 s; tune 0.4–0.6) | existing `StopMovement` timer |

3. In `Source/GAME_CORE/Private/BossActionComponent.cpp`, in `ExecuteActionEnum`, insert the
   commitment check immediately after the existing `if (bIsDead || bIsPerformingAction) return;`
   line and before the `IsReacting()` block:

   ```cpp
   const double Now = GetWorld()->GetTimeSeconds();
   if (CurrentAction != EBossAction::Count && Now - ActionStartTime < CurrentMinDuration)
       return; // committed — drop this decision on the floor
   ```

4. Record the commitment when each action fires: at the end of the `switch`, set
   `CurrentAction = Action; ActionStartTime = Now;` and set `CurrentMinDuration` per the
   table (`AttackMontage->GetPlayLength()` for Attack, the `max(...)` expression for Block,
   `MoveDuration` for moves). Clear it (`CurrentAction = EBossAction::Count`) in
   `OnActionMontageEnded`, `StopMovement`, `HandleDeath`, and `ResetForNewRound`.

5. Rebuild with Build.bat (editor closed — new `UPROPERTY`). Verify in PIE: spam-watch the
   `BossAction:` log lines; you should never see two different actions within 0.4 s of each
   other except Attack→nothing (montage end).

**4.2 — Hysteresis on movement actions.**
- Approach→Retreat flip-flopping at 67 ms cadence is the single worst-looking artifact.
  Require either the minimum duration (4.1) *or* N consecutive identical decisions before
  switching movement direction. Blend the transition through `BS_Boss_Locomotion`
  (decelerate, plant, turn) instead of reversing velocity.

**Step by step:**

1. Same files as 4.1. Add to `BossActionComponent.h`:

   ```cpp
   UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Commitment",
             meta = (ClampMin = "1", ClampMax = "10"))
   int32 MovementFlipVotes = 3;  // ~200 ms of agreement at 15 Hz

   // private:
   EBossAction LastMovementAction = EBossAction::Count;
   EBossAction PendingMovementAction = EBossAction::Count;
   int32 PendingMovementVoteCount = 0;
   ```

2. In `ExecuteActionEnum`, after the 4.1 commitment check and the `IsReacting()` gate,
   before the `switch`:

   ```cpp
   const bool bIsMove = (Action == EBossAction::Approach || Action == EBossAction::Retreat);
   if (bIsMove && LastMovementAction != EBossAction::Count && Action != LastMovementAction)
   {
       // Direction reversal: allow only after min duration elapsed OR N consecutive votes.
       PendingMovementVoteCount = (Action == PendingMovementAction) ? PendingMovementVoteCount + 1 : 1;
       PendingMovementAction = Action;
       const bool bMinElapsed = (Now - ActionStartTime) >= CurrentMinDuration;
       if (!bMinElapsed && PendingMovementVoteCount < MovementFlipVotes)
           return; // hold course
   }
   if (bIsMove)
   {
       LastMovementAction = Action;
       PendingMovementVoteCount = 0;
       PendingMovementAction = EBossAction::Count;
   }
   ```

   Reset `LastMovementAction` in `ResetForNewRound` alongside the other state.

3. Never reverse `MoveDirection` mid-move. The flow above guarantees a reversal only starts
   from idle (after `StopMovement` has run), so the blendspace sees speed go
   `ApproachSpeed → 0 → RetreatSpeed` instead of an instant sign flip.

4. Make the deceleration visible: in ABP_Boss's AnimGraph, don't feed
   `GetIntendedMoveSpeed()` raw into the `BS_Boss_Locomotion` speed input — interpolate it
   (Float Interp / `FInterpTo` node, interp speed ≈ 6) so the boss visibly decelerates,
   plants, and turns. The turn itself is already handled by the capped
   `RotationInterpSpeed = 8.0` facing logic in `TickComponent`.

**4.3 — Action masking (legality filter).**
- Before executing, validate: Attack only within range + facing tolerance; Dodge only if
  not already mid-dodge; etc. Illegal action → fall back to the nearest legal one (Attack
  out of range → Approach). Two options, in order of preference:
  a) **Mask Python-side**: send a legal-action bitmask in the observation JSON and mask
     logits in `BossEnv` — the policy then *learns* with the mask and training matches inference.
  b) Mask C++-side only — simpler, but creates train/inference mismatch. Fine as a first step.

**Step by step (C++ side — do this first):**

1. In `BossActionComponent.h`, add tunables under a `BossAction|Masking` category:

   ```cpp
   UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Masking")
   float AttackRange = 250.0f;            // cm; match montage reach + warp clamp

   UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Masking")
   float AttackFacingToleranceDeg = 45.0f;
   ```

2. Add a private helper in `BossActionComponent.cpp` and call it in `ExecuteActionEnum`
   right before the `switch` (`Action = ApplyActionMask(Action);`):

   ```cpp
   EBossAction UBossActionComponent::ApplyActionMask(EBossAction Action) const
   {
       if (Action != EBossAction::Attack || !TargetActor) return Action;
       const FVector ToTarget = TargetActor->GetActorLocation() - GetOwner()->GetActorLocation();
       const float Dist = ToTarget.Size2D();
       const float FacingDeg = FMath::RadiansToDegrees(FMath::Acos(
           FVector::DotProduct(GetOwner()->GetActorForwardVector(), ToTarget.GetSafeNormal2D())));
       if (Dist > AttackRange || FacingDeg > AttackFacingToleranceDeg)
           return EBossAction::Approach;  // nearest legal substitute
       return Action;
   }
   ```

   Dodge-while-mid-dodge is already illegal via `bIsPerformingAction`; nothing to add there.
   Start with `AttackRange = 250` and tighten once motion-warp clamping (Phase 3.3) is in.

3. Know the caveat you just bought: the policy was trained believing "Attack at range 800"
   does something; at inference you silently substitute Approach. That's train/inference
   mismatch — fine for feel work, but the boss's learned timing will be slightly off until
   you do the Python side.

**Step by step (Python side — the correct fix):**

1. The critical correctness point: **vanilla Stable Baselines3 `PPO` does not support action
   masking.** No flag, no kwarg. Masking the policy requires `MaskablePPO` from
   **sb3-contrib**:

   ```
   pip install sb3-contrib
   ```

2. Ship the mask from C++: expose the same legality logic as a
   `UFUNCTION(BlueprintPure) TArray<bool> GetLegalActionMask() const` on
   `BossActionComponent`, and add a `"mask": [1,1,1,1,1]`-style array field where
   `StateObservationComponent` serializes `FRLObservation` to JSON (the same payload
   `RLBridgeComponent::SendObservation` ships).

3. In `D:\GAME_CORE\Python\boss_env.py`, in `BossEnv._receive_observation`, store the field,
   and add the method `MaskablePPO` looks for:

   ```python
   self._last_action_mask = np.array(data.get("mask", [1] * 5), dtype=bool)

   def action_masks(self) -> np.ndarray:
       return self._last_action_mask
   ```

   The env must expose `action_masks()` (or be wrapped in
   `sb3_contrib.common.wrappers.ActionMasker`) — `MaskablePPO` calls it during rollout
   collection automatically.

4. In `Python/train.py`, swap the algorithm:

   ```python
   from sb3_contrib import MaskablePPO   # instead of: from stable_baselines3 import PPO
   model = MaskablePPO("MlpPolicy", env, ...)
   ```

   The `training.algorithm: "PPO"` key in `Python/config.yaml` should be updated to match
   if `train.py` branches on it. In `Python/infer.py`, pass the mask explicitly:
   `model.predict(obs, action_masks=env.action_masks(), deterministic=True)`.

5. Order of operations: ship the C++ mask now (instant feel win), retrain with `MaskablePPO`
   when you next retrain anyway. Don't block the feel pass on a training run.

**4.4 — Telegraphs: the fairness contract.**
- Every boss attack needs a readable anticipation: a distinct wind-up pose held for
  0.3–0.6 s scaled by damage, plus an audio cue. If the retargeted attack montages have
  weak wind-ups, stretch the first section's play rate (slow-in) — cheap and effective.
- Valhalla-style rune flash on unblockables is UI, not VFX-budget — a simple indicator
  widget is enough (Phase 7).

**Step by step:**

1. Open the boss attack montage: in the Content Browser, double-click the asset assigned to
   `AttackMontage` on BP_Boss's BossActionComponent (check the component's Details panel ->
   BossAction -> Montages if you've forgotten which asset that is).

2. Split the montage into sections. In the montage editor timeline, right-click the
   **Sections** track -> New Montage Section. Create `Windup` at time 0 and `Active` at the
   frame the swing starts traveling — just before your `ANS_DealDamage` window begins. In
   the Montage Sections panel (Window -> Montage Sections in UE 5.4–5.6; verify exact
   location in your 5.7 build), confirm `Windup` chains into `Active` sequentially.

3. Slow the wind-up at runtime. Montages don't store per-section play rates, so set the rate
   on play and restore it at the section boundary. In
   `UBossActionComponent::DoAttack` (or inside `PlayMontage`), after `Montage_Play`:

   ```cpp
   AnimInstance->Montage_SetPlayRate(AttackMontage, 0.6f);  // slow-in
   ```

   Then create a tiny notify to restore speed — `UAnimNotify` subclass `AN_RestoreRate`
   (mirror the `ANS_DealDamage` file layout in `Source/GAME_CORE/`) whose `Notify` override does:

   ```cpp
   if (UAnimInstance* AI = MeshComp->GetAnimInstance())
       AI->Montage_SetPlayRate(AI->GetCurrentActiveMontage(), 1.0f);
   ```

   Place it in the montage editor: right-click the Notifies track at the start of the
   `Active` section -> Add Notify -> AN_RestoreRate. Net effect: a 0.5 s wind-up plays at
   0.6× (~0.83 s of readable anticipation), the swing lands at full speed. Tune the rate per
   attack damage — heavier hit, slower wind-up, aiming for 0.3–0.6 s of held anticipation.

4. Audio cue: in the same montage, right-click the Notifies track at the wind-up start ->
   Add Notify -> Play Sound. Select the new notify, and in the Details panel set **Sound**
   to a boss grunt/whoosh cue (any free pack placeholder works — Phase 7.1 upgrades it).
   This same cue is the off-screen warning 5.3 depends on, so do it now.

5. One montage per attack, always — `PlayComboMontage` and `PlayHitReaction` already mutate
   shared assets (known project constraint), and `Montage_SetPlayRate` games on top of a
   shared montage would interleave the same way.

**4.5 — Recovery windows are a gift to the player.**
- After every boss attack, enforce a recovery period where the boss cannot act
  (extend the `IsReacting()`-style gate to cover post-attack recovery). Heavier attack →
  longer recovery. This is what makes a boss feel *fair* — and notably, the RL reward
  doesn't need to know: it's an execution-layer constraint, like a human's reaction time.
- Pair with **hyper-armor** on the heaviest attacks: ignore light-stagger thresholds during
  their active frames (`HitReactionComponent` stagger intensity already gives you the dial),
  so the player can't infinitely flinch-lock the boss.

**Step by step (recovery gate):**

1. This is the exact pattern `HitReactionComponent` already uses for its grace period
   (`LastReactionEndTime` + `HitReactionGracePeriod = 0.25` keeping `IsReacting()` true past
   montage end) — replicate it for attacks. In `BossActionComponent.h`:

   ```cpp
   UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Commitment")
   float AttackRecoveryDuration = 0.7f;   // heavier attacks: 0.9-1.2

   // private:
   double ActionLockoutUntil = 0.0;
   ```

2. In `BossActionComponent.cpp`, `OnActionMontageEnded` currently just flips
   `bIsPerformingAction = false`. Extend it:

   ```cpp
   void UBossActionComponent::OnActionMontageEnded(UAnimMontage* Montage, bool bInterrupted)
   {
       bIsPerformingAction = false;
       CurrentAction = EBossAction::Count;
       if (Montage == AttackMontage && !bInterrupted)
           ActionLockoutUntil = GetWorld()->GetTimeSeconds() + AttackRecoveryDuration;
   }
   ```

3. Gate on it in `ExecuteActionEnum`, in the same block as the 4.1 commitment check:
   `if (Now < ActionLockoutUntil) return;`. Zero it in `ResetForNewRound` and `HandleDeath`.
   When you later add multiple boss attacks, move the duration into a per-montage
   `TMap<TObjectPtr<UAnimMontage>, float>` — heavier attack, longer number.

**Step by step (hyper-armor):**

1. The real dials in `Source/GAME_CORE/Public/HitReactionComponent.h`: cumulative
   `CurrentStagger` against `MediumStaggerThreshold = 30` and `HeavyStaggerThreshold = 60`,
   decaying at `StaggerDecayRate = 15`/s, with `DetermineStaggerIntensity()` picking
   Light/Medium/Heavy. Hyper-armor means: during a heavy attack's active frames, **Light**
   reactions don't play — but stagger still accumulates, so sustained pressure punches a
   Medium through the armor. Armor stops the flinch, not the poise damage.

2. Add to `HitReactionComponent.h`:

   ```cpp
   UFUNCTION(BlueprintCallable, Category = "HitReaction")
   void SetHyperArmor(bool bActive) { bHyperArmorActive = bActive; }
   // private:
   bool bHyperArmorActive = false;
   ```

   In `PlayHitReaction` (`Private/HitReactionComponent.cpp`), after intensity is determined
   and stagger accumulated, before any montage plays:

   ```cpp
   if (bHyperArmorActive && Intensity == EStaggerIntensity::Light)
       return;  // armor through it — damage and stagger already applied upstream
   ```

   (Keep the `OnHitReactionTriggered` broadcast above this line — `PlayerProfileComponent`
   still needs to see the hit.)

3. Drive the flag from an anim notify state: create `ANS_HyperArmor` mirroring
   `ANS_DealDamage` exactly — `NotifyBegin` finds the owner's `UHitReactionComponent` via
   `FindComponentByClass` and calls `SetHyperArmor(true)`; `NotifyEnd` clears it. Operate on
   the owner component, never on notify-state members — the same UE5 reliability constraint
   that shaped `ANS_DealDamage`. Also clear the flag in
   `HitReactionComponent::ResetForNewRound` so an interrupted attack can't leave armor stuck on.

4. Place it: open the heavy attack montage, right-click the Notify track -> Add Notify
   State -> ANS_HyperArmor, drag its ends to cover the active frames (roughly the
   `ANS_DealDamage` window plus a few frames either side). Rebuild, then verify in PIE:
   light spam during the boss's heavy swing should neither flinch it nor save you.

**4.6 — Fallback brain (no-Python mode).**
- A minimal scripted policy inside `BossActionComponent` (distance-banded: far→Approach,
  mid→mix, near→Attack with cooldown; Dodge on incoming attack with x% chance). Activate
  on bridge disconnect or timeout. Also serves as your baseline to A/B against the RL boss —
  if the RL boss doesn't *feel* better than this 30-line policy, the feel work isn't done.

**Step by step:**

1. Detection uses the real bridge API in `Source/GAME_CORE/Public/RLBridgeComponent.h`:
   `URLBridgeComponent::IsClientConnected()` (BlueprintPure — checks
   `ClientSocket->GetConnectionState() == SCS_Connected`). The bridge lives on BP_Boss, same
   owner as BossActionComponent, so cache it in `BeginPlay` (Phase 0.3 already added the
   override): `Bridge = GetOwner()->FindComponentByClass<URLBridgeComponent>();`
   stored as `TWeakObjectPtr<URLBridgeComponent> Bridge;`.

2. A connected-but-silent Python process (hung script, breakpoint) also needs covering, so
   pair the socket check with a timeout. Add members:

   ```cpp
   UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Fallback")
   float FallbackTimeout = 1.5f;   // ~22 missed decisions at 15 Hz
   // private:
   double LastBridgeActionTime = 0.0;
   double NextFallbackDecisionTime = 0.0;
   double LastFallbackAttackTime = -10.0;
   ```

   Set `LastBridgeActionTime = GetWorld()->GetTimeSeconds();` at the top of
   `ExecuteAction(int32)` — that's the bridge's entry point (the BP binds
   `OnRLActionReceived` to it), and the fallback calls `ExecuteActionEnum` directly so it
   never refreshes its own watchdog.

3. The policy itself, in `BossActionComponent.cpp` (include `CombatComponent.h` —
   `UCombatComponent::IsAttacking()` is real and BlueprintPure):

   ```cpp
   void UBossActionComponent::TickFallbackBrain()
   {
       const double Now = GetWorld()->GetTimeSeconds();
       if (bIsDead || bIsPerformingAction || Now < NextFallbackDecisionTime || !TargetActor)
           return;
       NextFallbackDecisionTime = Now + 0.25;  // ~4 Hz scripted cadence

       const float Dist = FVector::Dist2D(GetOwner()->GetActorLocation(),
                                          TargetActor->GetActorLocation());

       // Reactive: chance to dodge an incoming swing at close range
       if (UCombatComponent* HeroCombat = TargetActor->FindComponentByClass<UCombatComponent>())
           if (HeroCombat->IsAttacking() && Dist < 300.f && FMath::FRand() < 0.35f)
           {
               ExecuteActionEnum(EBossAction::Dodge);
               return;
           }

       if (Dist > 600.f)
           ExecuteActionEnum(EBossAction::Approach);
       else if (Dist > 250.f)
           ExecuteActionEnum(FMath::FRand() < 0.7f ? EBossAction::Approach : EBossAction::Retreat);
       else if (Now - LastFallbackAttackTime > 2.0)
       {
           LastFallbackAttackTime = Now;
           ExecuteActionEnum(EBossAction::Attack);
       }
       else
           ExecuteActionEnum(FMath::FRand() < 0.5f ? EBossAction::Block : EBossAction::Retreat);
   }
   ```

4. Trigger it at the end of `TickComponent`:

   ```cpp
   const bool bBridgeAlive = Bridge.IsValid() && Bridge->IsClientConnected()
       && (GetWorld()->GetTimeSeconds() - LastBridgeActionTime) < FallbackTimeout;
   if (!bBridgeAlive)
       TickFallbackBrain();
   ```

   Because the fallback routes through `ExecuteActionEnum`, every Phase 4 gate — commitment,
   hysteresis, mask, recovery, telegraphs — applies to it for free. That's why it goes
   through the front door.

5. Test the seam: start a fight with `infer.py` running, kill the Python process mid-combo
   (Task Manager or Ctrl+C), and watch for a stall longer than `FallbackTimeout`. Then run
   a fight with Python never started — this scripted boss is your A/B baseline.

**4.7 — Optional: decision cadence tuning.**
- After 4.1–4.3, the boss already looks deliberate. If decisions still feel laggy
  (e.g., dodge arrives too late to matter), raise the bridge rate for *decision sampling*
  but keep execution-layer commitment — the policy decides often, the body commits.
  Don't raise the rate before the commitment layer exists or you'll amplify twitchiness.

**Step by step:**

1. The cadence lives in two places that must move together:
   - **C++**: `URLBridgeComponent::TickRate` (`UPROPERTY`, default 15, clamped 1–60). In the
     editor: open BP_Boss -> Components panel -> select RLBridgeComponent -> Details panel ->
     RLBridge -> **Tick Rate**.
   - **Python**: `env.step_delay: 0.066` in `D:\GAME_CORE\Python\config.yaml` (the
     `BossEnv.__init__` default `step_delay=0.066` mirrors it — the `time.sleep` in
     `BossEnv.step` between sending the action and requesting the next observation).

2. To go to 30 Hz decisions: Tick Rate = 30 on the component, `step_delay: 0.033` in
   config.yaml. The commitment layer (4.1) means the boss's *body* still acts at a humane
   rate — only the sampling is denser, which is exactly what makes reactive dodges arrive
   in time.

3. Two warnings, both load-bearing. First: do not touch this before 4.1–4.3 are in — at
   30 Hz an ungated boss flip-flops twice as fast. Second: cadence is part of the
   environment dynamics; a policy trained at 15 Hz will behave differently when sampled at
   30 Hz (every transition it learned spans half the wall-clock time it expects). Plan a
   retrain after changing it, and re-check frame cost in Unreal Insights — the Phase 0.2
   bridge audit assumed 15 Hz.

**Feels right when:** an observer can't tell the boss is RL-driven — it strafes with intent,
telegraphs, commits to attacks, gets punished in recovery — and killing Python mid-fight
swaps to the fallback brain without a visible seam.

---

## Phase 5 — Camera (gameplay camera, not cinematics)

GoW's camera is a gameplay system. Budget real time here; a bad camera makes great combat feel bad.

**5.1 — Combat camera basics.**
- Over-shoulder offset (GoW) or mid-distance follow (Valhalla) — pick one and commit.
- Spring-arm lag: positional lag ~5–10, rotational lag slightly lower. Zero lag feels
  robotic; too much feels drunk.
- Camera collision that *predicts* (probe size, smooth correction) — never snap through walls.

**Step by step:**

1. Open BP_NeuralHero (Content Browser -> Content/Blueprints/BP_NeuralHero, double-click)
   and select the **SpringArm** component in the Components panel. All settings below are in
   its Details panel. (Property display names are stable from UE 5.4 through 5.6 and should
   match in 5.7.)

2. Under the **Lag** category, set:

   | Property | Value | Note |
   |---|---|---|
   | Enable Camera Lag | checked | positional lag |
   | Camera Lag Speed | 9.0 | interp speed — *higher = less lag*; tune within 8–10 |
   | Enable Camera Rotation Lag | checked | |
   | Camera Rotation Lag Speed | 10.0 | slightly snappier than position, per the rule above |
   | Camera Lag Max Distance | 75.0 | clamp 50–100 so fast pivots never leave the pawn behind |

   If you see lag jitter at uneven frame times, also enable **Use Camera Lag Substepping**
   (same category) and leave **Camera Lag Max Time Step** at its default.

3. Under the **Camera Collision** category: **Do Collision Test** = checked, **Probe Size**
   = 12.0, **Probe Channel** = Camera (default). The spring arm's probe is reactive, not
   truly predictive — the "prediction" you can buy cheaply is the lag itself smoothing the
   correction plus a probe fat enough (12 vs the default 12 is already reasonable; go up to
   16 if you see near-wall clipping) that it starts correcting before the lens touches
   geometry. If the arena has thin pillars that cause pops, fix the arena's camera-channel
   collision before fighting the spring arm.

4. Framing — pick one and commit, under the **Camera** category on the SpringArm:
   - **Mid-distance follow (Valhalla — recommended here**, one large boss is easier to keep
     framed at distance**)**: Target Arm Length = 400, Socket Offset = (0, 40, 20),
     Target Offset = (0, 0, 40).
   - **Over-shoulder (GoW)**: Target Arm Length = 220, Socket Offset = (0, 55, 15),
     Target Offset = (0, 0, 40).

   Socket Offset displaces the camera end of the arm in its local space (Y = sideways, the
   over-shoulder ingredient); Target Offset moves the pivot on the pawn (Z = 40 raises it
   to chest height so the camera orbits the torso, not the feet).

5. Select the **Camera** component (child of the SpringArm) -> Details panel -> **Camera
   Settings** category -> **Field of View** = 90.0.

6. FOV changes at runtime are a lerp, not a set. Sprint widen (+5°) and the boss-close widen
   from 5.2 both use the same line, in the pawn's Tick (C++ or the BP equivalent with an
   FInterpTo node):

   ```cpp
   Camera->SetFieldOfView(FMath::FInterpTo(Camera->FieldOfView, TargetFOV, DeltaTime, 4.f));
   ```

   Per Phase 8.1, park `TargetFOV` sources and all the numbers above somewhere tunable —
   these are exactly the values you'll iterate on in 20-minute loops.

**5.2 — Lock-on / framing.**
- Soft framing mode for the boss fight: bias the camera to keep both fighters on screen,
  with a hard lock-on toggle as an option. Rules: never wrestle the player's stick —
  bias, don't override; cap correction speed.
- FOV: slight widen when the boss closes distance (keeps it framed), slight sprint FOV boost.

**Step by step:**

1. Add the toggle input: in the Content Browser, right-click -> Input -> Input Action,
   name it `IA_LockOn`. Add it to the hero's existing Input Mapping Context (the one that
   already maps `IA_Move`) with a binding (gamepad right-stick click is the genre
   convention). Bind its Triggered event in BP_NeuralHero to flip a `bLockedOn` bool.

2. Target scoring — with one boss this is trivially "the boss," but build the function now
   so adds don't break the camera later. Score every candidate in front of the camera and
   pick the max:

   ```cpp
   // Angle from camera forward dominates; distance breaks ties.
   const float AngleScore = 1.f - (AngleToCandidateDeg / 90.f);   // <0 = behind, reject
   const float DistScore  = 1.f - FMath::Clamp(Dist / 2000.f, 0.f, 1.f);
   const float Score = AngleScore * 0.7f + DistScore * 0.3f;
   ```

3. Drive the controller rotation, capped, in a small `ULockOnComponent` on BP_NeuralHero
   (or the pawn's Tick):

   ```cpp
   const FVector ToTarget = Target->GetActorLocation() - Camera->GetComponentLocation();
   FRotator Desired = ToTarget.Rotation();
   Desired.Pitch = FMath::Clamp(Desired.Pitch - 10.f, -35.f, 10.f);  // frame slightly above the boss's root

   const float InterpSpeed = LockOnInterpSpeed * (1.f - FMath::Clamp(LookInputMagnitude, 0.f, 1.f));
   PC->SetControlRotation(FMath::RInterpTo(PC->GetControlRotation(), Desired, DeltaTime, InterpSpeed));
   ```

   `LockOnInterpSpeed` = 6.0, tune 5–8. The `(1 - LookInputMagnitude)` factor is the
   "bias, don't override" rule made literal: the moment the player touches the look stick,
   the correction yields. In hard lock-on mode, drop that factor and let the stick switch
   targets instead of aiming. Cache `LookInputMagnitude` from the look Input Action the
   same way `SetMovementInput` already pushes `IA_Move` — Mover pawns give you nothing for
   free here (see the Mover gotchas in CLAUDE.md).

4. Soft framing without lock-on: run the same correction at a much lower interp speed
   (1.5–2.0) whenever the boss is alive and within ~1500 cm — enough to drift the boss
   toward frame, never enough to fight the stick.

5. FOV widen when the boss closes: map boss distance to the 5.1 `TargetFOV` — 90 base,
   ramping to 96 as distance drops below 300 cm; sprint adds +5 on top. One `FInterpTo`
   (speed 4) handles all sources; just compute the max requested FOV per frame.

**5.3 — The off-screen attack rule.**
- AAA standard: enemies don't land hits from off-screen without warning. With one boss and
  decent framing this is mostly solved by 5.2, but add the guard anyway: if the boss attacks
  while outside the view frustum, require an audio telegraph and slightly longer wind-up.
  This can live in the Phase 4 execution layer.

**Step by step:**

1. The check is one engine call: `AActor::WasRecentlyRendered(float Tolerance = 0.2f)`.
   It keys off the actor's last render time, so both frustum culling *and* occlusion count
   as "unseen" — a boss winding up behind a pillar gets the same courtesy, which is what
   you want. (PIE caveat: any editor viewport rendering the boss counts, so test this in a
   single-viewport PIE window or standalone.) If you ever need strict frustum-only logic,
   the alternative is `PlayerController->ProjectWorldLocationToScreen()` plus a
   viewport-bounds check — skip it unless `WasRecentlyRendered` misbehaves.

2. Wire it into the Phase 4.4 telegraph in `UBossActionComponent::DoAttack`
   (`Source/GAME_CORE/Private/BossActionComponent.cpp`), where the wind-up rate is set:

   ```cpp
   const bool bOffScreen = !GetOwner()->WasRecentlyRendered(0.2f);
   const float WindupRate = bOffScreen ? 0.45f : 0.6f;   // longer telegraph when unseen
   AnimInstance->Montage_SetPlayRate(AttackMontage, WindupRate);
   ```

3. The audio half is already mandatory because the Play Sound notify from 4.4 sits at
   wind-up start on the montage itself — it fires whether or not the boss is rendered. Make
   it carry: open the telegraph cue's attenuation settings and confirm it's clearly audible
   at arena scale, or, for an unmissable warning, additionally fire
   `UGameplayStatics::PlaySound2D` from `DoAttack` when `bOffScreen` is true (2D = no
   spatialization, cannot be missed).

4. Verify the contract: stand still, deliberately point the camera away from the boss, and
   let it attack. You should hear the cue and have visibly more time to react when you whip
   the camera back. If you're getting hit before you can turn, lengthen the off-screen
   wind-up (drop 0.45 toward 0.35) rather than touching the on-screen rate.

**Feels right when:** you stop thinking about the camera entirely for a full fight.

---

## Phase 6 — Physicality: reactions, death, and contact

**6.1 — Reaction variety and interrupt rules.**
- Directional reactions exist. Add a second tier: light flinch (additive or upper-body slot —
  doesn't interrupt movement) vs. heavy stagger (full-body, current behavior). Light hits on
  a moving target playing full-body flinches makes combat feel like ping-pong.
- Each intensity/direction pair needs its own montage asset — known constraint, since
  `PlayHitReaction` mutates the asset.

**Step by step:**

1. **Create the upper-body slot.** Open any animation asset for the target skeleton (or the
   AnimBP) -> **Window -> Anim Slot Manager** -> Add Slot Group `UpperBody` -> Add Slot
   `UpperBody.Hit`. Slots live on the Skeleton asset, so do this once per skeleton — hero
   and boss each.
2. **Branch the AnimGraph.** In each pawn's AnimBP, montages currently play through the
   full-body `DefaultGroup.DefaultSlot` node. After it, add a **Layered blend per bone**
   node: Base Pose = the existing chain; Blend Pose 0 = a new **Slot 'UpperBody.Hit'** node.
   In the Layered blend's Details -> Layer Setup -> Branch Filters -> Bone Name = `spine_01`,
   Blend Depth = 2. Result: any montage playing in `UpperBody.Hit` moves spine-up only —
   the legs keep walking.
3. **Author the light flinches as upper-body montages.** Duplicate each Light directional
   montage (unique assets per the mutation rule — `PlayHitReaction` writes blend values onto
   the asset it plays) and set its slot: open the montage, click the slot name on the
   montage track header, pick `UpperBody.Hit`.
4. **The C++ branch already exists.** `HitReactionComponent::PlayHitReaction` picks the
   montage set via `DetermineStaggerIntensity()` -> `GetReactionSet()` — Light maps to the
   `LightHitReactions` struct on the component. Assigning the new upper-body montages there
   (select HitReactionComponent -> Details -> HitReaction -> Light Hit Reactions, four
   direction slots) is the whole change; the montage carries its own slot, so the play code
   is untouched.
5. **Boss design choice while you're here:** Light flinches arguably shouldn't set the
   boss's `bIsReacting` lockout at all — the boss keeps acting through light taps (pairs
   with Phase 4.5 hyper-armor; light hits still feed `CurrentStagger`, so pressure still
   pays off in a Medium). If you take it: in `PlayHitReaction`, skip the `bIsReacting = true`
   path for `EStaggerIntensity::Light` on the boss. Keep the full lockout for Medium/Heavy.
6. **Verify:** mash lights at the boss mid-walk — torso flinches, feet keep planting, no
   ping-pong; a Medium threshold break still stops it cold.

**6.2 — Death with weight.**
- Replace or augment the death montage with **physical-animation blend → ragdoll**: simulate
  below the spine on death, blend in the impulse from the killing blow's direction.
  Montage-only deaths look canned by the fifth kill; impulse-driven deaths never repeat.

**Step by step:**

1. **Check the physics asset.** In the Content Browser, find the boss's skeletal mesh — its
   Physics Asset sits alongside it (or via the mesh's Details -> Physics Asset). If there
   isn't one: right-click the skeletal mesh -> Create -> Physics Asset, accept defaults.
   Open it (this is PhAT) and confirm bodies exist for pelvis, spine, and limbs.
2. **Know where death happens today.** `CombatComponent::ApplyDamage` sets `bIsDead` and
   broadcasts `OnHealthDepleted`; the BP binds that to `BossActionComponent::HandleDeath`
   (plays `DeathMontage`, broadcasts `OnBossDied`); the BP then delays and calls
   `ResetForNewRound()`. Keep all of it — the ragdoll replaces the *tail* of the death
   montage, not the system.
3. **Ragdoll in the BP death handler**, after `HandleDeath`: **Delay 0.4–0.7 s** (let the
   montage sell the hit first), then on the boss's mesh component:
   - **Set Collision Profile Name** = `Ragdoll`
   - **Set All Bodies Below Simulate Physics** (In Bone Name = `spine_01`, New Simulate = true)
   - **Set All Bodies Below Physics Blend Weight** (`spine_01`, 1.0) — or drive 0 -> 1 with a
     0.3 s Timeline for a blend instead of a pop
   - **Add Impulse** (Impulse = `LastHitDirection` × 400, Bone Name = `spine_02`,
     Vel Change = true)
4. **`LastHitDirection` comes from Phase 3.5 step 2** (the `ApplyDamage` instigator
   extension caches it). Make it `BlueprintReadOnly` so the BP impulse node can read it.
   With **Vel Change = true** the impulse is mass-independent: 300–500 reads as a shove,
   800+ as a launch — scale by the killing attack's `KnockbackImpulse` if you want finishers
   to send the boss flying.
5. **Un-ragdoll on reset — the classic trap.** Before the respawn step of the round-reset
   flow: **Set All Bodies Simulate Physics** = false, **Set Collision Profile Name** back to
   the original (check what the mesh uses today — typically `CharacterMesh`), and re-attach
   + restore the mesh's relative transform (cache the spawn-time relative location/rotation
   in BeginPlay; a simulated mesh drifts from its actor). Skip this and round 2 starts with
   the boss's mesh lying 3 m from its capsule.
6. **Same recipe works for the hero's death** — bind it to the hero CombatComponent's
   `OnHealthDepleted` the same way.

**6.3 — Knockback and spacing.**
- Heavy hits push the target (root-motion or Mover impulse — verify which plays nicely with
  Mover pawns; test early, this is exactly the kind of thing Mover handles differently).
  Knockback resets spacing and gives both fighters' animations room to read.

**Step by step:**

1. **The honest constraint:** Mover pawns have no `LaunchCharacter`. Two routes, in order:
   - **Root-motion knockback (safe — do this first).** `HitReactionComponent` already has a
     `KnockbackMontage` property reserved for heavy combo finishers (Details ->
     HitReaction). Author or retarget a knockback-stumble animation *with root motion* and
     assign it — Mover integrates the displacement exactly like attack root motion, no new
     code path. Displacement is whatever the anim authors (aim for 2.5–4 m).
   - **Mover impulse APIs.** The Mover plugin ships instant movement effects (apply-velocity
     style) queued on the Mover component — the API names shifted across 5.x versions, so
     check the plugin source / MoverExamples for the 5.7 form (verify in your build). Budget
     a one-hour test before relying on it; if the root-motion route already feels right,
     skip this entirely.
2. **Wire the trigger.** In `PlayHitReaction`, when intensity is Heavy *and* the hit is a
   finisher (the `DamageType` from `FAttackAnimData` distinguishes — e.g., set finishers to
   `Heavy`), play `KnockbackMontage` instead of the directional heavy reaction.
3. **Why it matters:** knockback resets spacing to ~3–4 m — both fighters' animations get
   room to read, and the boss's recovery window (Phase 4.5) plus the knockback distance is
   what creates the punish-reset-reengage rhythm GoW fights breathe with.

**Feels right when:** mashing lights doesn't stun-lock anyone into a flinch loop, and every
death looks slightly different.

---

## Phase 7 — Audio + UI feedback (the cheap 30 % of game feel)

Not visuals — feedback channels. Both are disproportionately high-leverage.

**7.1 — Combat audio via anim notifies:** whoosh on swing start, layered impact on hit
(material + weight tiers), distinct parry *ting*, boss vocal grunt on telegraph wind-ups
(doubles as the off-screen warning from 5.3). Even placeholder sounds from a free pack
move feel dramatically; silent combat reads as broken no matter the animation quality.

**Step by step:**

1. **Whooshes ride the montages.** Open each attack montage -> Notifies track -> right-click
   -> Add Notify -> **Play Sound**. Select the notify; in the Details panel set **Sound** to
   the whoosh cue, **Attach Name** to the weapon socket (`hand_r` if there's no weapon
   socket), **Follow** = checked. Place at swing start. On boss attacks, this is the same
   notify Phase 4.4 placed at wind-up start — one notify serves telegraph and whoosh.
2. **Impacts do NOT ride the montages** — they come from the hit path, so whiffs stay
   silent. The right hook is `ANS_DealDamage::NotifyTick`, in the block where
   `TriggerHitFeedback` already fires after a confirmed hit. Cleanest version: add a
   `UPROPERTY(EditAnywhere) TObjectPtr<USoundBase> ImpactSound;` to `HitFeedbackComponent`
   and play it inside `TriggerHitFeedback` via
   `UGameplayStatics::PlaySoundAtLocation(GetWorld(), ImpactSound, GetOwner()->GetActorLocation());`
   — it then inherits the per-attack weight scaling from Phase 3.4 for free (louder/lower
   variant in `TriggerHeavyHitFeedback`). Layer two waves per impact — a body thud plus a
   material ring — for cheap perceived weight.
3. **MetaSounds quick start** (for the layered impact): Content Browser right-click ->
   Audio -> **MetaSound Source**. In the graph: two **Wave Player** nodes -> a mix to the
   output; add a **Random (Float)** node into a pitch-shift input (±2 semitones) so two
   hundred hits don't sound like a sample loop. Plain Sound Cues still work if MetaSounds
   feels like overkill today — the random-pitch trick is the part that matters.
4. **The parry *ting*** is a reward sound: brighter and longer-tailed than the block thud,
   and unmissable — fire it with `PlaySound2D` from the Phase 3.5 parry branch (2D = no
   spatialization, never lost in the mix).
5. **Free sources:** Freesound (filter license = CC0), the Sonniss GDC Game Audio bundles
   (free, enormous), Kenney's audio packs (CC0). Do the placeholder pass *now* — silent
   combat reads as broken; placeholder combat just reads as unfinished. Different leagues.

**7.2 — UI:** boss health + a visible **stagger/poise bar** (the data already exists in
`HitReactionComponent` — exposing it turns stagger into a strategy), damage direction
indicator on the player, unblockable-attack indicator (4.4). Keep the existing health UI;
add hit-confirm flashes on the boss bar.

**Step by step:**

1. **Boss status widget.** Content Browser right-click -> User Interface -> **Widget
   Blueprint** -> `WBP_BossStatus`: two ProgressBars (HP, stagger/poise).
2. **The stagger data is already exposed:** `HitReactionComponent::GetCurrentStagger()`
   (BlueprintPure) and `HeavyStaggerThreshold` (BlueprintReadWrite, default 60). Bar
   percent = `GetCurrentStagger() / HeavyStaggerThreshold`. Stagger decays continuously
   (`StaggerDecayRate = 15`/s), so bind this one in the widget's Tick — the rare case where
   a tick binding is honest, since a delegate would have to fire every frame anyway.
3. **HP** binds to `CurrentHealth / MaxHealth` on the boss's CombatComponent, same pattern
   as the existing health UI.
4. **Hit-confirm flash:** bind the *hero* CombatComponent's `OnAttackLanded`
   (BlueprintAssignable; fires once per landed swing with damage + type — broadcast from
   `ANS_DealDamage` on confirmed hits only, so it can't lie) -> flash the boss bar's border
   for 0.1 s. Free with the existing delegate.
5. **Damage direction on the player:** bind the hero HitReactionComponent's
   `OnHitReactionTriggered` (carries `InstigatorActor`) -> compute the angle of
   (instigator location − player location) against camera yaw -> rotate a single radial
   flash Image widget to that angle. One image is enough at this scope.
6. **Unblockable telegraph:** Add Component -> **Widget** on BP_Boss (Space = Screen,
   positioned above the head) containing the rune-flash image, hidden by default. Toggle it
   from a Blueprint AnimNotify (Content Browser right-click -> Blueprint Class -> parent
   **AnimNotify**, override `Received_Notify`, set the widget visible/hidden) placed over
   the unblockable attack's wind-up frames.
7. **Keep the UI at the indie bar:** bars, flashes, one direction indicator — no floating
   damage numbers. They fight the silhouette readability the visuals.md art-direction
   section is building.

---

## Phase 8 — Tuning infrastructure and the iteration loop

AAA feel is 20 % systems, 80 % iteration. Optimize iteration speed itself.

**8.1 — Everything tunable without rebuilds.**
- Move every magic number this guide introduced into `CombatAnimConfig` / new data assets or
  `UDeveloperSettings`-backed CVars: hit-stop durations, cancel-window timings, warp clamps,
  boss commitment durations, recovery times, camera lag. The Live Coding limitations make
  data-driven tuning mandatory, not nice-to-have — a rebuild per tweak kills iteration.

**Step by step:**

1. **Audit where every number now lives.** If the earlier phases were followed, the map is:

   | Home | What lives there | Edited where |
   |---|---|---|
   | `FAttackAnimData` / `UCombatAnimConfig` | blend times, play rates, damage, hit stop, shake scale, knockback | the four data assets in the Content Browser |
   | Component `UPROPERTY`s | boss commitment/mask/fallback (BossActionComponent), stagger thresholds + grace (HitReactionComponent), global feedback defaults (HitFeedbackComponent), buffer/warp/block/parry (CombatComponent), camera lag/probe/offsets (SpringArm) | Details panel on the BPs |
   | `UDeveloperSettings` (below) | cross-cutting feel numbers owned by no single component | Project Settings -> Game |
   | CVars (below) | live-tuning and debug toggles | the console, mid-fight |

   Anything still hardcoded in a `.cpp` gets moved the first time you want to change it twice.
2. **`UDeveloperSettings` for the cross-cutting numbers.** Tools -> New C++ Class -> All
   Classes -> **DeveloperSettings** -> `GameFeelSettings`:

   ```cpp
   UCLASS(Config = Game, DefaultConfig, meta = (DisplayName = "Game Feel"))
   class GAME_CORE_API UGameFeelSettings : public UDeveloperSettings
   {
       GENERATED_BODY()
   public:
       UPROPERTY(EditAnywhere, Config, Category = "Camera")
       float LockOnInterpSpeed = 6.0f;

       UPROPERTY(EditAnywhere, Config, Category = "Camera")
       float SprintFOVBoost = 5.0f;
   };
   ```

   It appears at **Edit -> Project Settings -> Game -> Game Feel** automatically, persists
   to `Config/DefaultGame.ini`, and reads anywhere as
   `GetDefault<UGameFeelSettings>()->LockOnInterpSpeed`.
3. **A CVar for live A/B mid-fight:**

   ```cpp
   static float GComboWindowBonus = 0.0f;
   static FAutoConsoleVariableRef CVarComboWindowBonus(
       TEXT("combat.ComboWindowBonus"), GComboWindowBonus,
       TEXT("Seconds added to the combo window at runtime, for live tuning."));
   ```

   File-scope in the relevant `.cpp`; type `combat.ComboWindowBonus 0.2` in the console with
   the fight still running. CVars beat editor properties exactly when you want to compare
   two values inside one session.
4. **The rule:** rebuilding to change a number is a workflow bug. If you typed a constant
   into a `.cpp` this week, move it before Phase 8.4's loops begin.

**8.2 — Feel-debug HUD.**
- A debug overlay (console-toggled): current boss action + commitment state + mask result,
  player buffered inputs, active cancel/i-frame windows, frame time. You cannot tune
  invisible windows.

**Step by step:**

1. **One toggle CVar** (file-scope in `BossActionComponent.cpp`):

   ```cpp
   static TAutoConsoleVariable<int32> CVarFeelDebug(
       TEXT("combat.DebugHUD"), 0, TEXT("1 = combat feel debug overlay"));
   ```

2. **Boss lines in `TickComponent`** — fixed message keys so lines update in place instead
   of scrolling:

   ```cpp
   if (GEngine && CVarFeelDebug.GetValueOnGameThread() > 0)
   {
       const double Now = GetWorld()->GetTimeSeconds();
       GEngine->AddOnScreenDebugMessage(101, 0.f, FColor::Yellow, FString::Printf(
           TEXT("Boss action: %s  commit: %.2fs  lockout: %.2fs"),
           *UEnum::GetValueAsString(CurrentAction),
           FMath::Max(0.0, (ActionStartTime + CurrentMinDuration) - Now),
           FMath::Max(0.0, ActionLockoutUntil - Now)));
       // second line: IsReacting() + GetCurrentStagger() from the cached HitReactionComponent
   }
   ```

   (Key = 101, duration = 0 -> repainted every frame, one stable line per key.)
3. **Player lines in `CombatComponent::TickComponent`** (give it a tick, or piggyback on an
   existing per-frame path): buffered action type + age, `IsCancelWindowOpen()`,
   dodge-i-frame state, `GetComboStep()`. Keys 111, 112, ...
4. **World-space alternative:** `DrawDebugString(GetWorld(), Location, Text, nullptr,
   FColor::White, 0.f)` floats the same info above heads — better when recording clips to
   review (Phase 8.4), since the state sits next to the body doing it.
5. **Why this is non-optional:** when a cancel "feels late," the overlay answers in one
   glance whether the window was even open, whether the press buffered, or whether the boss
   was inside its commitment — three different fixes, indistinguishable without the HUD.

**8.3 — Use the telemetry you already built.**
- `EmotionEstimationComponent` (frustration/flow/boredom) and `PlayerProfileComponent` are
  playtesting instruments most studios don't have. Log them per session; after balance
  changes, compare flow-state duration across builds. Pair with the constrained-learning
  win-rate cap to converge on "challenging but fair" with data instead of vibes.

**Step by step:**

1. **What exists, by name.** `UEmotionEstimationComponent` produces an `FEmotionEstimate`
   (`FrustrationScore` / `FlowScore` / `BoredomScore` + `DominantState`) with an
   `OnEmotionEstimateUpdated` delegate, and records `FEncounterOutcome` rows (`bBossWon`,
   `DurationSeconds`, `HeroHPAtEnd`, `BossHPAtEnd`). `UPlayerProfileComponent` maintains the
   8 EMA dims (`AggressionScore`, `DodgeTendency`, `BlockTendency`, `OpenerAggression`,
   `PressureResponse`, `KitingScore`, `ComboCompletionRate`, `PositionalVariance`).
2. **Cheapest pipeline — log Python-side.** All of it already flows over the bridge in the
   observation JSON. In `Python/infer.py`'s loop, append one CSV row per round (outcome,
   duration, the emotion triple, the profile vector) with `csv.writer` — ~10 lines, zero
   C++ rebuilds, and the data lands next to the training logs where you'll analyze it.
3. **C++ alternative** if you want logs without Python attached: bind
   `OnEmotionEstimateUpdated` + the death delegates (`OnBossDied`, hero `OnHealthDepleted`)
   in the level BP or a small subsystem and append lines via
   `FFileHelper::SaveStringToFile(Line, *Path, ..., FILEWRITE_Append)` to
   `Saved/Telemetry/feel_log.csv`.
4. **How to actually use it:** after each tuning change, compare medians over ≥10 rounds —
   flow share up and frustration spikes shorter means keep the change. The constrained-
   learning win-rate cap already steers difficulty; this telemetry tells you whether *feel*
   changes move *emotion*, which vibes alone cannot.

**8.4 — The playtest cadence.**
- Tune in 20-minute loops: change one variable → fight the boss twice → decide. Bring in
  fresh hands weekly; you are calibrated to your own jank. Ask only two questions:
  "did anything feel unfair?" and "did anything feel unresponsive?" — those answers map
  directly to Phase 4.4/4.5 and Phase 1/3.2 respectively.

**Step by step:**

1. **The loop, literally:** change ONE value (8.1 made that a Details-panel or console edit,
   not a rebuild) -> fight twice -> keep or revert -> note it. Twenty minutes. The 8.2
   overlay exists so diagnosing takes one glance, not one more fight.
2. **Fresh hands weekly,** two questions only: "anything unfair?" (-> telegraphs 4.4,
   recovery 4.5), "anything unresponsive?" (-> buffering Phase 1, cancel windows 3.2).
   Resist explaining the boss before they play; the boss must explain itself.
3. **Record fights** (Win+G game bar is plenty) and rewatch at 0.5× — off-by-three-frames
   cancel windows and double flinches hide in live play and jump out on replay.
4. **Keep a tuning journal:** one line per change — date, value before -> after, verdict.
   Three weeks in, that file is the difference between a tuned game and a lost one.

---

## Suggested order of attack (summary)

| # | Work | Phases | Why this order |
|---|---|---|---|
| 1 | Frame rate, bridge audit, disconnect fallback | 0, 4.6 | Everything reads through frame pacing; fallback unblocks all testing |
| 2 | Input buffering everywhere + dodge responsiveness | 1 | Cheapest, largest feel win |
| 3 | Boss execution layer (commit, hysteresis, mask, recovery) | 4.1–4.5 | The project's signature problem; transforms the boss |
| 4 | Player cancel windows + weight scaling + i-frames | 3 | Builds on buffering; defines the combat identity |
| 5 | Locomotion overhaul (hero first) | 2 | High effort, high visibility |
| 6 | Camera | 5 | Needs final locomotion speeds to tune against |
| 7 | Reactions/ragdoll/knockback + audio/UI | 6, 7 | Polish multipliers on a working core |
| 8 | Tuning passes with telemetry | 8 | Continuous from step 3 onward |

A useful bar for "done": record 60 seconds of a boss fight and watch it muted. If the
fight is readable — telegraphs visible, hits obviously landing, both characters moving
with intent — and you can't spot the moment-to-moment RL decisions, you're at the target.
