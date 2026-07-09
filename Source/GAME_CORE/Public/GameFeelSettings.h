#pragma once

#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"
#include "UObject/SoftObjectPath.h"
#include "GameFeelSettings.generated.h"

/**
 * One row of the settings-driven NNE archetype bank (M5).
 *
 * Persona -> exported per-persona boss policy (UNNEModelData) + the 8-dim
 * behavior centroid that persona represents. The centroid is the MEAN 8-dim
 * FPlayerProfile the persona's policy trained against (measured from
 * replays/<persona>/ — the AutoHero persona's own EMA profile). At boss init,
 * UNNEBossPolicyComponent picks the row whose centroid has the highest COSINE
 * SIMILARITY to the player's stored PlayerMemoryComponent profile, so a
 * returning rushdown player meets the anti-rusher policy from the first swing.
 *
 * Serialized as +NNEArchetypeBank=(...) struct rows in Config/DefaultGame.ini —
 * chosen over a TMap property because UE's config loader handles arrays of
 * structs via the +Element syntax reliably, while TMap-from-DefaultConfig is a
 * single-line ImportText path with fragile merge semantics.
 */
USTRUCT()
struct GAME_CORE_API FNNEArchetypeBankEntry
{
	GENERATED_BODY()

	/** Persona name. By convention matches an M1 AutoHero persona
	 *  (rusher/turtle/kiter/counter/chaotic) and the persona keys used by
	 *  Tools/run_training.ps1 for replays/<persona>/. */
	UPROPERTY(EditAnywhere, Category = "Archetype")
	FName Persona;

	/** The persona's exported policy (Python/export_onnx.py ->
	 *  Tools/import_onnx_model.py). Keep it under /Game/Arena/Models — that
	 *  directory is force-cooked (DirectoriesToAlwaysCook) precisely because
	 *  config-only soft paths are not cook dependencies. */
	UPROPERTY(EditAnywhere, Category = "Archetype", meta = (AllowedClasses = "/Script/NNE.NNEModelData"))
	FSoftObjectPath ModelData;

	/** 8-dim centroid, EXACTLY 8 entries, FPlayerProfile::ToFloatArray() order:
	 *  [AggressionScore, DodgeTendency, BlockTendency, OpenerAggression,
	 *   PressureResponse, KitingScore, ComboCompletionRate, PositionalVariance],
	 *  each in [0,1] (0.5 = neutral). Rows with Num() != 8 are excluded from
	 *  cosine selection (warned at load); their model stays loadable as a
	 *  last-resort bank entry. (TArray<float> because UHT cannot reflect raw
	 *  C arrays — fixed size is enforced by convention + runtime check.) */
	UPROPERTY(EditAnywhere, Category = "Archetype")
	TArray<float> Centroid;
};

/**
 * CONTRACT #2 — all cross-cutting game-feel toggles/numbers live here.
 * Track C owns this file; tracks A and B may READ via GetDefault<UGameFeelSettings>()
 * but must not edit it.
 *
 * Config=Game + DefaultConfig → values persist to Config/DefaultGame.ini and are
 * editable in Project Settings → Game → Game Feel. Everything here is exactly the
 * kind of 20-minute-loop tunable guide.md Phase 8.1 asks to centralize.
 *
 * Camera numbers follow guide.md 5.1/5.2 (mid-distance follow variant: arm 400,
 * socket (0,40,20), target offset (0,0,40), FOV 90 ramping to 96 under 300cm).
 * C++ defaults are the guide.md mid-follow contract (FOV 90 / arm 400); the SHIPPED
 * DefaultConfig in Config/DefaultGame.ini overrides toward the GoW cheat-sheet
 * (BaseFOV=78, arm 320, shoulder Y=55, interp 3) — the ini wins at load, and Project
 * Settings edits persist there. Telegraph colors are the GoW Ragnarok canon: red
 * (#FF2A1A) = unblockable/dodge-only, yellow (#FFC400) = parryable guard-break.
 */
