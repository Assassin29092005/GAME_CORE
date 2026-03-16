#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "PlayerProfileComponent.h"
#include "PlayerMemoryComponent.generated.h"

/**
 * A single encounter record for cross-encounter memory.
 */
USTRUCT(BlueprintType)
struct FPlayerEncounterRecord
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "PlayerMemory")
	FPlayerProfile Profile;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerMemory")
	int32 EncounterIndex = 0;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerMemory")
	bool bBossWon = false;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerMemory")
	float FightDurationSeconds = 0.0f;
};

/**
 * Persistent player memory data, serialized to JSON.
 */
USTRUCT(BlueprintType)
struct FPlayerMemoryData
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "PlayerMemory")
	FString PlayerId;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerMemory")
	FPlayerProfile DecayedProfile;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerMemory")
	TArray<FPlayerEncounterRecord> RecentEncounters;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerMemory")
	int32 TotalEncounters = 0;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerMemory")
	int32 BossWins = 0;

	// Per-dimension: encounters since that dimension was "active" (above threshold)
	UPROPERTY()
	TArray<int32> EncountersSinceActive;
};

/**
 * Stores and manages cross-encounter player behavior memory with decay.
 * Attach to BP_Boss. Persists data as JSON in Saved/BossMemory/{PlayerId}.json.
 *
 * Decay mechanic: if a profile dimension hasn't been "active" for DecayEncounterThreshold
 * encounters, it gradually decays toward 0.5 (neutral). This prevents the boss from
 * being an all-knowing entity that counters everything simultaneously.
 */
UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UPlayerMemoryComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UPlayerMemoryComponent();

	// How many encounters before a dimension starts decaying
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "PlayerMemory|Decay")
	int32 DecayEncounterThreshold = 5;

	// Per-encounter decay rate beyond threshold (lerp factor toward 0.5)
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "PlayerMemory|Decay", meta = (ClampMin = "0.01", ClampMax = "0.5"))
	float DecayRate = 0.15f;

	// Threshold for considering a dimension "active" (abs distance from 0.5)
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "PlayerMemory|Decay", meta = (ClampMin = "0.05", ClampMax = "0.4"))
	float ActiveThreshold = 0.15f;

	// Max recent encounters to store
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "PlayerMemory", meta = (ClampMin = "5", ClampMax = "100"))
	int32 MaxRecentEncounters = 20;

	// Load memory from disk for the given player
	UFUNCTION(BlueprintCallable, Category = "PlayerMemory")
	void LoadMemory(const FString& PlayerId);

	// Save current memory to disk
	UFUNCTION(BlueprintCallable, Category = "PlayerMemory")
	void SaveMemory();

	// Record the end of an encounter and apply decay
	UFUNCTION(BlueprintCallable, Category = "PlayerMemory")
	void RecordEncounterEnd(const FPlayerProfile& Profile, bool bBossWon, float DurationSeconds);

	// Get the current decayed aggregate profile
	UFUNCTION(BlueprintCallable, Category = "PlayerMemory")
	FPlayerProfile GetDecayedProfile() const { return MemoryData.DecayedProfile; }

	// Get as JSON for TCP transmission
	UFUNCTION(BlueprintCallable, Category = "PlayerMemory")
	FString GetDecayedProfileJson() const;

	UFUNCTION(BlueprintPure, Category = "PlayerMemory")
	int32 GetTotalEncounters() const { return MemoryData.TotalEncounters; }

	UFUNCTION(BlueprintPure, Category = "PlayerMemory")
	int32 GetBossWins() const { return MemoryData.BossWins; }

	UFUNCTION(BlueprintPure, Category = "PlayerMemory")
	float GetBossWinRate() const;

	UFUNCTION(BlueprintPure, Category = "PlayerMemory")
	FString GetCurrentPlayerId() const { return MemoryData.PlayerId; }

private:
	FPlayerMemoryData MemoryData;

	FString GetSaveFilePath(const FString& PlayerId) const;
	void ApplyDecay(const FPlayerProfile& CurrentProfile);
	void InitializeMemoryData(const FString& PlayerId);
};
