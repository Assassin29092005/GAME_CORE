#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
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

	FTimerHandle InstallTimerHandle;
	bool bCameraInstalled = false;
	bool bHUDInstalled = false;
	bool bMemoryLoaded = false;
	bool bHeroDeathBound = false;
	double RoundStartRealSeconds = 0.0;
	double LastRoundEndRealSeconds = -10.0;
};
