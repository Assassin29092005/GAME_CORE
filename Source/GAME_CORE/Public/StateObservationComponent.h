#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "PlayerProfileComponent.h"
#include "StateObservationComponent.generated.h"

class UCombatComponent;
class UPlayerMemoryComponent;
class UEmotionEstimationComponent;

USTRUCT(BlueprintType)
struct FRLObservation
{
	GENERATED_BODY()

	// Hero state (normalized)
	UPROPERTY(BlueprintReadOnly, Category = "Observation")
	FVector HeroVelocityNorm = FVector::ZeroVector;

	UPROPERTY(BlueprintReadOnly, Category = "Observation")
	int32 HeroComboStep = 0;

	UPROPERTY(BlueprintReadOnly, Category = "Observation")
	bool bHeroIsAttacking = false;

	UPROPERTY(BlueprintReadOnly, Category = "Observation")
	float HeroHealthPercent = 1.0f;

	// Relative state
	UPROPERTY(BlueprintReadOnly, Category = "Observation")
	float DistanceToHero = 0.0f;

	UPROPERTY(BlueprintReadOnly, Category = "Observation")
	float AngleToHero = 0.0f;

	// Boss state
	UPROPERTY(BlueprintReadOnly, Category = "Observation")
	float BossHealthPercent = 1.0f;

	// Player behavior profile (8 dimensions, indices 9-16)
	UPROPERTY(BlueprintReadOnly, Category = "Observation")
	FPlayerProfile PlayerProfile;

	// Extension 9: Estimated hero action for world model training
	// 0=Attack, 1=Block, 2=Dodge, 3=Approach, 4=Retreat, 5=Idle
	UPROPERTY(BlueprintReadOnly, Category = "Observation")
	int32 HeroLastAction = 5;

	// Extension 10: Player emotion estimation (frustration, flow, boredom)
	UPROPERTY(BlueprintReadOnly, Category = "Observation")
	float EmotionFrustration = 0.0f;

	UPROPERTY(BlueprintReadOnly, Category = "Observation")
	float EmotionFlow = 0.0f;

	UPROPERTY(BlueprintReadOnly, Category = "Observation")
	float EmotionBoredom = 0.0f;

	// Serialize to a flat float array for the RL environment
	TArray<float> ToFloatArray() const;

	// Serialize to JSON string for socket transmission
	FString ToJsonString() const;
};

UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UStateObservationComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UStateObservationComponent();

	// The hero actor to observe
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Observation")
	TObjectPtr<AActor> HeroActor;

	// Max walk speed for velocity normalization
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Observation")
	float MaxWalkSpeed = 600.0f;

	// Collect current observation snapshot
	UFUNCTION(BlueprintCallable, Category = "Observation")
	FRLObservation CollectObservation();

	// Get as JSON string (convenience for socket bridge)
	UFUNCTION(BlueprintCallable, Category = "Observation")
	FString GetObservationJson();

	// Get base observation dimension count (9 base + 8 profile = 17)
	// Additional dimensions (hero_action, emotion) are transmitted as
	// separate JSON fields and appended Python-side
	UFUNCTION(BlueprintPure, Category = "Observation")
	static int32 GetObservationSize() { return 17; }

	// Weight for merging live profile vs decayed historical profile
	// merged = LiveWeight * live + (1 - LiveWeight) * decayed
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Observation", meta = (ClampMin = "0.0", ClampMax = "1.0"))
	float LiveProfileWeight = 0.6f;

private:
	UCombatComponent* FindCombatComponent(AActor* Actor) const;
	FPlayerProfile GetMergedProfile() const;

	// Extension 9: Hero action estimation from observation deltas
	int32 EstimateHeroAction(const FRLObservation& Current, const FRLObservation& Previous) const;
	FRLObservation PreviousObservation;
	bool bHasPreviousObservation = false;
};
