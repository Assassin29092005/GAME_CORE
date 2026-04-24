#include "ANS_DealDamage.h"
#include "CombatComponent.h"
#include "HitReactionComponent.h"
#include "HitFeedbackComponent.h"
#include "GameFramework/Character.h"
#include "Components/SkeletalMeshComponent.h"
#include "CollisionQueryParams.h"

UANS_DealDamage::UANS_DealDamage()
{
	TraceRadius = 80.0f;
	TraceForwardOffset = 120.0f;
	bHasHitThisSwing = false;
}

void UANS_DealDamage::NotifyBegin(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, float TotalDuration, const FAnimNotifyEventReference& EventReference)
{
	Super::NotifyBegin(MeshComp, Animation, TotalDuration, EventReference);
	bHasHitThisSwing = false;

}

void UANS_DealDamage::NotifyTick(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, float FrameDeltaTime, const FAnimNotifyEventReference& EventReference)
{
	Super::NotifyTick(MeshComp, Animation, FrameDeltaTime, EventReference);

	if (!MeshComp) return;

	AActor* OwnerActor = MeshComp->GetOwner();
	if (!OwnerActor) return;

	// Use CombatComponent on the ATTACKER to guard one hit per swing.
	// This is more reliable than a notify-state instance bool in UE5.
	UCombatComponent* AttackerCombatGuard = OwnerActor->FindComponentByClass<UCombatComponent>();
	if (AttackerCombatGuard && AttackerCombatGuard->bHitLandedThisAttack) return;

	UWorld* World = OwnerActor->GetWorld();
	if (!World) return;

	// Sphere trace in front of the attacker
	const FVector Start = OwnerActor->GetActorLocation();
	const FVector End = Start + OwnerActor->GetActorForwardVector() * TraceForwardOffset;

	FCollisionQueryParams QueryParams;
	QueryParams.AddIgnoredActor(OwnerActor);

	FHitResult HitResult;
	const bool bHit = World->SweepSingleByChannel(
		HitResult,
		Start,
		End,
		FQuat::Identity,
		ECC_Pawn,
		FCollisionShape::MakeSphere(TraceRadius),
		QueryParams
	);

	if (!bHit)
	{
		// Uncomment to spam-debug misses: UE_LOG(LogTemp, Verbose, TEXT("ANS_DealDamage: No hit this tick"));
		return;
	}

	AActor* HitActor = HitResult.GetActor();
	if (!HitActor) return;

	// Lock out further hits this swing immediately
	if (AttackerCombatGuard)
	{
		AttackerCombatGuard->MarkHitLanded();
	}

	// Look up damage from the attacker's current combo step
	float DamageAmount = 10.0f;
	FName DamageType = FName(TEXT("Light"));

	if (AttackerCombatGuard && AttackerCombatGuard->CombatConfig)
	{
		const FAttackAnimData* AttackData = AttackerCombatGuard->CombatConfig->GetAttackData(AttackerCombatGuard->GetComboStep());
		if (AttackData)
		{
			DamageAmount = AttackData->DamageAmount;
			DamageType = AttackData->DamageType;
		}

		// Broadcast that this attack landed (for PlayerProfileComponent tracking)
		AttackerCombatGuard->OnAttackLanded.Broadcast(DamageAmount, DamageType);
	}

	// Apply damage to the target's health
	UCombatComponent* TargetCombat = HitActor->FindComponentByClass<UCombatComponent>();
	if (TargetCombat)
	{
		TargetCombat->ApplyDamage(DamageAmount);
	}

	// Trigger hit reaction on the target
	UHitReactionComponent* TargetHitReaction = HitActor->FindComponentByClass<UHitReactionComponent>();
	if (TargetHitReaction)
	{
		TargetHitReaction->PlayHitReaction(OwnerActor, DamageAmount, DamageType);
	}

	// Trigger hit feedback (hit stop, camera shake)
	UHitFeedbackComponent* TargetFeedback = HitActor->FindComponentByClass<UHitFeedbackComponent>();
	if (TargetFeedback)
	{
		TargetFeedback->TriggerHitFeedback(OwnerActor);
	}
}

void UANS_DealDamage::NotifyEnd(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, const FAnimNotifyEventReference& EventReference)
{
	Super::NotifyEnd(MeshComp, Animation, EventReference);
	bHasHitThisSwing = false;
}
