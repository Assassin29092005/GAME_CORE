#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "MinionEncounterSpawner.generated.h"

class ANPCMinionCharacter;

/**
 * Drop-in encounter: spawns SpawnCount minions on a ring of SpawnRadius around
 * this actor at BeginPlay. Each ring point is NavMesh-projected
 * (ProjectPointToNavigation) so minions land on walkable ground; if projection
 * fails (no navmesh / point in a wall) the raw ring point is used and the
 * AdjustIfPossibleButAlwaysSpawn collision handling nudges the capsule free.
 *
 * PatrolPoints are passed through to every spawned minion
 * (ANPCMinionCharacter::PatrolPoints) — BTService_MinionCombatState cycles them
 * into the PatrolLocation blackboard key. Leave empty for stand-at-home guards.
 */
UCLASS()
class GAME_CORE_API AMinionEncounterSpawner : public AActor
{
	GENERATED_BODY()

public:
	AMinionEncounterSpawner();

	/** Minion BP class to spawn (BP child of ANPCMinionCharacter with mesh,
	 *  AnimBP, and its OWN duplicated montages/CombatAnimConfig assets). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Spawner")
	TSubclassOf<ANPCMinionCharacter> MinionClass;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Spawner", meta = (ClampMin = "0"))
	int32 SpawnCount = 3;

	/** Ring radius (cm) around the spawner the minions appear on. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Spawner", meta = (ClampMin = "0.0"))
	float SpawnRadius = 900.0f;

	/** Ordered patrol route handed to every spawned minion (e.g. TargetPoint actors). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Spawner")
	TArray<TObjectPtr<AActor>> PatrolPoints;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Spawner")
	bool bSpawnOnBeginPlay = true;

	/** Manual trigger for BP-scripted encounters (e.g. spawn on volume overlap).
	 *  Idempotent while its previous batch is alive: early-outs if any tracked
	 *  minion still exists, so a retriggered overlap volume can't stack a second
	 *  ring of minions on top of the first. Use RespawnAll to force a fresh batch. */
	UFUNCTION(BlueprintCallable, Category = "Spawner")
	void SpawnMinions();

	/** Destroy any surviving tracked minions, then spawn a fresh ring. Call this
	 *  from the training level wherever round resets are observed so encounters
	 *  repopulate per round (dead minions are permanently destroyed via
	 *  SetLifeSpan and TriggerRoundReset deliberately skips minions — without a
	 *  respawn hook the arena silently goes minion-free after a few rounds). */
	UFUNCTION(BlueprintCallable, Category = "Spawner")
	void RespawnAll();

protected:
	virtual void BeginPlay() override;

private:
	/** Minions spawned by the last SpawnMinions call. Weak: destroyed/despawned
	 *  minions read as invalid and are pruned on the next spawn attempt. */
	TArray<TWeakObjectPtr<ANPCMinionCharacter>> SpawnedMinions;
};
