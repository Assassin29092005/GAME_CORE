#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "CombatAnimConfig.h"
#include "CombatComponent.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnHealthDepleted);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnAttackLanded, float, DamageAmount, FName, DamageType);

class UAnimInstance;
class UMotionWarpingComponent;

UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UCombatComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UCombatComponent();

protected:
	virtual void BeginPlay() override;

public:
	// --- Health ---
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Health")
	float MaxHealth = 100.0f;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Combat|Health")
	float CurrentHealth;

	UFUNCTION(BlueprintCallable, Category = "Combat|Health")
	void ApplyDamage(float DamageAmount);

	UPROPERTY(BlueprintAssignable, Category = "Combat|Health")
	FOnHealthDepleted OnHealthDepleted;

	// --- Combo / Montage System ---
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Combat|Animation")
	TObjectPtr<UCombatAnimConfig> CombatConfig;

	UFUNCTION(BlueprintCallable, Category = "Combat|Animation")
	void RequestAttack();

	UFUNCTION(BlueprintCallable, Category = "Combat|Animation")
	void ResetCombo();

	UFUNCTION(BlueprintPure, Category = "Combat|Animation")
	bool IsAttacking() const { return bIsAttacking; }

	UFUNCTION(BlueprintPure, Category = "Combat|Animation")
	int32 GetComboStep() const { return ComboStep; }

	UPROPERTY(BlueprintAssignable, Category = "Combat|Animation")
	FOnAttackLanded OnAttackLanded;

	// --- Motion Warping ---
	UFUNCTION(BlueprintCallable, Category = "Combat|Warping")
	void SetWarpTarget(AActor* Target);

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Warping")
	FName WarpTargetName = FName(TEXT("AttackTarget"));

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Warping")
	bool bEnableMotionWarping = true;

protected:
	UPROPERTY()
	TObjectPtr<AActor> WarpTargetActor;

private:
	void PlayComboMontage(const FAttackAnimData& AttackData);

	UFUNCTION()
	void OnMontageEnded(UAnimMontage* Montage, bool bInterrupted);

	UFUNCTION()
	void OnMontageBlendingOut(UAnimMontage* Montage, bool bInterrupted);

	UAnimInstance* GetOwnerAnimInstance() const;

	int32 ComboStep = 0;
	bool bIsAttacking = false;
	bool bComboWindowOpen = false;
	bool bInputBuffered = false;
	FTimerHandle ComboWindowTimerHandle;

	// Tracks the active combo montage to ignore stale end-delegate callbacks
	UPROPERTY()
	TObjectPtr<UAnimMontage> CurrentComboMontage;

	void OpenComboWindow();
	void CloseComboWindow();
	void UpdateMotionWarpTarget();
};
