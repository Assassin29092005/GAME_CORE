#include "CombatAnimConfig.h"

const FAttackAnimData* UCombatAnimConfig::GetAttackData(int32 ComboIndex) const
{
	if (ComboChain.Num() == 0) return nullptr;
	const int32 ClampedIndex = FMath::Clamp(ComboIndex, 0, ComboChain.Num() - 1);
	return &ComboChain[ClampedIndex];
}
