#include "BTService_MinionCombatState.h"
#include "MinionAIController.h"
#include "NPCMinionCharacter.h"
#include "CombatComponent.h"
#include "HitReactionComponent.h"
#include "AIController.h"
#include "BehaviorTree/BlackboardComponent.h"
#include "Kismet/GameplayStatics.h"

UBTService_MinionCombatState::UBTService_MinionCombatState()
{
	NodeName = TEXT("Minion Combat State");
	Interval = 0.2f;
	RandomDeviation = 0.05f;   // de-sync multiple minions so they don't tick in lockstep
}

void UBTService_MinionCombatState::TickNode(UBehaviorTreeComponent& OwnerComp, uint8* NodeMemory, float DeltaSeconds)
{
	Super::TickNode(OwnerComp, NodeMemory, DeltaSeconds);

	AAIController* AICon = OwnerComp.GetAIOwner();
	APawn* Pawn = AICon ? AICon->GetPawn() : nullptr;
	UBlackboardComponent* BB = OwnerComp.GetBlackboardComponent();
	if (!AICon || !Pawn || !BB) return;

	UCombatComponent* Combat = Pawn->FindComponentByClass<UCombatComponent>();

	// --- Self gate (mirrors BossActionComponent::ExecuteActionEnum's lockout).
	// Shared with BTDecorator_MinionCanAct and the controller's fallback brain. ---
	const bool bSelfAlive = Combat && !Combat->IsDead();
	const bool bCanAct = AMinionAIController::ComputeCanAct(Pawn);
	BB->SetValueAsBool(AMinionAIController::CanActKey, bCanAct);

	// --- Target: always player 0. Minions exist to pressure the hero (and feed
	// the boss's dossier through the hero's own PlayerProfileComponent). ---
	APawn* Hero = UGameplayStatics::GetPlayerPawn(Pawn, 0);
	UCombatComponent* HeroCombat = Hero ? Hero->FindComponentByClass<UCombatComponent>() : nullptr;
	// A pawn WITHOUT a CombatComponent is not a valid target either (PIE
	// eject/spectator pawn, default pawn before BP_NeuralHero possession, future
	// menu/photo-mode pawn) — otherwise minions chase and swing at something
	// ANS_DealDamage can never damage instead of falling back to patrol.
	const bool bTargetDead = !Hero || !HeroCombat || HeroCombat->IsDead();
	BB->SetValueAsBool(AMinionAIController::TargetDeadKey, bTargetDead);

	if (bTargetDead || !bSelfAlive)
	{
		BB->ClearValue(AMinionAIController::TargetActorKey);
		// Reset the distance key too so distance-gated branches ("Dist <
		// AttackRange" + CanAct) fail CLOSED — leaving the last in-combat value
		// (e.g. 150cm) frozen kept minions swinging at air over the hero's
		// corpse for the whole death/reset window.
		BB->SetValueAsFloat(AMinionAIController::DistanceToTargetKey, TNumericLimits<float>::Max());
		AICon->ClearFocus(EAIFocusPriority::Gameplay);
	}
	else
	{
		BB->SetValueAsObject(AMinionAIController::TargetActorKey, Hero);

		const float Dist = FVector::Dist(Pawn->GetActorLocation(), Hero->GetActorLocation());
		BB->SetValueAsFloat(AMinionAIController::DistanceToTargetKey, Dist);

		// Face the hero while in combat range; outside it, dropping focus lets
		// AAIController::UpdateControlRotation fall back to the move direction,
		// so patrolling minions look where they walk.
		if (Dist <= FocusRange)
		{
			AICon->SetFocus(Hero, EAIFocusPriority::Gameplay);
		}
		else
		{
			AICon->ClearFocus(EAIFocusPriority::Gameplay);
		}
	}

	// --- Patrol destination for the stock BTTask_MoveTo (cycling logic shared
	// with the controller's fallback brain via the pawn helper) ---
	FVector PatrolDest = BB->GetValueAsVector(AMinionAIController::HomeLocationKey);
	if (ANPCMinionCharacter* Minion = Cast<ANPCMinionCharacter>(Pawn))
	{
		PatrolDest = Minion->AdvancePatrolAndGetDestination(PatrolDest, PatrolAcceptanceRadius);
	}
	BB->SetValueAsVector(AMinionAIController::PatrolLocationKey, PatrolDest);
}
