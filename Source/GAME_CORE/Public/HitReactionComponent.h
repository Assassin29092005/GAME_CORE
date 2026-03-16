#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Animation/AnimMontage.h"
#include "HitReactionComponent.generated.h"

UENUM(BlueprintType)
enum class EHitDirection : uint8
{
	Front,
	Back,
	Left,
	Right
};

UENUM(BlueprintType)
enum class EStaggerIntensity : uint8
{
	Light,
	Medium,
	Heavy
};

USTRUCT(BlueprintType)
struct FDirectionalHitReaction
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "HitReaction")
	TObjectPtr<UAnimMontage> HitFront = nullptr;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "HitReaction")
	TObjectPtr<UAnimMontage> HitBack = nullptr;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "HitReaction")
	TObjectPtr<UAnimMontage> HitLeft = nullptr;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "HitReaction")
	TObjectPtr<UAnimMontage> HitRight = nullptr;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "HitReaction", meta = (ClampMin = "0.5", ClampMax = "1.5"))
	float PlayRate = 1.0f;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "HitReaction", meta = (ClampMin = "0.0", ClampMax = "0.5"))
	float BlendInTime = 0.15f;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "HitReaction", meta = (ClampMin = "0.0", ClampMax = "0.5"))
	float BlendOutTime = 0.2f;

	UAnimMontage* GetMontageForDirection(EHitDirection Direction) const;
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE_ThreeParams(FOnHitReactionTriggered, AActor*, InstigatorActor, float, DamageAmount, FName, DamageType);

UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UHitReactionComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UHitReactionComponent();

	// Directional hit reactions by stagger intensity
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "HitReaction")
	FDirectionalHitReaction LightHitReactions;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "HitReaction")
	FDirectionalHitReaction MediumHitReactions;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "HitReaction")
	FDirectionalHitReaction HeavyHitReactions;

	// Knockback montage for heavy combo finishers
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "HitReaction")
	TObjectPtr<UAnimMontage> KnockbackMontage = nullptr;

	// Threshold: cumulative damage before upgrading stagger
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitReaction|Stagger")
	float MediumStaggerThreshold = 30.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitReaction|Stagger")
	float HeavyStaggerThreshold = 60.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitReaction|Stagger")
	float StaggerDecayRate = 15.0f;

	// Fires when a hit reaction is triggered (before montage plays).
	// Useful for PlayerProfileComponent to track incoming attacks.
	UPROPERTY(BlueprintAssignable, Category = "HitReaction")
	FOnHitReactionTriggered OnHitReactionTriggered;

	// Main entry point: call when this actor takes a hit
	UFUNCTION(BlueprintCallable, Category = "HitReaction")
	void PlayHitReaction(AActor* InstigatorActor, float DamageAmount, FName DamageType);

	UFUNCTION(BlueprintPure, Category = "HitReaction")
	float GetCurrentStagger() const { return CurrentStagger; }

protected:
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	EHitDirection CalculateHitDirection(AActor* InstigatorActor) const;
	EStaggerIntensity DetermineStaggerIntensity(float DamageAmount, FName DamageType) const;
	const FDirectionalHitReaction& GetReactionSet(EStaggerIntensity Intensity) const;

	float CurrentStagger = 0.0f;
};