UCLASS(Config = Game, DefaultConfig, meta = (DisplayName = "Game Feel"))
class GAME_CORE_API UGameFeelSettings : public UDeveloperSettings
{
	GENERATED_BODY()

public:
	UGameFeelSettings();

	// --- Feature toggles (read by UGameFeelSubsystem at world begin-play) ---

	/** Self-install UBossStatusHUDComponent on the boss (first Enemy-tagged actor with a BossActionComponent). */
	UPROPERTY(EditAnywhere, Config, Category = "Toggles")
	bool bEnableBossStatusHUD = true;

	/** Self-install UCombatCameraComponent on the player pawn. */
	UPROPERTY(EditAnywhere, Config, Category = "Toggles")
	bool bEnableCombatCamera = true;

	/** M5: self-install UNNEBossPolicyComponent on the boss (in-engine ONNX brain,
	 *  no Python). Safe to leave on for training too — the component self-disables
	 *  under -rlbridge and stands aside while the Python TCP client is connected. */
	UPROPERTY(EditAnywhere, Config, Category = "Toggles")
	bool bEnableNNEBoss = true;

	/** Default UNNEModelData asset the injected NNE boss policy loads when its
	 *  ModelData/ArchetypeBank are unset (the auto-injected component has no BP
	 *  property pass, so this is its wiring point). Empty = component stays
	 *  dormant and the scripted fallback brain covers the boss. */
	UPROPERTY(EditAnywhere, Config, Category = "Toggles", meta = (AllowedClasses = "/Script/NNE.NNEModelData"))
	FSoftObjectPath NNEBossModelData;

	/** M5 archetype bank rows (persona -> per-persona ONNX policy + 8-dim
	 *  behavior centroid). Read by UNNEBossPolicyComponent when its own
	 *  ArchetypeBank UPROPERTY is empty (the auto-injected path always is):
	 *  models are soft-loaded into the bank and centroids feed the
	 *  cosine-similarity match against PlayerMemoryComponent's stored profile.
	 *  Empty, or no usable player profile -> NNEBossModelData default.
	 *  See FNNEArchetypeBankEntry for the centroid contract. */
	UPROPERTY(EditAnywhere, Config, Category = "Toggles|NNE", meta = (TitleProperty = "Persona"))
	TArray<FNNEArchetypeBankEntry> NNEArchetypeBank;

	/** Let UCombatCameraComponent push the guide.md 5.1 defaults onto the hero's
	 *  SpringArm/Camera at BeginPlay (lag 9/10, max lag distance 75, substepping,
	 *  probe 12, collision test, arm 400, socket (0,40,20), target offset (0,0,40),
	 *  FOV = BaseFOV). Untick to keep whatever the BP has authored. */
	UPROPERTY(EditAnywhere, Config, Category = "Toggles")
	bool bApplyCameraDefaults = true;

	/** Overlay the RL-visibility HUD (brain badge, action-mask row, live 8-dim
	 *  player-profile radar, insight-taunt fade). Turns the shipped BossStatusHUD
	 *  into a "how the boss brain sees you" showcase. Read-only reflection of the
	 *  existing components — never modifies combat. Off in shipping (default);
	 *  console `arena.Showcase 1` flips it live. Requires bEnableBossStatusHUD. */
	UPROPERTY(EditAnywhere, Config, Category = "Toggles")
	bool bEnableRLShowcase = false;

	// --- Lock-on / soft framing ---

	/** RInterpTo speed while hard-locked (guide 5.2: 6.0, tune 5-8). LockOnComponent
	 *  uses this unless its bOverrideInterpSpeed is ticked. */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|LockOn", meta = (ClampMin = "0.0"))
	float LockOnInterpSpeed = 6.0f;

	/** RInterpTo speed for soft framing when NOT locked (guide 5.2 step 4: 1.5-2.0 —
	 *  enough to drift the boss toward frame, never enough to fight the stick). */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|LockOn", meta = (ClampMin = "0.0"))
	float SoftFramingInterpSpeed = 1.8f;

