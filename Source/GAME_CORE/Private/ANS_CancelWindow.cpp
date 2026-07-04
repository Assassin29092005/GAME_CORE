#include "ANS_CancelWindow.h"
#include "CombatComponent.h"

void UANS_CancelWindow::NotifyBegin(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, float TotalDuration, const FAnimNotifyEventReference& EventReference)
{
	Super::NotifyBegin(MeshComp, Animation, TotalDuration, EventReference);

	AActor* Owner = MeshComp ? MeshComp->GetOwner() : nullptr;
	if (UCombatComponent* Combat = Owner ? Owner->FindComponentByClass<UCombatComponent>() : nullptr)
	{
		// Also drains the buffered-action queue — the feel-critical hookup.
		Combat->SetCancelWindowOpen(true);
	}
}

void UANS_CancelWindow::NotifyEnd(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, const FAnimNotifyEventReference& EventReference)
{
	Super::NotifyEnd(MeshComp, Animation, EventReference);

	// Interruption can skip this — CombatComponent force-clears the flag in
	// PlayComboMontage / OnMontageEnded / ResetCombo as the backstop.
	AActor* Owner = MeshComp ? MeshComp->GetOwner() : nullptr;
	if (UCombatComponent* Combat = Owner ? Owner->FindComponentByClass<UCombatComponent>() : nullptr)
	{
		Combat->SetCancelWindowOpen(false);
	}
}
