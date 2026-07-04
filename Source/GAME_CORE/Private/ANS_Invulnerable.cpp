#include "ANS_Invulnerable.h"
#include "CombatComponent.h"

void UANS_Invulnerable::NotifyBegin(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, float TotalDuration, const FAnimNotifyEventReference& EventReference)
{
	Super::NotifyBegin(MeshComp, Animation, TotalDuration, EventReference);

	// Safe against the hit-stop NotifyBegin re-fire: setting true twice is a no-op.
	AActor* Owner = MeshComp ? MeshComp->GetOwner() : nullptr;
	if (UCombatComponent* Combat = Owner ? Owner->FindComponentByClass<UCombatComponent>() : nullptr)
	{
		Combat->SetDodgeInvulnerable(true);
	}
}

void UANS_Invulnerable::NotifyEnd(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, const FAnimNotifyEventReference& EventReference)
{
	Super::NotifyEnd(MeshComp, Animation, EventReference);

	// Interruption can skip this — OnDodgeMontageEnded / ResetForNewRound are
	// the defensive backstops on CombatComponent.
	AActor* Owner = MeshComp ? MeshComp->GetOwner() : nullptr;
	if (UCombatComponent* Combat = Owner ? Owner->FindComponentByClass<UCombatComponent>() : nullptr)
	{
		Combat->SetDodgeInvulnerable(false);
	}
}
