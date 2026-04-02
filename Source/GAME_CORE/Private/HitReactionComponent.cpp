#include "HitReactionComponent.h"
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

	AnimInstance->Montage_Play(Montage, ReactionSet.PlayRate);

	UE_LOG(LogTemp, Log, TEXT("HitReaction: Direction=%d, Intensity=%d, Stagger=%.1f"),
		static_cast<int32>(Direction), static_cast<int32>(Intensity), CurrentStagger);
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