	/** Soft framing only engages while the boss is alive and within this range (cm). */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|LockOn", meta = (ClampMin = "0.0"))
	float SoftFramingRange = 1500.0f;

	/** Pitch framing (guide 5.2 step 3): Desired.Pitch = Clamp(RawPitch + Offset, Min, Max)
	 *  — frames slightly above the boss's root. GoW clamps roughly [-30, +20]. */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|LockOn")
	float LockOnPitchOffset = -10.0f;

	UPROPERTY(EditAnywhere, Config, Category = "Camera|LockOn")
	float LockOnPitchMin = -35.0f;

	UPROPERTY(EditAnywhere, Config, Category = "Camera|LockOn")
	float LockOnPitchMax = 10.0f;

	/** Mouse delta (px/frame) that counts as "full" look input for the
	 *  (1 - LookInputMagnitude) yield factor. Gamepad right stick is already 0-1. */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|LockOn", meta = (ClampMin = "0.1"))
	float LookYieldMouseScale = 5.0f;

	/** After the player releases the look input, auto-framing blends back in over this
	 *  many seconds (Nesky rule: player intent wins; resume gently after stick silence). */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|LockOn", meta = (ClampMin = "0.0"))
	float LookYieldRecoverySeconds = 0.75f;

	// --- FOV ---

	/** Horizontal FOV at rest. Contract-pinned 90 (guide 5.1); GoW-class tight would be 74. */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|FOV", meta = (ClampMin = "40.0", ClampMax = "130.0"))
	float BaseFOV = 90.0f;

	/** Degrees added on top of BaseFOV as the boss closes to melee (90 → 96 ramp). */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|FOV", meta = (ClampMin = "0.0"))
	float BossCloseFOVBoost = 6.0f;

	/** Boss distance (cm) below which the close-widen ramp begins (guide 5.2 step 5: 300). */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|FOV", meta = (ClampMin = "1.0"))
	float BossCloseWidenDistance = 300.0f;

	/** FInterpTo speed for all FOV changes (guide: 4; cheat-sheet: never above ~5 or it reads as a zoom cut). */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|FOV", meta = (ClampMin = "0.1"))
	float FOVInterpSpeed = 4.0f;

	// --- Spring arm defaults (applied only when bApplyCameraDefaults) ---

	UPROPERTY(EditAnywhere, Config, Category = "Camera|SpringArm", meta = (ClampMin = "0.0"))
	float CameraLagSpeed = 9.0f;

	UPROPERTY(EditAnywhere, Config, Category = "Camera|SpringArm", meta = (ClampMin = "0.0"))
	float CameraRotationLagSpeed = 10.0f;

	UPROPERTY(EditAnywhere, Config, Category = "Camera|SpringArm", meta = (ClampMin = "0.0"))
	float CameraLagMaxDistance = 75.0f;

	UPROPERTY(EditAnywhere, Config, Category = "Camera|SpringArm", meta = (ClampMin = "0.0"))
	float CameraProbeSize = 12.0f;

	/** Mid-distance follow (guide 5.1 step 4, recommended for one large boss). */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|SpringArm", meta = (ClampMin = "0.0"))
	float TargetArmLength = 400.0f;

	UPROPERTY(EditAnywhere, Config, Category = "Camera|SpringArm")
	FVector CameraSocketOffset = FVector(0.0f, 40.0f, 20.0f);

	UPROPERTY(EditAnywhere, Config, Category = "Camera|SpringArm")
	FVector CameraTargetOffset = FVector(0.0f, 0.0f, 40.0f);

	// --- Exploration camera (Tier 4 overworld) ---
	// Overrides applied when UCombatCameraComponent::SetCameraMode(Exploration) is
	// active. Interps toward these on entry and back to combat values on encounter
	// (BossEncounterVolume overlap). Numbers picked to feel like an open-world
	// third-person walk cam, not a tight combat over-the-shoulder.

	/** Spring-arm length while exploring (cm). Longer than combat's TargetArmLength
	 *  to widen the sightlines for navigation. */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|Exploration", meta = (ClampMin = "0.0"))
	float ExplorationArmLength = 550.0f;

