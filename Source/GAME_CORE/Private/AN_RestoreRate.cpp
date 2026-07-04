#include "AN_RestoreRate.h"
#include "Animation/AnimInstance.h"
#include "Components/SkeletalMeshComponent.h"

void UAN_RestoreRate::Notify(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, const FAnimNotifyEventReference& EventReference)
{
	Super::Notify(MeshComp, Animation, EventReference);

	if (!MeshComp) return;

	if (UAnimInstance* AI = MeshComp->GetAnimInstance())
	{
		// Target the montage that OWNS this notify, not GetCurrentActiveMontage():
		// for montage-hosted notifies Animation IS the montage, so this is exact and
		// repeat-safe. GetCurrentActiveMontage() returns the most recently started
		// montage — if an upper-body block/flinch started the same frame on a
		// multi-slot ABP, the old code reset THAT montage's rate (clobbering its
		// authored PlayRate) while the attack stayed stuck at the windup slow-in.
		if (UAnimMontage* OwnerMontage = Cast<UAnimMontage>(Animation))
		{
			AI->Montage_SetPlayRate(OwnerMontage, 1.0f);
		}
	}
}
