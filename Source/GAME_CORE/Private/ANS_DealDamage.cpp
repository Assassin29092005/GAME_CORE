#include "ANS_DealDamage.h"
#include "CombatComponent.h"
#include "HitReactionComponent.h"
#include "HitFeedbackComponent.h"
#include "GameFramework/Character.h"
#include "Components/SkeletalMeshComponent.h"
#include "CollisionQueryParams.h"
#include "DrawDebugHelpers.h"
#include "EngineUtils.h"
#include "GameFramework/Pawn.h"

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

	// Faction = the "Enemy" actor tag (project convention: BP_Boss and minions
	// carry it, the hero doesn't). Two actors on the same side of that test are
	// teammates and must neither take nor absorb this swing.
	static const FName EnemyFactionTag(TEXT("Enemy"));
	const bool bOwnerIsEnemyFaction = OwnerActor->ActorHasTag(EnemyFactionTag);

	FCollisionQueryParams QueryParams;
	QueryParams.AddIgnoredActor(OwnerActor);

	// Ignore ALL same-team pawns so a friendly capsule can't BLOCK the sweep and
	// shadow the real target standing behind it (a blocking hit ends even a
	// multi-sweep). With several minions crowding one hero this is routine.
	for (TActorIterator<APawn> PawnIt(World); PawnIt; ++PawnIt)
	{
		APawn* OtherPawn = *PawnIt;
		if (OtherPawn && OtherPawn != OwnerActor
			&& OtherPawn->ActorHasTag(EnemyFactionTag) == bOwnerIsEnemyFaction)
		{
			QueryParams.AddIgnoredActor(OtherPawn);
		}
	}

	// SweepMulti, not SweepSingle: with several same-team pawns in play (the
	// minion encounters), a friendly body inside the sphere must not SHADOW the
	// real target — the sweep has to be able to look past allies. SweepSingle
	// let minion B eat minion A's swing (friendly fire) AND consume A's per-swing
	// hit token, so the hero took nothing that swing.
	TArray<FHitResult> HitResults;
	const bool bHit = World->SweepMultiByChannel(
		HitResults,
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

	// Pick the first HOSTILE, damageable actor along the sweep.
	// - Same-faction hits are skipped (belt-and-braces on top of the ignore list
	//   above): minion↔minion and minion↔boss hits never land, so packed minions
	//   can't whittle each other down or inject damage the RL bridge never chose.
	// - Skip non-combat hits (landscape, walls, props). Without this, a swing
	//   whose trace grazed the ground caught LandscapeStreamingProxy on its first
	//   tick, consumed the per-swing hit token via MarkHitLanded, and never got
	//   another chance to hit the boss on later ticks — the symptom was "combo
	//   step 3 deals no damage".
	// MarkHitLanded only fires once a confirmed hostile target is found, so a
	// friendly/prop overlap never steals the swing token.
	AActor* HitActor = nullptr;
	UCombatComponent* TargetCombat = nullptr;
	for (const FHitResult& Hit : HitResults)
	{
		AActor* Candidate = Hit.GetActor();
		if (!Candidate) continue;

		// Same team — friendly bodies don't take (or absorb) the hit.
		if (Candidate->ActorHasTag(EnemyFactionTag) == bOwnerIsEnemyFaction) continue;

		UCombatComponent* CandidateCombat = Candidate->FindComponentByClass<UCombatComponent>();
		if (!CandidateCombat) continue;

		HitActor = Candidate;
		TargetCombat = CandidateCombat;
		break;
	}
	if (!HitActor || !TargetCombat) return;

	// Lock out further hits this swing immediately (only after confirming the
	// hit is on a damageable target).
	if (AttackerCombatGuard)
	{
		AttackerCombatGuard->MarkHitLanded();
	}

	// Look up damage from the attacker's current combo step. AttackData is kept
	// in scope past this block — the hit-feedback call site below reads its
	// per-attack HitStopDuration/CameraShakeScale (guide.md 3.4).
	float DamageAmount = 10.0f;
	FName DamageType = FName(TEXT("Light"));
	const FAttackAnimData* AttackData = nullptr;

	if (AttackerCombatGuard && AttackerCombatGuard->CombatConfig)
	{
		AttackData = AttackerCombatGuard->CombatConfig->GetAttackData(AttackerCombatGuard->GetComboStep());
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

	// A hit on an invulnerable (just-respawned grace window OR mid-dodge i-frames)
	// or already-dead target is a no-op for health. Suppress the flinch + hit-stop
	// too, otherwise the target visibly reacts while its HP bar never moves — the
	// "hit reaction but no damage" confusion (and a flinch would interrupt the
	// dodge the i-frames just rewarded). Sampled BEFORE ApplyDamage so a hit that
	// takes the target to 0 still plays its reaction this swing.
	const bool bNoOpHit = TargetCombat && (TargetCombat->IsInvulnerable() || TargetCombat->IsDodgeInvulnerable() || TargetCombat->IsDead());

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

	// Trigger hit feedback (hit stop, camera shake, impact sound) — skip on no-op
	// hits so a swing into a respawned/dead target doesn't stutter time for
	// nothing, and skip on BLOCKED hits so a block doesn't read/sound identical
	// to a clean flesh hit (the block montage + CombatComponent::BlockSound thud
	// played inside ApplyDamage ARE the blocked-hit feedback).
	// Weight is per-attack data (guide.md 3.4): chain finishers route through the
	// heavy tier so they VISIBLY hit harder than openers; every other attack
	// passes its FAttackAnimData feedback numbers through. Single-entry chains
	// (boss/minion one-swing configs) are openers, not finishers — without the
	// length check every boss hit would read as a finisher.
	UHitFeedbackComponent* TargetFeedback = HitActor->FindComponentByClass<UHitFeedbackComponent>();
	if (TargetFeedback && !bNoOpHit && !bBlocked)
	{
		const bool bComboFinisher = AttackerCombatGuard && AttackerCombatGuard->CombatConfig
			&& AttackerCombatGuard->CombatConfig->GetComboLength() > 1
			&& AttackerCombatGuard->GetComboStep() == AttackerCombatGuard->CombatConfig->GetComboLength() - 1;

		if (bComboFinisher)
		{
			TargetFeedback->TriggerHeavyHitFeedback(OwnerActor);
		}
		else if (AttackData)
		{
			TargetFeedback->TriggerHitFeedback(OwnerActor, AttackData->HitStopDuration, AttackData->CameraShakeScale);
		}
		else
		{
			TargetFeedback->TriggerHitFeedback(OwnerActor);
		}
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
