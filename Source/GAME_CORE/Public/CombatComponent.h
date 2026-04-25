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

	/** True after health hits zero. Blocks further damage and attacks until ResetForNewRound(). */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Combat|Health")
	bool bIsDead = false;

	/** Restore full health and clear the dead flag. Call this when starting a new round. */
	UFUNCTION(BlueprintCallable, Category = "Combat|Health")
	void ResetForNewRound();

	// --- Combo / Montage System ---

	/** Neutral combo (standing still or no directional input). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Animation|Directional")
	TObjectPtr<UCombatAnimConfig> NeutralComboConfig;

	/** Forward combo (W held while attacking). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Animation|Directional")
	TObjectPtr<UCombatAnimConfig> ForwardComboConfig;

	/** Backward combo (S held while attacking). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Animation|Directional")
	TObjectPtr<UCombatAnimConfig> BackwardComboConfig;

	/** Side combo (A or D held while attacking). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Animation|Directional")
	TObjectPtr<UCombatAnimConfig> SideComboConfig;

	/** Speed below which the neutral combo is always used (cm/s). Used only as fallback when BP has not fed input. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Animation|Directional")
	float MovementComboThreshold = 100.0f;

	/** World-space direction cached from the last IA_Move value fed by the pawn BP. Takes priority over velocity. */
	UPROPERTY(BlueprintReadOnly, Category = "Combat|Animation|Directional")
	FVector LastMovementInput = FVector::ZeroVector;

	/**
	 * Feed IA_Move value from the pawn BP (hook IA_Move Triggered → here, and IA_Move Completed → ClearMovementInput).
	 * InputValue: X = A/D axis (right positive), Y = W/S axis (forward positive) — the raw ActionValue.Get<FVector2D>().
	 * C++ transforms it into world-space using the controller's yaw, so combos stay correct with a free camera.
	 */
	UFUNCTION(BlueprintCallable, Category = "Combat|Animation|Directional")
	void SetMovementInput(FVector2D InputValue);

	UFUNCTION(BlueprintCallable, Category = "Combat|Animation|Directional")
	void ClearMovementInput();

	/** Active config for the current combo — set automatically by SelectComboByDirection(). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Combat|Animation")
	TObjectPtr<UCombatAnimConfig> CombatConfig;

	/** How long after a combo ends before a new one can start (seconds). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Animation")
	float AttackCooldownDuration = 0.4f;

	UFUNCTION(BlueprintPure, Category = "Combat|Animation")
	bool IsInCooldown() const { return bInAttackCooldown; }

	UFUNCTION(BlueprintCallable, Category = "Combat|Animation")
	void RequestAttack();

	UFUNCTION(BlueprintCallable, Category = "Combat|Animation")
	void ResetCombo();

	/** Called by ANS_DealDamage when a hit lands — prevents multi-hit per swing. */
	void MarkHitLanded();

	/** True after the first hit of this swing has landed. Reset when next attack starts. */
	bool bHitLandedThisAttack = false;

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

	/** Picks the correct directional config based on velocity at attack start. */
	void SelectComboByDirection();

	void StartCooldown();
	void ClearCooldown();

	int32 ComboStep = 0;
	bool bIsAttacking = false;
	bool bComboWindowOpen = false;
	bool bInputBuffered = false;
	bool bInAttackCooldown = false;
	FTimerHandle ComboWindowTimerHandle;
	FTimerHandle CooldownTimerHandle;

	// Tracks the active combo montage to ignore stale end-delegate callbacks
	UPROPERTY()
	TObjectPtr<UAnimMontage> CurrentComboMontage;

	void OpenComboWindow();
	void CloseComboWindow();
	void UpdateMotionWarpTarget();
};
