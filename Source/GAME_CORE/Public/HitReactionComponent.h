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

	/** Extra grace period after a hit reaction montage ends during which IsReacting() still
	 *  returns true. Stops the next RL action from firing in the tiny gap between Montage_End
	 *  and the next combo hit landing (which was causing the boss to dodge mid-combo). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitReaction|Stagger")
	float HitReactionGracePeriod = 0.25f;

	// Fires when a hit reaction is triggered (before montage plays).
	// Useful for PlayerProfileComponent to track incoming attacks.
	UPROPERTY(BlueprintAssignable, Category = "HitReaction")
	FOnHitReactionTriggered OnHitReactionTriggered;

	// Main entry point: call when this actor takes a hit
	UFUNCTION(BlueprintCallable, Category = "HitReaction")
	void PlayHitReaction(AActor* InstigatorActor, float DamageAmount, FName DamageType);

	/** Clear stagger and any in-flight reaction state. Called by BossActionComponent::ResetForNewRound
	 *  so post-reset hits don't inherit the previous round's accumulated stagger or grace timer. */
	UFUNCTION(BlueprintCallable, Category = "HitReaction")
	void ResetForNewRound();

	UFUNCTION(BlueprintPure, Category = "HitReaction")
	float GetCurrentStagger() const { return CurrentStagger; }

	/** True from the moment a hit-reaction montage starts until it finishes AND the grace
	 *  period elapses. BossActionComponent reads this to lock out RL actions while the boss
	 *  is flinching, so an Attack arriving from the bridge mid-reaction doesn't pop into the
	 *  attack montage. Non-inline because the grace check needs the world time. */
	UFUNCTION(BlueprintPure, Category = "HitReaction")
	bool IsReacting() const;

protected:
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	EHitDirection CalculateHitDirection(AActor* InstigatorActor) const;
	EStaggerIntensity DetermineStaggerIntensity(float DamageAmount, FName DamageType) const;
	const FDirectionalHitReaction& GetReactionSet(EStaggerIntensity Intensity) const;

	UFUNCTION()
	void OnHitReactionMontageEnded(UAnimMontage* Montage, bool bInterrupted);

	float CurrentStagger = 0.0f;

	bool bIsReacting = false;

	/** World time (seconds) at which the last reaction montage ended. IsReacting() uses this
	 *  with HitReactionGracePeriod to keep the lockout active for a short window after the
	 *  flinch finishes — otherwise the next RL Action arriving from the bridge can fire
	 *  in the gap and the boss visibly dodges/attacks mid-combo. */
	float LastReactionEndTime = -1000.0f;

	// Tracks the active hit-reaction montage so we ignore stale end-delegate callbacks
	// (e.g., when one reaction interrupts another).
	UPROPERTY()
	TObjectPtr<UAnimMontage> CurrentReactionMontage;
};
