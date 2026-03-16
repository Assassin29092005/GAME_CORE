#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "PlayerProfileComponent.h"
#include "BossExplainabilityComponent.generated.h"

/**
 * A single insight about what the boss has learned about the player.
 */
USTRUCT(BlueprintType)
struct FBossInsight
{
	GENERATED_BODY()

	// Human-readable taunt text (e.g., "Your sword arm grows predictable")
	UPROPERTY(BlueprintReadOnly, Category = "Explainability")
	FText TauntText;

	// Longer description of what the boss learned
	UPROPERTY(BlueprintReadOnly, Category = "Explainability")
	FText StrategyDescription;

	// Tag for visual effects / armor adaptation (e.g., "AntiMelee", "AntiKite")
	UPROPERTY(BlueprintReadOnly, Category = "Explainability")
	FName AdaptationTag;

	// How confident the boss is about this insight (0 = uncertain, 1 = very confident)
	UPROPERTY(BlueprintReadOnly, Category = "Explainability")
	float Confidence = 0.0f;

	// Which profile dimension this insight relates to (0-7)
	UPROPERTY(BlueprintReadOnly, Category = "Explainability")
	int32 ProfileDimensionIndex = -1;
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnBossInsightGenerated, const FBossInsight&, Insight);

/**
 * Generates player-facing feedback about what the boss has learned.
 * Reads from the player behavior profile and produces taunts, visual cues,
 * and strategy descriptions that make the RL system visible to the player.
 *
 * Attach to BP_Boss. This is a passive reader — it never modifies combat behavior.
 */
UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UBossExplainabilityComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UBossExplainabilityComponent();

	// Generate all insights from a profile
	UFUNCTION(BlueprintCallable, Category = "Explainability")
	TArray<FBossInsight> GenerateInsights(const FPlayerProfile& Profile) const;

	// Generate the single strongest taunt
	UFUNCTION(BlueprintCallable, Category = "Explainability")
	FText GenerateTopTaunt(const FPlayerProfile& Profile) const;

	// Broadcast all insights via delegate (call at encounter start/end)
	UFUNCTION(BlueprintCallable, Category = "Explainability")
	void BroadcastInsights(const FPlayerProfile& Profile);

	// Fires for each insight generated
	UPROPERTY(BlueprintAssignable, Category = "Explainability")
	FOnBossInsightGenerated OnBossInsightGenerated;

	// Threshold: profile dimension must be this far from 0.5 to trigger an insight
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Explainability")
	float StrongTraitThreshold = 0.7f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Explainability")
	float WeakTraitThreshold = 0.3f;

	// Designer-customizable taunt templates per adaptation tag
	// Key = AdaptationTag (e.g., "AntiMelee"), Value = Taunt text
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Explainability|Taunts")
	TMap<FName, FText> TauntOverrides;

private:
	struct FInsightTemplate
	{
		int32 DimensionIndex;
		bool bHighIsActive;  // true = high value triggers, false = low value triggers
		FName AdaptationTag;
		FText DefaultTaunt;
		FText Description;
	};

	TArray<FInsightTemplate> InsightTemplates;
	void InitializeTemplates();
};
