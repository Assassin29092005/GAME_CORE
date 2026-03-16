#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "PlayerProfileComponent.generated.h"

/**
 * 8-dimensional player behavior profile, all values normalized to [0,1].
 * Appended to the RL observation vector (indices 9-16).
 */
USTRUCT(BlueprintType)
struct FPlayerProfile
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "PlayerProfile")
	float AggressionScore = 0.5f;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerProfile")
	float DodgeTendency = 0.5f;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerProfile")
	float BlockTendency = 0.5f;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerProfile")
	float OpenerAggression = 0.5f;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerProfile")
	float PressureResponse = 0.5f;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerProfile")
	float KitingScore = 0.5f;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerProfile")
	float ComboCompletionRate = 0.5f;

	UPROPERTY(BlueprintReadOnly, Category = "PlayerProfile")
	float PositionalVariance = 0.5f;

	TArray<float> ToFloatArray() const;
	FString ToJsonString() const;
	void FromJsonObject(const TSharedPtr<FJsonObject>& Obj);

	static int32 GetProfileSize() { return 8; }

	/** Element access by index (0-7). */
	float GetDimension(int32 Index) const;
	void SetDimension(int32 Index, float Value);
};

class UCombatComponent;

/**
 * Tracks multi-dimensional player behavior during an encounter.
 * Attach to the player character (BP_NeuralHero).
 * Uses exponential moving averages for smooth, recency-weighted profiling.
 */
UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UPlayerProfileComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UPlayerProfileComponent();

protected:
	virtual void BeginPlay() override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

public:
	// Reference to the boss for distance calculations
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "PlayerProfile")
	TObjectPtr<AActor> BossActor;

	// Melee range threshold (units). Below = melee, above = ranged/kiting.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "PlayerProfile", meta = (ClampMin = "100.0"))
	float MeleeRangeThreshold = 300.0f;

	// EMA smoothing factor (lower = smoother, 0.05 default)
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "PlayerProfile", meta = (ClampMin = "0.01", ClampMax = "0.5"))
	float EmaAlpha = 0.05f;

	// Size of the position history ring buffer for variance calculation
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "PlayerProfile", meta = (ClampMin = "5", ClampMax = "100"))
	int32 PositionHistorySize = 20;

	// Get the current profile snapshot
	UFUNCTION(BlueprintCallable, Category = "PlayerProfile")
	FPlayerProfile GetProfile() const;

	// Reset all tracking counters (call at encounter start)
	UFUNCTION(BlueprintCallable, Category = "PlayerProfile")
	void ResetEncounterTracking();

	// Record that the player performed an attack
	UFUNCTION(BlueprintCallable, Category = "PlayerProfile")
	void RecordAttack();

	// Record that the player dodged an incoming attack
	UFUNCTION(BlueprintCallable, Category = "PlayerProfile")
	void RecordDodge();

	// Record that the player blocked an incoming attack
	UFUNCTION(BlueprintCallable, Category = "PlayerProfile")
	void RecordBlock();

	// Record that the player was hit (neither dodged nor blocked)
	UFUNCTION(BlueprintCallable, Category = "PlayerProfile")
	void RecordHitTaken();

	// Record that a combo was started
	UFUNCTION(BlueprintCallable, Category = "PlayerProfile")
	void RecordComboStarted();

	// Record that a combo was completed (all steps landed)
	UFUNCTION(BlueprintCallable, Category = "PlayerProfile")
	void RecordComboCompleted();

private:
	// Sampling accumulator (samples at ~4 Hz)
	float SampleAccumulator = 0.0f;
	static constexpr float SampleInterval = 0.25f;

	// EMA-smoothed counters
	float EmaAttackRate = 0.5f;        // attacks / total actions
	float EmaDodgeRate = 0.5f;         // dodges / incoming attacks
	float EmaBlockRate = 0.5f;         // blocks / incoming attacks
	float EmaKitingRate = 0.5f;        // time at range / total time

	// Raw encounter counters
	int32 TotalActions = 0;
	int32 AttackActions = 0;
	int32 IncomingAttacks = 0;
	int32 DodgedAttacks = 0;
	int32 BlockedAttacks = 0;
	int32 CombosStarted = 0;
	int32 CombosCompleted = 0;

	// Opener tracking (first 20% of encounter)
	int32 EncounterStepCount = 0;
	int32 OpenerStepCount = 0;
	int32 OpenerAttackCount = 0;
	bool bOpenerPhaseComplete = false;

	// Pressure tracking (HP < 30%)
	int32 LowHpSamples = 0;
	int32 LowHpAttackSamples = 0;

	// Distance sampling
	int32 MeleeSamples = 0;
	int32 RangeSamples = 0;

	// Positional variance (ring buffer)
	TArray<FVector2D> PositionHistory;
	int32 PositionHistoryIndex = 0;

	// Helper to bind delegates
	void BindToCombatComponent();

	// Delegate callbacks
	UFUNCTION()
	void OnOwnerAttackLanded(float DamageAmount, FName DamageType);

	// Compute positional variance from history
	float ComputePositionalVariance() const;

	UCombatComponent* OwnerCombatComp = nullptr;
};
