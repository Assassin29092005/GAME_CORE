#pragma once

#include "CoreMinimal.h"
#include "BehaviorTree/BTTaskNode.h"
#include "BTTask_MinionAttack.generated.h"

/** Per-execution scratch (node instances are shared across minions). */
struct FBTMinionAttackMemory
{
	float ElapsedTime = 0.0f;
};

/**
 * Fires one swing through UCombatComponent::RequestAttack() — the public API
 * ONLY. That path routes SelectComboByDirection → PlayComboMontage, which is
 * one of exactly two places allowed to clear the per-swing hit guard
 * (bHitLandedThisAttack). Playing attack montages directly from here would
 * bypass the guard and reintroduce the M0 one-click-kill class of bugs.
 *
 * Returns InProgress while IsAttacking(), Succeeded when the swing finishes,
 * Failed if RequestAttack was refused (cooldown / dodging / dead / no config)
 * or if the swing somehow never ends within AttackTimeout.
 */
UCLASS()
class GAME_CORE_API UBTTask_MinionAttack : public UBTTaskNode
{
	GENERATED_BODY()

public:
	UBTTask_MinionAttack();

	/** Safety net: fail the task if IsAttacking() never clears (e.g. montage asset
	 *  misconfigured and the end delegate never fires). Generous vs. a normal swing. */
	UPROPERTY(EditAnywhere, Category = "Minion", meta = (ClampMin = "0.5"))
	float AttackTimeout = 5.0f;

	virtual EBTNodeResult::Type ExecuteTask(UBehaviorTreeComponent& OwnerComp, uint8* NodeMemory) override;
	virtual void TickTask(UBehaviorTreeComponent& OwnerComp, uint8* NodeMemory, float DeltaSeconds) override;
	virtual uint16 GetInstanceMemorySize() const override { return sizeof(FBTMinionAttackMemory); }
};
