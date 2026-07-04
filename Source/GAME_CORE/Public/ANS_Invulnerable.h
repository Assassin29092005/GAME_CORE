#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimNotifies/AnimNotifyState.h"
#include "ANS_Invulnerable.generated.h"

/**
 * Dodge i-frames (guide.md 3.5). Place on the dodge montage covering roughly
 * 10%-60% of the roll (~0.3s of i-frames in a 0.7s dodge): i-frames start a
 * beat AFTER the press and end BEFORE recovery — dodge timing as a skill, not
 * dodge spam as a defense.
 *
 * Drives CombatComponent::bDodgeInvulnerable — a SEPARATE flag from the
 * post-reset bIsInvulnerable, which is owned by ResetForNewRound and its timer.
 * Same owner-side-state pattern as ANS_DealDamage/ANS_CancelWindow, with the
 * same defensive clears (OnDodgeMontageEnded / ResetForNewRound) because an
 * interrupted montage can skip NotifyEnd.
 */
UCLASS(meta = (DisplayName = "Invulnerable (i-frames)"))
class GAME_CORE_API UANS_Invulnerable : public UAnimNotifyState
{
	GENERATED_BODY()

public:
	virtual void NotifyBegin(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, float TotalDuration, const FAnimNotifyEventReference& EventReference) override;
	virtual void NotifyEnd(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, const FAnimNotifyEventReference& EventReference) override;

	virtual FString GetNotifyName_Implementation() const override { return TEXT("Invulnerable"); }
};
