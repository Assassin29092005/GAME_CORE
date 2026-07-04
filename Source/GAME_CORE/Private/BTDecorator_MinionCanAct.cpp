#include "BTDecorator_MinionCanAct.h"
#include "MinionAIController.h"
#include "AIController.h"

UBTDecorator_MinionCanAct::UBTDecorator_MinionCanAct()
{
	NodeName = TEXT("Minion Can Act");
}

bool UBTDecorator_MinionCanAct::CalculateRawConditionValue(UBehaviorTreeComponent& OwnerComp, uint8* NodeMemory) const
{
	const AAIController* AICon = OwnerComp.GetAIOwner();
	const APawn* Pawn = AICon ? AICon->GetPawn() : nullptr;

	// Live read — see class comment for why the BB's bCanAct isn't trusted here.
	// Shared gate (service BB mirror + fallback brain use the same function).
	return AMinionAIController::ComputeCanAct(Pawn);
}
