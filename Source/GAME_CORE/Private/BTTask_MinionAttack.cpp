#include "BTTask_MinionAttack.h"
#include "CombatComponent.h"
#include "AIController.h"

UBTTask_MinionAttack::UBTTask_MinionAttack()
{
	NodeName = TEXT("Minion Attack");
	bNotifyTick = true;
}

EBTNodeResult::Type UBTTask_MinionAttack::ExecuteTask(UBehaviorTreeComponent& OwnerComp, uint8* NodeMemory)
{
	const AAIController* AICon = OwnerComp.GetAIOwner();
	APawn* Pawn = AICon ? AICon->GetPawn() : nullptr;
	UCombatComponent* Combat = Pawn ? Pawn->FindComponentByClass<UCombatComponent>() : nullptr;
	if (!Combat || Combat->IsDead()) return EBTNodeResult::Failed;

	// Public API only — RequestAttack routes PlayComboMontage, which clears the
	// per-swing hit guard at the TRUE swing start (project rule: never add an
	// attack path that skips that clear).
	Combat->RequestAttack();

	// RequestAttack self-gates (cooldown, dodging, missing config/AnimInstance).
	// If it refused, fail fast so the BT falls through and retries next pass.
	if (!Combat->IsAttacking()) return EBTNodeResult::Failed;

	FBTMinionAttackMemory* Memory = CastInstanceNodeMemory<FBTMinionAttackMemory>(NodeMemory);
	Memory->ElapsedTime = 0.0f;
	return EBTNodeResult::InProgress;
}

void UBTTask_MinionAttack::TickTask(UBehaviorTreeComponent& OwnerComp, uint8* NodeMemory, float DeltaSeconds)
{
	Super::TickTask(OwnerComp, NodeMemory, DeltaSeconds);

	const AAIController* AICon = OwnerComp.GetAIOwner();
	const APawn* Pawn = AICon ? AICon->GetPawn() : nullptr;
	const UCombatComponent* Combat = Pawn ? Pawn->FindComponentByClass<UCombatComponent>() : nullptr;
	if (!Combat)
	{
		FinishLatentTask(OwnerComp, EBTNodeResult::Failed);
		return;
	}

	// Swing over (montage end delegate dropped bIsAttacking) → done.
	if (!Combat->IsAttacking())
	{
		FinishLatentTask(OwnerComp, EBTNodeResult::Succeeded);
		return;
	}

	FBTMinionAttackMemory* Memory = CastInstanceNodeMemory<FBTMinionAttackMemory>(NodeMemory);
	Memory->ElapsedTime += DeltaSeconds;
	if (Memory->ElapsedTime >= AttackTimeout)
	{
		FinishLatentTask(OwnerComp, EBTNodeResult::Failed);
	}
}
