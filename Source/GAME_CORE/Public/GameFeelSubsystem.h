#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "CombatCameraComponent.h"  // for ECameraMode
#include "GameFeelSubsystem.generated.h"

/**
 * Zero-Blueprint installer for the game-feel layer (Track C). On world
 * begin-play a short retry timer waits for the combatants to exist, then — per
 * the UGameFeelSettings toggles — NewObject+RegisterComponent installs:
 *
 *   - UCombatCameraComponent on the player pawn (GetPlayerPawn(0)),
 *   - UBossStatusHUDComponent on the BOSS: the first Enemy-tagged actor that
 *     also has a UBossActionComponent. Minions carry the Enemy tag too but are
 *     ACharacter patrols without a BossActionComponent, so they never match.
 *
 * Rationale: CombatComponent::BeginPlay is owned by Track B and BP edits are
 * off-limits, so the subsystem is the only insertion point that touches neither.
 * Registered components persist on their actors across round resets (actors are
 * teleported, never destroyed), so installation is one-shot per world.
 */
UCLASS()
class GAME_CORE_API UGameFeelSubsystem : public UWorldSubsystem
{
	GENERATED_BODY()

public:
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;

	/** First Enemy-tagged actor with a UBossActionComponent, or nullptr. Shared
	 *  boss-discovery rule for the camera and the HUD. */
	static AActor* FindBossActor(UWorld* World);

	/** Tier 4 overworld: switch the player's camera between Combat and
	 *  Exploration behaviors. Combat mode is today's tight arm + soft framing +
	 *  boss-close FOV widen; Exploration is a looser arm/FOV and LockOn deactivated.
	 *
	 *  Called from ABossEncounterVolume overlap (Combat on enter, Exploration on
	 *  exit / boss death). Idempotent; smooth arm/FOV interp handled by
	 *  UCombatCameraComponent. Silently no-ops if no player pawn or camera
	 *  component exists (level with no player yet, or camera toggle disabled). */
	UFUNCTION(BlueprintCallable, Category = "Camera")
	void SetCameraMode(ECameraMode NewMode);

	/** Tier 4 overworld encounter start. Called from ABossEncounterVolume when the
	 *  player enters. Unhides the volume's boss, ensures HUD + NNE components are
	 *  installed, applies the volume's PreferredPersonaFallback to the NNE
	 *  archetype resolver, binds OnBossDied to trigger EndEncounter, and switches
	 *  the player's camera to Combat mode. Idempotent — a duplicate BeginEncounter
	 *  for the same volume no-ops. */
	void BeginEncounter(class ABossEncounterVolume* Volume);

	/** Tier 4 overworld encounter end. Called from ABossEncounterVolume on boss
	 *  death or when the player leaves the volume. Records + saves player memory
	 *  (skipped under -rlbridge / while a Python TCP client is connected — same
	 *  training-vs-shipping arbitration rule as elsewhere), re-hides the boss, and
	 *  switches the camera back to Exploration mode. */
	void EndEncounter(class ABossEncounterVolume* Volume);

private:
	/** Timer body: installs whatever is enabled and already spawnable; clears the
	 *  timer once every enabled feature is installed. */
	void TryInstall();

	/** Shipped-path player-memory lifecycle. The M5 archetype bank matches
	 *  against the STORED PlayerMemoryComponent profile, but outside training
	 *  nothing loaded or recorded it (LoadMemory's only other caller is the
	 *  Python bridge's set_player_id) — the bank was dead code in shipped play.
	 *  The subsystem now: LoadMemory (Firebase UID, else "guest") BEFORE the NNE
	 *  component is injected (its BeginPlay resolves the archetype match), and
	 *  RecordEncounterEnd + SaveMemory at every round end. Training sessions
	 *  (-rlbridge / live TCP client) skip recording — bot rounds must not
	 *  pollute the human dossier (the -NoTelemetry philosophy). */
	UFUNCTION()
	void HandleHeroHealthDepleted();
	UFUNCTION()
	void HandleBossDied();
	void RecordRoundEnd(bool bBossWon);

	/** True when this level contains at least one ABossEncounterVolume. TryInstall
	 *  detects this once and disables its own boss-side auto-injection (HUD, NNE,
	 *  boss-death binding, memory load) — the encounter volumes own those flows
	 *  and TryInstall would otherwise inject on the wrong actor. Set once at the
	 *  first TryInstall call. */
	bool bOverworldMode = false;

	/** Guards the one-time overworld-volume scan in TryInstall so PIE re-runs
	 *  redetect (per-subsystem member instead of function-local static). */
	bool bLevelInspected = false;

	/** Currently-active encounter (Tier 4). One at a time by design. */
	UPROPERTY()
	TObjectPtr<class ABossEncounterVolume> ActiveEncounter;

	FTimerHandle InstallTimerHandle;
	bool bCameraInstalled = false;
	bool bHUDInstalled = false;
	bool bMemoryLoaded = false;
	bool bHeroDeathBound = false;
	double RoundStartRealSeconds = 0.0;
	double LastRoundEndRealSeconds = -10.0;
};
