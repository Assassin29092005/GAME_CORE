#include "CombatStateComponent.h"
#include "Animation/AnimInstance.h"
#include "GameFramework/Character.h"
#include "Components/SkeletalMeshComponent.h"

UCombatStateComponent::UCombatStateComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
}

void UCombatStateComponent::EnterCombat()
{
	if (CurrentState == ECombatState::Combat) return;

	CurrentState = ECombatState::Combat;
	OnCombatStateChanged.Broadcast(CurrentState);

	PlayTransitionMontage(IdleToCombatMontage);
	RefreshCombatTimer();

	UE_LOG(LogTemp, Log, TEXT("CombatState: Entered Combat"));
}

void UCombatStateComponent::ExitCombat()
{
	if (CurrentState == ECombatState::Exploration) return;

	CurrentState = ECombatState::Exploration;
	OnCombatStateChanged.Broadcast(CurrentState);

	PlayTransitionMontage(CombatToIdleMontage);

	UE_LOG(LogTemp, Log, TEXT("CombatState: Exited Combat"));
}

void UCombatStateComponent::RefreshCombatTimer()
{
	UWorld* World = GetWorld();
	if (!World) return;

	World->GetTimerManager().ClearTimer(CombatExitTimerHandle);
	World->GetTimerManager().SetTimer(
		CombatExitTimerHandle,
		this,
		&UCombatStateComponent::ExitCombat,
		CombatExitDelay,
		false
	);
}

void UCombatStateComponent::PlayTransitionMontage(UAnimMontage* Montage)
{
	if (!Montage) return;

	ACharacter* OwnerChar = Cast<ACharacter>(GetOwner());
	if (!OwnerChar || !OwnerChar->GetMesh()) return;

	UAnimInstance* AnimInstance = OwnerChar->GetMesh()->GetAnimInstance();
	if (!AnimInstance) return;

	AnimInstance->Montage_Play(Montage, 1.0f);
}
