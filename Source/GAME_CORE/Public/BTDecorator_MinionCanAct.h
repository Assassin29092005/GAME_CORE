#pragma once

#include "CoreMinimal.h"
#include "BehaviorTree/BTDecorator.h"
#include "BTDecorator_MinionCanAct.generated.h"

/**
 * Gate for minion action branches. Recomputes the bCanAct condition LIVE from
 * the pawn's components — deliberately NOT read from the blackboard, because
 * the BB copy (written by BTService_MinionCombatState at ~0.2s cadence) can be
 * up to an interval stale, and a stale "true" would let an attack fire while a
 * flinch montage is already playing.
 *
 * Condition: Combat && !IsDead() && !IsAttacking() &&
 *            (!HitReaction || !HitReaction->IsReacting())
 * IsReacting() covers the flinch montage PLUS HitReactionGracePeriod — the same
 * lockout the boss applies in BossActionComponent::ExecuteActionEnum.
 *
 * The blackboard bCanAct key still exists for observer aborts (set the
 * decorator's Flow Abort mode + a Blackboard decorator on bCanAct if a branch
 * must be interrupted mid-move when the minion gets staggered).
 */
UCLASS()
class GAME_CORE_API UBTDecorator_MinionCanAct : public UBTDecorator
{
	GENERATED_BODY()

public:
	UBTDecorator_MinionCanAct();

protected:
	virtual bool CalculateRawConditionValue(UBehaviorTreeComponent& OwnerComp, uint8* NodeMemory) const override;
};
