#pragma once

#include "CoreMinimal.h"
#include "BehaviorTree/BTService.h"
#include "BTService_MinionCombatState.generated.h"

/**
 * Blackboard feeder for the minion BT (keys documented on AMinionAIController).
 * Runs at ~0.2s intervals on the BT root:
 *
 * - TargetActor / DistanceToTarget / bTargetDead from GetPlayerPawn(0) + its
 *   CombatComponent (target cleared while the hero is dead so combat branches
 *   fall through to patrol).
 * - bCanAct = !HitReaction->IsReacting() && !Combat->IsDead() &&
 *   !Combat->IsAttacking() — the same lockout the boss applies in
 *   BossActionComponent::ExecuteActionEnum. IsReacting() covers the flinch
 *   montage PLUS the grace period, so the minion can't attack mid-stunlock.
 * - SetFocus(hero) while within FocusRange (facing: the minion character runs
 *   bUseControllerRotationYaw=false + bUseControllerDesiredRotation=true, so
 *   focus-driven control rotation is smoothly interpolated onto the pawn by
 *   CharacterMovement — no orient-to-movement fighting, no snap).
 * - PatrolLocation: cycles ANPCMinionCharacter::PatrolPoints (advancing when the
 *   pawn is within PatrolAcceptanceRadius of the current one), falls back to
 *   HomeLocation with no route. Stock BTTask_MoveTo consumes the key.
 *
 * Stateless (no node instance) — per-minion patrol progress lives on the pawn
 * (CurrentPatrolIndex), so one shared service node serves every minion.
 */
UCLASS()
class GAME_CORE_API UBTService_MinionCombatState : public UBTService
{
	GENERATED_BODY()

public:
	UBTService_MinionCombatState();

	/** Within this range (cm) the controller keeps focus on the hero so the minion faces it. */
	UPROPERTY(EditAnywhere, Category = "Minion", meta = (ClampMin = "0.0"))
	float FocusRange = 800.0f;

	/** Distance (cm) at which a patrol point counts as reached and the route advances. */
	UPROPERTY(EditAnywhere, Category = "Minion", meta = (ClampMin = "0.0"))
	float PatrolAcceptanceRadius = 150.0f;

protected:
	virtual void TickNode(UBehaviorTreeComponent& OwnerComp, uint8* NodeMemory, float DeltaSeconds) override;
};
