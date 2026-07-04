#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimNotifies/AnimNotify.h"
#include "AN_RestoreRate.generated.h"

/**
 * Restores the active montage's play rate to 1.0.
 * Phase 4.4 telegraph slow-in: BossActionComponent::DoAttack plays the attack
 * montage then drops its rate (WindupPlayRate 0.6, or OffscreenWindupPlayRate 0.45
 * when unseen — Phase 5.3) so the wind-up reads as anticipation. Place this notify
 * at the start of the montage's Active section so the swing itself lands at full
 * speed. Stateless on purpose — a plain UAnimNotify has nothing to leak, and
 * re-firing (e.g. hit-stop pause/resume) just re-sets 1.0, which is repeat-safe.
 */
UCLASS(meta = (DisplayName = "Restore Play Rate"))
class GAME_CORE_API UAN_RestoreRate : public UAnimNotify
{
	GENERATED_BODY()

public:
	virtual void Notify(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, const FAnimNotifyEventReference& EventReference) override;

	virtual FString GetNotifyName_Implementation() const override { return TEXT("RestoreRate"); }
};
