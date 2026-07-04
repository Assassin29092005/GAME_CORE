#include "MinionAIController.h"
#include "NPCMinionCharacter.h"
#include "CombatComponent.h"
#include "HitReactionComponent.h"
#include "AITypes.h"
#include "BehaviorTree/BehaviorTree.h"
#include "BehaviorTree/BlackboardComponent.h"
#include "Navigation/PathFollowingComponent.h"
#include "Kismet/GameplayStatics.h"
#include "TimerManager.h"

const FName AMinionAIController::TargetActorKey(TEXT("TargetActor"));
const FName AMinionAIController::DistanceToTargetKey(TEXT("DistanceToTarget"));
const FName AMinionAIController::CanActKey(TEXT("bCanAct"));
const FName AMinionAIController::TargetDeadKey(TEXT("bTargetDead"));
const FName AMinionAIController::HomeLocationKey(TEXT("HomeLocation"));
const FName AMinionAIController::PatrolLocationKey(TEXT("PatrolLocation"));

bool AMinionAIController::ComputeCanAct(const APawn* Pawn)
{
	if (!Pawn)
	{
		return false;
	}

	// Re-fetched every call, never cached: minion corpses destroy their combat
	// components deferred (next tick after death), so any held pointer dangles.
	const UCombatComponent* Combat = Pawn->FindComponentByClass<UCombatComponent>();
	const UHitReactionComponent* HitReaction = Pawn->FindComponentByClass<UHitReactionComponent>();

	// Same lockout the boss applies in BossActionComponent::ExecuteActionEnum.
	// IsReacting() covers the flinch montage PLUS the grace period.
	return Combat
		&& !Combat->IsDead()
		&& !Combat->IsAttacking()
		&& (!HitReaction || !HitReaction->IsReacting());
}

void AMinionAIController::OnPossess(APawn* InPawn)
{
	Super::OnPossess(InPawn);

	// Re-possess safety: never stack a fallback timer on top of an old one.
	StopBrain();

	if (!BehaviorTreeAsset)
	{
		UE_LOG(LogTemp, Warning,
			TEXT("MinionAIController[%s]: no BT assigned — running built-in fallback brain; author a BehaviorTree asset to override."),
			*GetName());

		// Same anchor the BT path seeds into the HomeLocation blackboard key.
		FallbackHomeLocation = InPawn ? InPawn->GetActorLocation() : FVector::ZeroVector;
		FallbackPatrolDestination = FAISystem::InvalidLocation;

		// Jittered first think de-syncs minion packs, mirroring the BT
		// service's RandomDeviation.
		GetWorldTimerManager().SetTimer(
			FallbackBrainTimerHandle, this, &AMinionAIController::TickFallbackBrain,
			FallbackBrainInterval, /*bLoop=*/true,
			/*FirstDelay=*/FMath::FRandRange(0.0f, FallbackBrainInterval));
		return;
	}

	// RunBehaviorTree also spins up the blackboard from the tree's BlackboardAsset.
	RunBehaviorTree(BehaviorTreeAsset);

	// Seed the anchor keys. HomeLocation is the possess-time (spawn) spot; the
	// patrol destination starts there until the service picks a patrol point.
	if (UBlackboardComponent* BB = GetBlackboardComponent())
	{
		if (InPawn)
		{
			BB->SetValueAsVector(HomeLocationKey, InPawn->GetActorLocation());
			BB->SetValueAsVector(PatrolLocationKey, InPawn->GetActorLocation());
		}
	}
}

void AMinionAIController::OnUnPossess()
{
	StopBrain();
	Super::OnUnPossess();
}

void AMinionAIController::StopBrain()
{
	if (!FallbackBrainTimerHandle.IsValid())
	{
		return;
	}

	if (UWorld* World = GetWorld())
	{
		World->GetTimerManager().ClearTimer(FallbackBrainTimerHandle);
	}
	FallbackBrainTimerHandle.Invalidate();

	// AAIController::StopMovement / ClearFocus are pawn-null safe.
	StopMovement();
	ClearFocus(EAIFocusPriority::Gameplay);
}

