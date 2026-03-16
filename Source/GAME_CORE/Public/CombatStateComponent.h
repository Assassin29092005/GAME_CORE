#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Animation/AnimMontage.h"
#include "CombatStateComponent.generated.h"

UENUM(BlueprintType)
enum class ECombatState : uint8
{
	Exploration,
	Combat
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnCombatStateChanged, ECombatState, NewState);

UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UCombatStateComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UCombatStateComponent();

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "CombatState")
	TObjectPtr<UAnimMontage> IdleToCombatMontage;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "CombatState")
	TObjectPtr<UAnimMontage> CombatToIdleMontage;

	// Time without combat input before returning to exploration
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "CombatState", meta = (ClampMin = "1.0", ClampMax = "10.0"))
	float CombatExitDelay = 4.0f;

	UFUNCTION(BlueprintCallable, Category = "CombatState")
	void EnterCombat();

	UFUNCTION(BlueprintCallable, Category = "CombatState")
	void ExitCombat();

	// Call this whenever a combat action occurs (attack, block, dodge) to reset the exit timer
	UFUNCTION(BlueprintCallable, Category = "CombatState")
	void RefreshCombatTimer();

	UFUNCTION(BlueprintPure, Category = "CombatState")
	ECombatState GetCombatState() const { return CurrentState; }

	UFUNCTION(BlueprintPure, Category = "CombatState")
	bool IsInCombat() const { return CurrentState == ECombatState::Combat; }

	UPROPERTY(BlueprintAssignable, Category = "CombatState")
	FOnCombatStateChanged OnCombatStateChanged;

private:
	ECombatState CurrentState = ECombatState::Exploration;
	FTimerHandle CombatExitTimerHandle;

	void PlayTransitionMontage(UAnimMontage* Montage);
};
