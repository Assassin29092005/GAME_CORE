#include "LockOnComponent.h"

#include "CombatCameraComponent.h"
#include "CombatComponent.h"
#include "GameFeelSettings.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"

namespace
{
	// Corpses are not lock-on targets: a minion corpse lingers CorpseLifetime
	// seconds (tag removal on death covers new acquisition, this covers a target
	// that dies WHILE locked and any tagged actor whose CombatComponent is dead).
	bool IsDeadCombatant(const AActor* Actor)
	{
		const UCombatComponent* Combat = Actor ? Actor->FindComponentByClass<UCombatComponent>() : nullptr;
		return Combat && Combat->IsDead();
	}
}

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

	// Drop the lock the moment the target dies — otherwise the DisengageRange
	// hysteresis keeps the camera yawed at a corpse for its whole despawn window
	// while a second live enemy attacks from off-screen.
	if (LockedTarget && IsDeadCombatant(LockedTarget))
	{
		LockedTarget = nullptr;
	}

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
		if (IsDeadCombatant(A)) continue;   // never acquire a corpse
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

	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();

	// Bias, never override (guide 5.2): the moment the player touches the look
	// input the correction yields entirely; at zero input it runs at full rate.
	const float LookInputMagnitude = UCombatCameraComponent::ComputeLookInputMagnitude(PC);
	const float BaseInterpSpeed = bOverrideInterpSpeed ? YawInterpRate : Settings->LockOnInterpSpeed;
	const float InterpSpeed = BaseInterpSpeed * (1.0f - FMath::Clamp(LookInputMagnitude, 0.0f, 1.0f));
	if (InterpSpeed <= KINDA_SMALL_NUMBER) return; // player is steering — do not fight the stick

	const FRotator CurrentRot = PC->GetControlRotation();
	const FRotator RawDesired = ToTarget.Rotation();
	// Yaw tracks the target; pitch frames slightly above the target's root
	// (guide 5.2 step 3). Because the whole correction yields to look input,
	// the player can still tilt freely — framing only drifts back when idle.
	// RInterpTo handles 359 → 1 wrap correctly, whereas a per-axis FInterpTo
	// would lerp the long way around.
	const FRotator Desired(
		FMath::Clamp(RawDesired.Pitch + Settings->LockOnPitchOffset, Settings->LockOnPitchMin, Settings->LockOnPitchMax),
		RawDesired.Yaw,
		CurrentRot.Roll);
	const FRotator NewRot = FMath::RInterpTo(CurrentRot, Desired, DeltaTime, InterpSpeed);

	PC->SetControlRotation(NewRot);
}
