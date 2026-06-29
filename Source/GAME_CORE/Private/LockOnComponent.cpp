#include "LockOnComponent.h"

#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"

ULockOnComponent::ULockOnComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
}

void ULockOnComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	AActor* Owner = GetOwner();
	if (!Owner) return;

	APawn* Pawn = Cast<APawn>(Owner);
	if (!Pawn) return;

	// Only engage when this pawn is the locally controlled player. AI bots
	// driving the hero (AutoHeroComponent personas) don't need camera lock-on.
	APlayerController* PC = Cast<APlayerController>(Pawn->GetController());
	if (!PC) return;

	// Hysteresis: if we already have a target, hold it until it exits the wider
	// DisengageRange. Stops the lock from flickering at the boundary.
	if (LockedTarget)
	{
		const float Dist = FVector::Dist(Owner->GetActorLocation(), LockedTarget->GetActorLocation());
		if (Dist > DisengageRange)
		{
			LockedTarget = nullptr;
		}
	}

	if (!LockedTarget)
	{
		AActor* Candidate = FindNearestEnemy();
		if (Candidate && FVector::Dist(Owner->GetActorLocation(), Candidate->GetActorLocation()) <= LockOnRange)
		{
			LockedTarget = Candidate;
		}
	}

	if (LockedTarget)
	{
		UpdateControllerRotation(DeltaTime);
	}
}

AActor* ULockOnComponent::FindNearestEnemy() const
{
	AActor* Owner = GetOwner();
	if (!Owner || EnemyTag.IsNone()) return nullptr;

	TArray<AActor*> Candidates;
	UGameplayStatics::GetAllActorsWithTag(this, EnemyTag, Candidates);

	const FVector OwnerLoc = Owner->GetActorLocation();
	AActor* Best = nullptr;
	float BestDistSq = TNumericLimits<float>::Max();
	for (AActor* A : Candidates)
	{
		if (!A || A == Owner) continue;
		const float DistSq = FVector::DistSquared(OwnerLoc, A->GetActorLocation());
		if (DistSq < BestDistSq)
		{
			BestDistSq = DistSq;
			Best = A;
		}
	}
	return Best;
}

void ULockOnComponent::UpdateControllerRotation(float DeltaTime)
{
	AActor* Owner = GetOwner();
	APawn* Pawn = Cast<APawn>(Owner);
	if (!Pawn || !LockedTarget) return;

	APlayerController* PC = Cast<APlayerController>(Pawn->GetController());
	if (!PC) return;

	const FVector ToTarget = LockedTarget->GetActorLocation() - Owner->GetActorLocation();
	if (ToTarget.IsNearlyZero()) return;

	const FRotator CurrentRot = PC->GetControlRotation();
	// Only override YAW. Pitch stays under player control so they can still
	// tilt the camera up/down. RInterpTo handles 359 → 1 wrap correctly,
	// whereas a per-axis FInterpTo would lerp the long way around.
	const FRotator Desired(CurrentRot.Pitch, ToTarget.Rotation().Yaw, CurrentRot.Roll);
	const FRotator NewRot = FMath::RInterpTo(CurrentRot, Desired, DeltaTime, YawInterpRate);

	PC->SetControlRotation(NewRot);
}
