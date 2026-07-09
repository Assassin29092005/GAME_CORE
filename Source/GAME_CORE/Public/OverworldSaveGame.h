#pragma once

#include "CoreMinimal.h"
#include "GameFramework/SaveGame.h"
#include "OverworldSaveGame.generated.h"

/**
 * One row in the OverworldSaveGame's encounter log — a lightweight audit trail
 * of every encounter the player has finished. Optional; not consumed by
 * gameplay directly, but useful for the dashboard's per-run replay of who
 * fought which archetype in which biome.
 */
USTRUCT()
struct GAME_CORE_API FOverworldEncounterRecord
{
	GENERATED_BODY()

	/** Encounter identifier (matches ABossEncounterVolume::EncounterID). */
	UPROPERTY()
	FName EncounterID;

	/** Persona the NNE archetype selection resolved to for this encounter. */
	UPROPERTY()
	FName SelectedPersona;

	/** True = boss defeated, false = player retreated / died. */
	UPROPERTY()
	bool bBossDefeated = false;

	/** Real-time seconds the encounter lasted. */
	UPROPERTY()
	float DurationSeconds = 0.0f;

	/** Unix timestamp (seconds since epoch, UTC) when the encounter ended. */
	UPROPERTY()
	int64 EndUnixSeconds = 0;
};

/**
 * Tier 4 open-world save state.
 *
 * Written whenever an encounter ends (boss defeated or player retreat) and
 * whenever the player quits (Phase G hook, later). Loaded once at world
 * BeginPlay by UGameFeelSubsystem: the player pawn is teleported to
 * PlayerLocation/PlayerRotation, and each ABossEncounterVolume whose
 * EncounterID appears in DefeatedBossZones marks itself as
 * bAlreadyDefeated = true so re-entering the volume does nothing.
 *
 * Independent from PlayerMemoryComponent's dossier: the memory captures
 * *the mind's* profile, this captures *the world's* progress. Both are
 * keyed by the same PlayerId (Firebase UID or "guest") but persist through
 * different SaveGame slots.
 */
UCLASS(BlueprintType)
class GAME_CORE_API UOverworldSaveGame : public USaveGame
{
	GENERATED_BODY()

public:
	/** Player world-space location at the moment of save. Restored on load. */
	UPROPERTY()
	FVector PlayerLocation = FVector(0.0f, 0.0f, 30000.0f);   // castle plateau default

	/** Player world-space rotation at the moment of save. Restored on load. */
	UPROPERTY()
	FRotator PlayerRotation = FRotator::ZeroRotator;

	/** Set of EncounterIDs the player has cleared. ABossEncounterVolume::BeginPlay
	 *  checks this and marks itself defeated so it won't re-trigger. */
	UPROPERTY()
	TSet<FName> DefeatedBossZones;

	/** Full history of encounters this save has completed. Not consumed by
	 *  gameplay — surfaced by the dashboard telemetry. Grows unbounded but at
	 *  << 200 bytes/entry the cost is negligible for even 10 k encounters. */
	UPROPERTY()
	TArray<FOverworldEncounterRecord> EncounterLog;

	/** Unix seconds the save was last touched. Sanity/debug field. */
	UPROPERTY()
	int64 LastSavedUnixSeconds = 0;

	/** Slot names for the SaveGame system. One slot per PlayerId. */
	static FString SlotNameForPlayer(const FString& PlayerId);

	/** SaveGame user index — kept 0; multi-user local play is not on the roadmap. */
	static constexpr int32 UserIndex = 0;
};
