#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "Animation/AnimMontage.h"
#include "CombatAnimConfig.generated.h"

USTRUCT(BlueprintType)
struct FAttackAnimData
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Animation")
	TObjectPtr<UAnimMontage> Montage = nullptr;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Animation", meta = (ClampMin = "0.1", ClampMax = "2.0"))
	float PlayRate = 0.9f;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Animation", meta = (ClampMin = "0.0", ClampMax = "1.0"))
	float BlendInTime = 0.2f;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Animation", meta = (ClampMin = "0.0", ClampMax = "1.0"))
	float BlendOutTime = 0.25f;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Animation")
	FName StartSection = NAME_None;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Animation")
	bool bEnableRootMotion = true;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Damage")
	float DamageAmount = 10.0f;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Damage")
	FName DamageType = FName(TEXT("Light"));

	// --- Per-attack hit feedback (guide.md 3.4) ---
	// Weight lives in data, not constants: openers ~0.05s/0.7, mid-chain 0.08/1.0,
	// finishers 0.12-0.15/1.5 (finishers additionally route through
	// TriggerHeavyHitFeedback at the ANS_DealDamage call site).

	/** Per-actor hit-stop length when this attack lands (seconds, real time). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Feedback",
	          meta = (ClampMin = "0.0", ClampMax = "0.3"))
	float HitStopDuration = 0.08f;     // matches HitFeedbackComponent's current global

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Feedback",
	          meta = (ClampMin = "0.0", ClampMax = "2.0"))
	float CameraShakeScale = 1.0f;

	/** Impulse applied to the target on hit. Consumed in guide.md Phase 6.3. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Feedback")
	float KnockbackImpulse = 0.0f;
};

UCLASS(BlueprintType)
class GAME_CORE_API UCombatAnimConfig : public UDataAsset
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Combat")
	TArray<FAttackAnimData> ComboChain;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Combat", meta = (ClampMin = "0.0", ClampMax = "2.0"))
	float ComboWindowDuration = 0.6f;

	const FAttackAnimData* GetAttackData(int32 ComboIndex) const;

	int32 GetComboLength() const { return ComboChain.Num(); }
};
