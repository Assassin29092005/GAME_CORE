#pragma once

#include "CoreMinimal.h"
#include "Engine/TriggerVolume.h"
#include "UObject/SoftObjectPtr.h"
#include "BossEncounterVolume.generated.h"

class AActor;
class UBossActionComponent;

/**
 * Tier 4 overworld: a per-biome trigger that starts a boss encounter when the
 * player walks in and ends it on boss death or when the player leaves.
 *
 * Purpose in the shipping story
 * -----------------------------
 * The paper's core contribution (paper.md §4 point 5) is *"archetype-matched
 * policy selection via mean-centered cosine similarity"*. In the arena game
 * that resolution ran once at world load; in the overworld it runs *per
 * encounter*, against whatever the player's cross-encounter dossier currently
 * says. Same mechanism, deferred moment — and richer, because multiple
 * encounters per session multiply the match evidence.
 *
 * Interaction with the boss actor
 * -------------------------------
 * The volume references a pre-placed, initially-hidden boss actor (dropped
 * into the level by Tools/build_overworld_level.py near the biome center).
 * On player enter, UGameFeelSubsystem::BeginEncounter(this):
 *   1. unhides the boss + turns collision on
 *   2. ensures BossStatusHUD + NNEBossPolicyComponent are installed
 *   3. optionally overrides the NNE archetype resolver with PreferredPersonaFallback
 *      (used only when the cosine match against the player profile fails)
 *   4. switches UCombatCameraComponent to Combat mode
 *   5. binds the boss's OnBossDied to fire EndEncounter
 *
 * On boss death, or when the player leaves the disengage bounds, the volume
 * calls UGameFeelSubsystem::EndEncounter(this) which records the round to
 * PlayerMemoryComponent, saves the dossier, restores exploration camera, and
 * marks EncounterID defeated in the save game (Phase E).
 *
 * BossArena backward compatibility: BossArena.umap has no encounter volumes;
 * UGameFeelSubsystem's TryInstall detects this and keeps the pre-encounter
 * auto-injection path.
 */
UCLASS(BlueprintType)
class GAME_CORE_API ABossEncounterVolume : public ATriggerVolume
{
	GENERATED_BODY()

public:
	ABossEncounterVolume();

	/** The pre-placed boss actor to activate for this encounter. Kept soft so the
	 *  overworld map doesn't hard-reference the boss BP class; the actor is
	 *  spawned/placed by Tools/build_overworld_level.py and this pointer is
	 *  wired in the editor. Null = the volume is inert (log warning at PIE). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Encounter")
	TSoftObjectPtr<AActor> BossActor;

	/** Save-game key for this encounter. Unique across the world. Once the boss
	 *  is defeated the ID is written to the OverworldSaveGame (Phase E) so
	 *  re-entering the volume does nothing until a new save-slot is started. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Encounter")
	FName EncounterID = FName(TEXT("Castle"));

	/** Persona name to use for NNE brain selection when the player's stored
	 *  profile has no cosine-similar entry in the archetype bank (new / guest
	 *  player). Should match one of the +NNEArchetypeBank rows in DefaultGame.ini
	 *  (rusher, turtle, kiter, ...). Empty = falls through to the settings-driven
	 *  global default (NNEBossModelData). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Encounter")
	FName PreferredPersonaFallback = NAME_None;

	/** Optional spawn override. If BossActor is null (or dead-and-hidden),
	 *  BeginEncounter can spawn one at this transform relative to the volume.
	 *  Reserved for future dynamic-spawn work; current MVP path is pre-placement. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Encounter")
	FTransform SpawnOffset = FTransform::Identity;

	UFUNCTION(BlueprintPure, Category = "Encounter")
	bool IsEncounterActive() const { return bEncounterActive; }

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

	UFUNCTION()
	void OnPlayerBeginOverlap(AActor* OverlappedActor, AActor* OtherActor);

	UFUNCTION()
	void OnPlayerEndOverlap(AActor* OverlappedActor, AActor* OtherActor);

	UFUNCTION()
	void OnBossDefeated();

private:
	/** True between BeginEncounter and EndEncounter — used to reject overlap
	 *  double-fires (a Mover pawn touches the trigger on multiple axes as it
	 *  crosses the boundary; only the first begin should fire). */
	bool bEncounterActive = false;

	/** True once EncounterID has been defeated in this session and shouldn't
	 *  re-trigger. Persistent state is loaded from OverworldSaveGame in Phase E;
	 *  for now this flag survives only for the current PIE session. */
	bool bAlreadyDefeated = false;
};
