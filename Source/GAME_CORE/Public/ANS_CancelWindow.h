#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimNotifies/AnimNotifyState.h"
#include "ANS_CancelWindow.generated.h"

/**
 * Marks the recovery frames of an attack montage as cancelable into dodge/block
 * (guide.md 3.2). Place over recovery: from just after the ANS_DealDamage bar to
 * ~85% of the montage. Lights get generous windows, heavies cancel late — that
 * asymmetry IS the light/heavy feel difference.
 *
 * State lives on the owner's CombatComponent, NOT on this notify state — the
 * ANS_DealDamage pattern; notify-state instance members proved unreliable in
 * UE5. Opening the window also drains the buffered-action queue, so a press
 * swallowed during startup fires the exact frame recovery becomes cancelable.
 * Safe against the hit-stop NotifyBegin re-fire: repeating SetCancelWindowOpen
 * (true) is idempotent and re-draining an empty buffer is a no-op.
 */
UCLASS(meta = (DisplayName = "Cancel Window"))
class GAME_CORE_API UANS_CancelWindow : public UAnimNotifyState
{
	GENERATED_BODY()

public:
	virtual void NotifyBegin(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, float TotalDuration, const FAnimNotifyEventReference& EventReference) override;
	virtual void NotifyEnd(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, const FAnimNotifyEventReference& EventReference) override;

	virtual FString GetNotifyName_Implementation() const override { return TEXT("CancelWindow"); }
};
