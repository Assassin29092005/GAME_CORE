#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "EmotionEstimationComponent.generated.h"

/**
 * Estimated player emotional state — no hardware needed,
 * purely inferred from behavioral signals.
 */
UENUM(BlueprintType)
enum class EPlayerEmotionalState : uint8
{
	Neutral		UMETA(DisplayName = "Neutral"),
	Frustrated	UMETA(DisplayName = "Frustrated"),
	Flow		UMETA(DisplayName = "Flow"),
	Bored		UMETA(DisplayName = "Bored"),
};

USTRUCT(BlueprintType)
struct FEmotionEstimate
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "Emotion")
	float FrustrationScore = 0.0f;

	UPROPERTY(BlueprintReadOnly, Category = "Emotion")
	float FlowScore = 0.0f;

	UPROPERTY(BlueprintReadOnly, Category = "Emotion")
	float BoredomScore = 0.0f;

	UPROPERTY(BlueprintReadOnly, Category = "Emotion")
	EPlayerEmotionalState DominantState = EPlayerEmotionalState::Neutral;

	FString ToJsonString() const;
};

/**
 * Stored record of a single encounter outcome for trend analysis.
 */
USTRUCT()
struct FEncounterOutcome
{
	GENERATED_BODY()

	UPROPERTY()
	bool bBossWon = false;

	UPROPERTY()
	float DurationSeconds = 0.0f;

	UPROPERTY()
	float HeroHPAtEnd = 0.0f;

	UPROPERTY()
	float BossHPAtEnd = 0.0f;
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnEmotionEstimateUpdated, const FEmotionEstimate&, Estimate);

/**
 * Estimates the player's emotional state from behavioral signals.
 * Attach to BP_Boss. Tracks encounter outcomes and within-encounter
 * action patterns to infer frustration, flow, or boredom.
 *
 * Frustration: consecutive losses, decreasing fight duration, action spam, low variety
 * Flow:        mixed outcomes, close HP fights, high action variety, stable duration
 * Boredom:     low action rate, high idle time, retreat-heavy, decreasing engagement
 *
 * Novel: Yannakakis (EDPCG 2011) proposed this theoretically but nobody has
 * implemented it with an RL boss AI in real-time combat.
 */
UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UEmotionEstimationComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UEmotionEstimationComponent();

	virtual void TickComponent(float DeltaTime, ELevelTick TickType,
		FActorComponentTickFunction* ThisTickFunction) override;

	// --- Public API ---

	/** Compute current emotion estimate from accumulated data. */
	UFUNCTION(BlueprintCallable, Category = "Emotion")
	FEmotionEstimate EstimateEmotion() const;

	/** Record the outcome of a completed encounter (call at fight end). */
	UFUNCTION(BlueprintCallable, Category = "Emotion")
	void RecordEncounterOutcome(bool bBossWon, float DurationSeconds,
		float HeroHPAtEnd, float BossHPAtEnd);

	/** Record a player action (call each time the hero acts). */
	UFUNCTION(BlueprintCallable, Category = "Emotion")
	void RecordPlayerAction(int32 ActionIndex);

	/** Reset within-encounter tracking (call at encounter start). */
	UFUNCTION(BlueprintCallable, Category = "Emotion")
	void ResetEncounterTracking();

	// --- Delegate ---

	UPROPERTY(BlueprintAssignable, Category = "Emotion")
	FOnEmotionEstimateUpdated OnEmotionEstimateUpdated;

	// --- Configuration ---

	/** How many recent encounters to consider for trend analysis. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Emotion|Config")
	int32 MaxRecentEncounters = 10;

	/** Consecutive losses needed for high frustration signal. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Emotion|Config")
	int32 FrustrationLossStreak = 3;

	/** Action rate multiplier above average that triggers "spam" detection. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Emotion|Config")
	float SpamRateMultiplier = 2.0f;

	/** Minimum score to consider an emotion "dominant". */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Emotion|Config")
	float DominanceThreshold = 0.3f;

	/** Seconds of idle time before boredom signal triggers. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Emotion|Config")
	float BoredomIdleThreshold = 3.0f;

private:
	// Encounter history (ring buffer of recent outcomes)
	TArray<FEncounterOutcome> RecentEncounters;

	// Within-encounter action tracking
	TArray<int32> ActionHistory;        // Action indices this encounter
	float EncounterElapsedTime = 0.0f;
	float TimeSinceLastAction = 0.0f;
	int32 ActionCountThisEncounter = 0;

	// Previous emotion state for change detection
	EPlayerEmotionalState PreviousDominantState = EPlayerEmotionalState::Neutral;

	// Scoring functions
	float ComputeFrustration() const;
	float ComputeFlow() const;
	float ComputeBoredom() const;

	// Helpers
	int32 GetConsecutiveLosses() const;
	float GetAverageFightDuration() const;
	float GetActionEntropy() const;
	float GetRecentWinRate() const;
	float GetAverageHPDifferential() const;
	bool IsFightDurationDecreasing() const;
};
