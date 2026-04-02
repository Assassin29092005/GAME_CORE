#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimNotifies/AnimNotifyState.h"
#include "ANS_DealDamage.generated.h"

/**
 * Anim Notify State that performs a sphere trace during the damage window
 * and applies damage + hit reaction to the first actor hit.
 * Place on attack montages to define when the attack can deal damage.
 */
UCLASS(meta = (DisplayName = "Deal Damage Window"))
class GAME_CORE_API UANS_DealDamage : public UAnimNotifyState
{
	GENERATED_BODY()

public:
	UANS_DealDamage();

	virtual void NotifyBegin(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, float TotalDuration, const FAnimNotifyEventReference& EventReference) override;
	virtual void NotifyTick(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, float FrameDeltaTime, const FAnimNotifyEventReference& EventReference) override;
	virtual void NotifyEnd(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, const FAnimNotifyEventReference& EventReference) override;

	virtual FString GetNotifyName_Implementation() const override { return TEXT("DealDamage"); }

	// Trace radius for hit detection
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Damage")
	float TraceRadius = 80.0f;

	// How far in front of the attacker to trace
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Damage")
	float TraceForwardOffset = 120.0f;

private:
	// Prevents hitting the same target multiple times per swing
	bool bHasHitThisSwing = false;
};
