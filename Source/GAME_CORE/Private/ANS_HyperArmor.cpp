#include "ANS_HyperArmor.h"
#include "HitReactionComponent.h"
#include "Components/SkeletalMeshComponent.h"

namespace
{
	UHitReactionComponent* FindOwnerHitReaction(USkeletalMeshComponent* MeshComp)
	{
		AActor* Owner = MeshComp ? MeshComp->GetOwner() : nullptr;
		return Owner ? Owner->FindComponentByClass<UHitReactionComponent>() : nullptr;
	}
}

void UANS_HyperArmor::NotifyBegin(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, float TotalDuration, const FAnimNotifyEventReference& EventReference)
{
	Super::NotifyBegin(MeshComp, Animation, TotalDuration, EventReference);

	// Repeat-safe by design: hit-stop pause/resume re-fires NotifyBegin mid-swing,
	// and re-arming an already-true flag is a no-op.
	if (UHitReactionComponent* HitReaction = FindOwnerHitReaction(MeshComp))
	{
		HitReaction->SetHyperArmor(true);
	}
}

void UANS_HyperArmor::NotifyEnd(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, const FAnimNotifyEventReference& EventReference)
{
	Super::NotifyEnd(MeshComp, Animation, EventReference);

	if (UHitReactionComponent* HitReaction = FindOwnerHitReaction(MeshComp))
	{
		HitReaction->SetHyperArmor(false);
	}
	// Insurance for interrupted montages that skip NotifyEnd:
	// HitReactionComponent::ResetForNewRound also clears the flag.
}
