#include "ANS_DealDamage.h"
#include "CombatComponent.h"
#include "HitReactionComponent.h"
#include "HitFeedbackComponent.h"
#include "GameFramework/Character.h"
#include "Components/SkeletalMeshComponent.h"
#include "CollisionQueryParams.h"
#include "DrawDebugHelpers.h"

UANS_DealDamage::UANS_DealDamage()
{
	HandSocketName = NAME_None;
	TraceRadius = 30.0f;
	TraceForwardOffset = 120.0f;
	bDrawDebugTrace = false;
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

	// Trace origin: prefer the hand socket if configured (damage requires the
	// fist/weapon to actually reach the target). Fall back to actor center if
	// no socket is set or the socket doesn't exist on the mesh.
	FVector Start;
	FVector End;
	if (!HandSocketName.IsNone() && MeshComp->DoesSocketExist(HandSocketName))
	{
		Start = MeshComp->GetSocketLocation(HandSocketName);
		End   = Start; // socket position IS the contact point — no forward sweep
	}
	else
	{
		Start = OwnerActor->GetActorLocation();
		End   = Start + OwnerActor->GetActorForwardVector() * TraceForwardOffset;
	}

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

#if ENABLE_DRAW_DEBUG
	if (bDrawDebugTrace)
	{
		const FColor TraceColor = bHit ? FColor::Green : FColor::Red;
		DrawDebugSphere(World, Start, TraceRadius, 12, TraceColor, false, 0.1f);
		if ((End - Start).SizeSquared() > KINDA_SMALL_NUMBER)
		{
			DrawDebugSphere(World, End, TraceRadius, 12, TraceColor, false, 0.1f);
			DrawDebugLine(World, Start, End, TraceColor, false, 0.1f, 0, 1.0f);
		}
	}
#endif

	if (!bHit)
	{
		return;
	}

	AActor* HitActor = HitResult.GetActor();
	if (!HitActor) return;

	// Skip non-combat hits (landscape, walls, props). Without this, a swing whose
	// trace grazes the ground caught LandscapeStreamingProxy on its first tick,
	// consumed the per-swing hit token via MarkHitLanded, and never got another
	// chance to hit the boss on later ticks — the symptom was "combo step 3 deals
	// no damage" because Hit3's trace dipped low enough to catch terrain first.
	UCombatComponent* TargetCombat = HitActor->FindComponentByClass<UCombatComponent>();
	if (!TargetCombat) return;

	// Lock out further hits this swing immediately (only after confirming the
	// hit is on a damageable target).
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
	const float TargetHPBefore = TargetCombat ? TargetCombat->CurrentHealth : -1.0f;
	const bool bBlocked = TargetCombat && TargetCombat->IsBlockingAgainst(OwnerActor);

	// A hit on an invulnerable (just-respawned grace window) or already-dead
	// target is a no-op for health. Suppress the flinch + hit-stop too, otherwise
	// the target visibly reacts while its HP bar never moves — the "hit reaction
	// but no damage" confusion. Sampled BEFORE ApplyDamage so a hit that takes the
	// target to 0 still plays its reaction this swing.
	const bool bNoOpHit = TargetCombat && (TargetCombat->IsInvulnerable() || TargetCombat->IsDead());

	if (TargetCombat)
	{
		TargetCombat->ApplyDamage(DamageAmount, OwnerActor, DamageType);
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

	// Trigger hit reaction on the target — unless the hit was blocked (block-impact
	// montage played instead) or it was a no-op hit (invulnerable / dead target).
	UHitReactionComponent* TargetHitReaction = HitActor->FindComponentByClass<UHitReactionComponent>();
	if (TargetHitReaction && !bBlocked && !bNoOpHit)
	{
		TargetHitReaction->PlayHitReaction(OwnerActor, DamageAmount, DamageType);
	}

	// Trigger hit feedback (hit stop, camera shake) — skip on no-op hits so a
	// swing into a respawned/dead target doesn't stutter time for nothing.
	UHitFeedbackComponent* TargetFeedback = HitActor->FindComponentByClass<UHitFeedbackComponent>();
	if (TargetFeedback && !bNoOpHit)
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
