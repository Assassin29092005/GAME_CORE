#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimNotifies/AnimNotifyState.h"
#include "ANS_HyperArmor.generated.h"

/**
 * Phase 4.5 hyper-armor window: while active, Light hit reactions on the owner are
 * suppressed (no flinch) — damage and stagger still apply, so sustained pressure can
 * escalate a Medium/Heavy through the armor. Place on the boss's heavy attack
 * montages covering the active frames (roughly the ANS_DealDamage window plus a few
 * frames either side) so the player can't flinch-lock the heaviest swings.
 *
 * State lives on the owner's HitReactionComponent, never on this notify instance —
 * UAnimNotifyState members are unreliable in UE5 (the ANS_DealDamage lesson). Note
 * that hit-stop's Montage_Pause/Resume re-fires NotifyBegin mid-swing; setting the
 * flag true again is idempotent, so that's safe (never gate once-per-swing state
 * on NotifyBegin).
 */
UCLASS(meta = (DisplayName = "Hyper Armor Window"))
class GAME_CORE_API UANS_HyperArmor : public UAnimNotifyState
{
	GENERATED_BODY()

public:
	virtual void NotifyBegin(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, float TotalDuration, const FAnimNotifyEventReference& EventReference) override;
	virtual void NotifyEnd(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, const FAnimNotifyEventReference& EventReference) override;

	virtual FString GetNotifyName_Implementation() const override { return TEXT("HyperArmor"); }
};
