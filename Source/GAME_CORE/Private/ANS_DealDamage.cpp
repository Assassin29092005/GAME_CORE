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

	// Do NOT clear the attacker's per-swing hit guard here. NotifyBegin is NOT
	// guaranteed to fire once per swing: hit-stop pauses/resumes the attacker's montage
	// mid-window (HitFeedbackComponent::PauseAttackerAnim → Montage_Pause/Resume), and
	// the resume re-fires NotifyBegin. Clearing the guard here re-armed damage on every
	// pause cycle and turned one swing into ~25 hits (one-click boss kill). The guard is
	// cleared at true swing starts instead: CombatComponent::PlayComboMontage (hero
	// combos) and BossActionComponent::DoAttack (boss attacks, which bypass that path).
	AActor* Attacker = MeshComp ? MeshComp->GetOwner() : nullptr;
	UCombatComponent* AttackerCombat = Attacker ? Attacker->FindComponentByClass<UCombatComponent>() : nullptr;

	UE_LOG(LogTemp, Log, TEXT("ANS_DealDamage: NotifyBegin — Attacker=%s Anim=%s AttackerCombat=%s"),
		Attacker ? *Attacker->GetName() : TEXT("null"),
		Animation ? *Animation->GetName() : TEXT("null"),
		AttackerCombat ? TEXT("FOUND") : TEXT("NULL"));
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

	// Apply damage to the target's health (instigator enables block checks
	// and the LastHitDirection cache for knockback/ragdoll later).
	UCombatComponent* TargetCombat = HitActor->FindComponentByClass<UCombatComponent>();
	const float TargetHPBefore = TargetCombat ? TargetCombat->CurrentHealth : -1.0f;
	const bool bBlocked = TargetCombat && TargetCombat->IsBlockingAgainst(OwnerActor);
	if (TargetCombat)
	{
		TargetCombat->ApplyDamage(DamageAmount, OwnerActor);
	}

	// LOG: Every successful damage application — if you see >1 of these per NotifyBegin,
	// the per-swing guard is failing and the bug is in this function. If you see exactly 1
	// but HP still drops by more than DamageAmount, the bug is elsewhere (BP-side wiring,
	// duplicate ApplyDamage call, etc).
	UE_LOG(LogTemp, Warning,
		TEXT("ANS_DealDamage: HIT — Attacker=%s Target=%s Dmg=%.1f Type=%s TargetHP %.1f→%.1f GuardWasSet=%d"),
		*OwnerActor->GetName(),
		*HitActor->GetName(),
		DamageAmount,
		*DamageType.ToString(),
		TargetHPBefore,
		TargetCombat ? TargetCombat->CurrentHealth : -1.0f,
		(AttackerCombatGuard && AttackerCombatGuard->bHitLandedThisAttack) ? 1 : 0);

	// Trigger hit reaction on the target — unless the hit was blocked, in which
	// case CombatComponent already played the block-impact montage instead.
	UHitReactionComponent* TargetHitReaction = HitActor->FindComponentByClass<UHitReactionComponent>();
	if (TargetHitReaction && !bBlocked)
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

	UE_LOG(LogTemp, Log, TEXT("ANS_DealDamage: NotifyEnd — Attacker=%s Anim=%s"),
		(MeshComp && MeshComp->GetOwner()) ? *MeshComp->GetOwner()->GetName() : TEXT("null"),
		Animation ? *Animation->GetName() : TEXT("null"));
}