void AMinionAIController::TickFallbackBrain()
{
	APawn* MinionPawn = GetPawn();
	if (!MinionPawn)
	{
		// Detached (death path calls DetachFromControllerPendingDestroy) — done.
		StopBrain();
		return;
	}

	// Re-fetch components every think — corpse components are destroyed deferred.
	UCombatComponent* Combat = MinionPawn->FindComponentByClass<UCombatComponent>();
	if (!Combat || Combat->IsDead())
	{
		StopBrain();
		return;
	}

	// Target: always player 0 — same rule as BTService_MinionCombatState. A pawn
	// without a CombatComponent (PIE eject/spectator/default pawn) is not a valid
	// target either; fall through to patrol instead of chasing the undamageable.
	APawn* Hero = UGameplayStatics::GetPlayerPawn(this, 0);
	UCombatComponent* HeroCombat = Hero ? Hero->FindComponentByClass<UCombatComponent>() : nullptr;
	const bool bTargetValid = Hero && HeroCombat && !HeroCombat->IsDead();

	if (!bTargetValid)
	{
		ClearFocus(EAIFocusPriority::Gameplay);
		FallbackPatrol(*MinionPawn);
		return;
	}

	// 2D on purpose: UPathFollowingComponent's reach test is 2D, so a 3D gate
	// here would widen the chase/attack dead zone on slopes and steps.
	const float Dist = FVector::Dist2D(MinionPawn->GetActorLocation(), Hero->GetActorLocation());

	if (Dist <= AttackRange)
	{
		// In striking range: plant, face the hero, swing when the shared gate
		// allows. Public CombatComponent API ONLY — RequestAttack routes
		// PlayComboMontage, which clears the per-swing hit guard at the TRUE
		// swing start (project rule: never bypass that).
		StopMovement();
		FallbackPatrolDestination = FAISystem::InvalidLocation;
		SetFocus(Hero, EAIFocusPriority::Gameplay);

		if (ComputeCanAct(MinionPawn))
		{
			Combat->RequestAttack();
		}
	}
	else if (Dist <= AggroRange)
	{
		// Chase. Only issue a fresh move request when idle or the goal changed —
		// re-calling MoveToActor every 0.2s would restart pathfollowing each
		// think (AAIController::MoveTo builds a new request unless AlreadyAtGoal).
		// A goal-actor move request repaths automatically as the hero moves.
		const UPathFollowingComponent* PFC = GetPathFollowingComponent();
		const bool bAlreadyChasingHero =
			PFC && PFC->GetStatus() == EPathFollowingStatus::Moving && PFC->GetMoveGoal() == Hero;
		if (!bAlreadyChasingHero)
		{
			// Explicit request instead of MoveToActor: the MoveToActor defaults
			// (bStopOnOverlap -> reach test includes agent radius, plus goal
			// radius) inflate the effective arrival distance by both capsule
			// radii (~70-90cm), which can meet or exceed AttackRange — the move
			// then finishes (or short-circuits AlreadyAtGoal) OUTSIDE swing
			// range and the brain deadlocks ~2.5m from a stationary hero.
			// Radius inflation off + acceptance strictly tighter than
			// AttackRange guarantees arrival lands inside the attack gate.
			FAIMoveRequest ChaseRequest(Hero);
			ChaseRequest.SetAcceptanceRadius(FMath::Max(50.0f, AttackRange - 100.0f));
			ChaseRequest.SetReachTestIncludesAgentRadius(false);
			ChaseRequest.SetReachTestIncludesGoalRadius(false);
			MoveTo(ChaseRequest);
			FallbackPatrolDestination = FAISystem::InvalidLocation;
		}

		// Face the hero while close; farther out, dropping focus lets
		// UpdateControlRotation fall back to move direction (look where we walk).
		if (Dist <= FallbackFocusRange)
		{
			SetFocus(Hero, EAIFocusPriority::Gameplay);
		}
		else
		{
			ClearFocus(EAIFocusPriority::Gameplay);
		}
	}
	else
	{
		ClearFocus(EAIFocusPriority::Gameplay);
		FallbackPatrol(*MinionPawn);
	}
}

void AMinionAIController::FallbackPatrol(APawn& MinionPawn)
{
	// Same cycling logic the BT service feeds into the PatrolLocation key —
	// shared helper on the pawn, so route progress (CurrentPatrolIndex) stays in
	// one place whichever brain is driving.
	FVector Dest = FallbackHomeLocation;
	if (ANPCMinionCharacter* Minion = Cast<ANPCMinionCharacter>(&MinionPawn))
	{
		Dest = Minion->AdvancePatrolAndGetDestination(FallbackHomeLocation, FallbackPatrolAcceptanceRadius);
	}

	// Re-issue the move only when the destination changed, or when we're idle
	// but NOT already standing at the point (the genuine retry case for a
	// failed/blocked move). Without the distance check, a minion resting at an
	// empty-route home spot is Idle every think and re-issues MoveToLocation
	// 5x/s forever — each call a navmesh projection plus an instant
	// AlreadyAtGoal finish. The acceptance here is deliberately tighter than
	// the route-advance radius so the helper (not pathfollowing) decides when
	// a point counts as reached.
	const bool bNewDestination = !Dest.Equals(FallbackPatrolDestination, 1.0f);
	const bool bIdleShortOfDest =
		GetMoveStatus() == EPathFollowingStatus::Idle &&
		FVector::Dist2D(MinionPawn.GetActorLocation(), Dest) > FallbackPatrolAcceptanceRadius;
	if (bNewDestination || bIdleShortOfDest)
	{
		MoveToLocation(Dest, /*AcceptanceRadius=*/50.0f);
		FallbackPatrolDestination = Dest;
	}
}