	/** Base FOV while exploring. Slightly wider than combat BaseFOV to sell scale
	 *  when standing on a plateau. */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|Exploration", meta = (ClampMin = "40.0", ClampMax = "130.0"))
	float ExplorationFOV = 85.0f;

	/** Spring-arm lag speed while exploring. Lower (looser) than combat so the
	 *  camera drifts behind the pawn less snappily — reads as "not combat". */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|Exploration", meta = (ClampMin = "0.0"))
	float ExplorationLagSpeed = 6.0f;

	/** FInterpTo speed for the arm-length transition between Combat and Exploration
	 *  modes. Same units as FOVInterpSpeed. */
	UPROPERTY(EditAnywhere, Config, Category = "Camera|Exploration", meta = (ClampMin = "0.1"))
	float ModeArmInterpSpeed = 3.0f;

	// --- Telegraph indicator (GoW color language: red = move, yellow = parryable) ---

	/** Unblockable/heavy telegraph. GoW Ragnarok red ring: #FF2A1A core. */
	UPROPERTY(EditAnywhere, Config, Category = "HUD|Telegraph")
	FLinearColor TelegraphUnblockableColor;

	/** Parryable guard-break telegraph. GoW Ragnarok yellow ring: #FFC400 core. */
	UPROPERTY(EditAnywhere, Config, Category = "HUD|Telegraph")
	FLinearColor TelegraphParryColor;

	/** How long the brief yellow tick shows for non-heavy (parryable) attacks. */
	UPROPERTY(EditAnywhere, Config, Category = "HUD|Telegraph", meta = (ClampMin = "0.05"))
	float TelegraphParryTickSeconds = 0.25f;

	// --- Boss status bar ---

	/** Seconds the white damage chip holds at the old HP value before draining.
	 *  Timer resets on each new hit so combos accumulate one big chip (Elden Ring ≈0.7s). */
	UPROPERTY(EditAnywhere, Config, Category = "HUD|BossBar", meta = (ClampMin = "0.0"))
	float BossBarChipDelay = 0.6f;

	/** Chip drain rate in bar-FRACTION per second after the hold elapses. */
	UPROPERTY(EditAnywhere, Config, Category = "HUD|BossBar", meta = (ClampMin = "0.01"))
	float BossBarChipDrainPerSecond = 0.35f;

	/** Bar width as a fraction of viewport width (Elden Ring boss bar ≈ 0.45). */
	UPROPERTY(EditAnywhere, Config, Category = "HUD|BossBar", meta = (ClampMin = "0.1", ClampMax = "1.0"))
	float BossBarWidthFraction = 0.45f;

	/** Distance (slate units) from the top of the screen to the boss name plate. */
	UPROPERTY(EditAnywhere, Config, Category = "HUD|BossBar", meta = (ClampMin = "0.0"))
	float BossBarTopPadding = 48.0f;

	/** Main HP fill (crimson). */
	UPROPERTY(EditAnywhere, Config, Category = "HUD|BossBar")
	FLinearColor BossBarHealthColor;

	/** Trailing damage-chip fill (white/ghost, fighting-game "provisional damage"). */
	UPROPERTY(EditAnywhere, Config, Category = "HUD|BossBar")
	FLinearColor BossBarChipColor;

	/** Stagger/poise fill under the HP bar (GoW white stun meter). */
	UPROPERTY(EditAnywhere, Config, Category = "HUD|BossBar")
	FLinearColor StaggerBarColor;

	/** Border flash on hero hit-confirm (OnAttackLanded). */
	UPROPERTY(EditAnywhere, Config, Category = "HUD|BossBar")
	FLinearColor HitConfirmFlashColor;

	/** Border flash duration (spec: 0.1s). */
	UPROPERTY(EditAnywhere, Config, Category = "HUD|BossBar", meta = (ClampMin = "0.01"))
	float HitConfirmFlashSeconds = 0.1f;
};
