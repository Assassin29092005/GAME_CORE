#include "HitReactionComponent.h"
#include "CombatComponent.h"
#include "Animation/AnimInstance.h"
#include "GameFramework/Character.h"
#include "Components/SkeletalMeshComponent.h"

UAnimMontage* FDirectionalHitReaction::GetMontageForDirection(EHitDirection Direction) const
{
	switch (Direction)
	{
	case EHitDirection::Front: return HitFront;
	case EHitDirection::Back:  return HitBack;
	case EHitDirection::Left:  return HitLeft;
	case EHitDirection::Right: return HitRight;
	default: return HitFront;
	}
}

UHitReactionComponent::UHitReactionComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.bStartWithTickEnabled = true;
}

void UHitReactionComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	// Decay stagger over time
	if (CurrentStagger > 0.0f)
	{
		CurrentStagger = FMath::Max(0.0f, CurrentStagger - StaggerDecayRate * DeltaTime);
	}
}

void UHitReactionComponent::PlayHitReaction(AActor* InstigatorActor, float DamageAmount, FName DamageType)
{
	// Broadcast before processing so profile tracking can record this hit
	OnHitReactionTriggered.Broadcast(InstigatorActor, DamageAmount, DamageType);

	AActor* Owner = GetOwner();
	if (!Owner) return;

	// Don't play hit reactions on a dead actor — death montage takes priority
	UCombatComponent* CombatComp = Owner->FindComponentByClass<UCombatComponent>();
	if (CombatComp && CombatComp->bIsDead) return;

	USkeletalMeshComponent* Mesh = Owner->FindComponentByClass<USkeletalMeshComponent>();
	if (!Mesh) return;

	UAnimInstance* AnimInstance = Mesh->GetAnimInstance();
	if (!AnimInstance) return;

	// Determine intensity before accumulating, so the current hit doesn't
	// immediately escalate its own reaction
	EStaggerIntensity Intensity = DetermineStaggerIntensity(DamageAmount, DamageType);

	// Accumulate stagger after intensity determination
	CurrentStagger += DamageAmount;

	// Combo finisher triggers knockback
	if (DamageType == FName(TEXT("ComboFinisher")) && KnockbackMontage)
	{
		AnimInstance->Montage_Play(KnockbackMontage, 1.0f);
		CurrentStagger = 0.0f;
		UE_LOG(LogTemp, Log, TEXT("HitReaction: Knockback triggered"));
		return;
	}

	EHitDirection Direction = CalculateHitDirection(InstigatorActor);
	const FDirectionalHitReaction& ReactionSet = GetReactionSet(Intensity);

	UAnimMontage* Montage = ReactionSet.GetMontageForDirection(Direction);
	if (!Montage) return;

	// NOTE: Blend times are set on the shared montage asset. Safe as long as
	// each intensity/direction uses a unique montage.
	Montage->BlendIn.SetBlendTime(ReactionSet.BlendInTime);
	Montage->BlendOut.SetBlendTime(ReactionSet.BlendOutTime);

	const float Duration = AnimInstance->Montage_Play(Montage, ReactionSet.PlayRate);

	if (Duration > 0.0f)
	{
		bIsReacting = true;
		CurrentReactionMontage = Montage;

		// Bind end delegate AFTER Montage_Play so the montage instance exists.
		// We use this to clear bIsReacting so BossActionComponent re-enables RL actions.
		FOnMontageEnded EndDelegate;
		EndDelegate.BindUObject(this, &UHitReactionComponent::OnHitReactionMontageEnded);
		AnimInstance->Montage_SetEndDelegate(EndDelegate, Montage);
	}

	UE_LOG(LogTemp, Log, TEXT("HitReaction: Direction=%d, Intensity=%d, Stagger=%.1f"),
		static_cast<int32>(Direction), static_cast<int32>(Intensity), CurrentStagger);
}

void UHitReactionComponent::OnHitReactionMontageEnded(UAnimMontage* Montage, bool bInterrupted)
{
	// Ignore stale callbacks from a previous reaction that got interrupted by a newer one
	// (Montage_SetEndDelegate is per-montage, but a bind from a prior call can still fire late).
	if (Montage != CurrentReactionMontage)
	{
		return;
	}

	bIsReacting = false;
	CurrentReactionMontage = nullptr;

	// Record when the reaction finished so IsReacting() can keep returning true for
	// HitReactionGracePeriod seconds — otherwise the next bridge action (~67ms cadence)
	// fires in the gap and the boss visibly pops into Dodge/Attack mid-combo.
	if (UWorld* World = GetWorld())
	{
		LastReactionEndTime = World->GetTimeSeconds();
	}
}

bool UHitReactionComponent::IsReacting() const
{
	if (bIsReacting) return true;

	if (HitReactionGracePeriod <= 0.0f) return false;

	const UWorld* World = GetWorld();
	if (!World) return false;

	return (World->GetTimeSeconds() - LastReactionEndTime) < HitReactionGracePeriod;
}

void UHitReactionComponent::ResetForNewRound()
{
	CurrentStagger = 0.0f;
	bIsReacting = false;
	CurrentReactionMontage = nullptr;
	// Push the end time far into the past so the grace period is already expired
	// at the start of the new round.
	LastReactionEndTime = -1000.0f;
}

EHitDirection UHitReactionComponent::CalculateHitDirection(AActor* InstigatorActor) const
{
	if (!InstigatorActor || !GetOwner()) return EHitDirection::Front;

	const FVector OwnerForward = GetOwner()->GetActorForwardVector();
	const FVector OwnerRight = GetOwner()->GetActorRightVector();
	const FVector ToInstigator = (InstigatorActor->GetActorLocation() - GetOwner()->GetActorLocation()).GetSafeNormal();

	const float ForwardDot = FVector::DotProduct(OwnerForward, ToInstigator);
	const float RightDot = FVector::DotProduct(OwnerRight, ToInstigator);

	// Determine primary axis
	if (FMath::Abs(ForwardDot) > FMath::Abs(RightDot))
	{
		return ForwardDot > 0.0f ? EHitDirection::Front : EHitDirection::Back;
	}
	else
	{
		return RightDot > 0.0f ? EHitDirection::Right : EHitDirection::Left;
	}
}

EStaggerIntensity UHitReactionComponent::DetermineStaggerIntensity(float DamageAmount, FName DamageType) const
{
	// Heavy damage type always triggers heavy reaction
	if (DamageType == FName(TEXT("Heavy")))
	{
		return EStaggerIntensity::Heavy;
	}

	// Otherwise use accumulated stagger
	if (CurrentStagger >= HeavyStaggerThreshold)
	{
		return EStaggerIntensity::Heavy;
	}
	else if (CurrentStagger >= MediumStaggerThreshold)
	{
		return EStaggerIntensity::Medium;
	}

	return EStaggerIntensity::Light;
}

const FDirectionalHitReaction& UHitReactionComponent::GetReactionSet(EStaggerIntensity Intensity) const
{
	switch (Intensity)
	{
	case EStaggerIntensity::Heavy:  return HeavyHitReactions;
	case EStaggerIntensity::Medium: return MediumHitReactions;
	default: return LightHitReactions;
	}
}
