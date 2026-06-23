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
	void ApplyDamage(float DamageAmount, AActor* InstigatorActor = nullptr);

	/** Direction FROM the last damaging attacker TO us (world, 2D). Cached for
	 *  knockback/ragdoll impulses (guide.md Phase 6). Zero until first hit. */
	UPROPERTY(BlueprintReadOnly, Category = "Combat|Health")
	FVector LastHitDirection = FVector::ZeroVector;

	UPROPERTY(BlueprintAssignable, Category = "Combat|Health")
	FOnHealthDepleted OnHealthDepleted;

	/** True after health hits zero. Blocks further damage and attacks until ResetForNewRound(). */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Combat|Health")
	bool bIsDead = false;

	/** How long after ResetForNewRound() the actor cannot take damage. Must cover the full
	 *  duration of any combo the attacker might be in the middle of when reset fires —
	 *  otherwise the boss is killed AGAIN by the rest of the combo and the death montage
	 *  plays a second time. 3.0s covers a typical 3-hit combo with comfortable margin. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Health")
	float PostResetInvulnerabilityDuration = 3.0f;

	UFUNCTION(BlueprintPure, Category = "Combat|Health")
	bool IsInvulnerable() const { return bIsInvulnerable; }

	/** Restore full health and clear the dead flag. Call this when starting a new round. */
	UFUNCTION(BlueprintCallable, Category = "Combat|Health")
	void ResetForNewRound();

	// --- Dodge ---
	// Directional dodge montages, selected against LastMovementInput the same
	// way SelectComboByDirection works. No input -> backstep (DodgeBackMontage).
	// Assign UNIQUE montage assets per character (play mutates blend/root-motion
	// on the asset — the project-wide montage caveat).

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Dodge")
	TObjectPtr<UAnimMontage> DodgeFrontMontage;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Dodge")
	TObjectPtr<UAnimMontage> DodgeBackMontage;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Dodge")
	TObjectPtr<UAnimMontage> DodgeLeftMontage;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Dodge")
	TObjectPtr<UAnimMontage> DodgeRightMontage;

	/** Near-instant by design — a dodge that cross-fades gets you hit. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Dodge", meta = (ClampMin = "0.0", ClampMax = "0.3"))
	float DodgeBlendInTime = 0.05f;

	/** Hook IA_Dodge Started -> here. Ignores attack cooldown on purpose. */
	UFUNCTION(BlueprintCallable, Category = "Combat|Dodge")
	void RequestDodge();

	UFUNCTION(BlueprintPure, Category = "Combat|Dodge")
	bool IsDodging() const { return bIsDodging; }

	// --- Block ---
	// Hold-state: SetBlocking(true) plays BlockStart, then chains BlockIdle
	// repeatedly until released (deliberate replay via end-delegate — NOT a
	// montage section loop). Blocked hits play BlockHit and skip the flinch.

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Block")
	TObjectPtr<UAnimMontage> BlockStartMontage;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Block")
	TObjectPtr<UAnimMontage> BlockIdleMontage;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Block")
	TObjectPtr<UAnimMontage> BlockHitMontage;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Block")
	TObjectPtr<UAnimMontage> BlockEndMontage;

	/** Fraction of damage that gets through a frontal block. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Combat|Block", meta = (ClampMin = "0.0", ClampMax = "1.0"))
	float BlockDamageMultiplier = 0.25f;

	/** Hook IA_Block Started -> true, Completed -> false. */
	UFUNCTION(BlueprintCallable, Category = "Combat|Block")
	void SetBlocking(bool bNewBlocking);

	UFUNCTION(BlueprintPure, Category = "Combat|Block")
	bool IsBlocking() const { return bIsBlocking; }

	/** True when blocking AND the attacker is within the frontal arc.
	 *  ANS_DealDamage uses this to suppress the flinch on blocked hits. */
	UFUNCTION(BlueprintPure, Category = "Combat|Block")
	bool IsBlockingAgainst(const AActor* Attacker) const;

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

	// --- Post-reset invulnerability ---
	// Set true by ResetForNewRound for PostResetInvulnerabilityDuration seconds.
	// ApplyDamage early-outs while this is set so combo damage that's still landing
	// during the death→reset transition can't immediately re-kill the actor.
	bool bIsInvulnerable = false;
	FTimerHandle InvulnTimerHandle;
	void ClearInvulnerability();

	// Tracks the active combo montage to ignore stale end-delegate callbacks
	UPROPERTY()
	TObjectPtr<UAnimMontage> CurrentComboMontage;

	void OpenComboWindow();
	void CloseComboWindow();
	void UpdateMotionWarpTarget();

	// --- Dodge / Block internals ---
	bool bIsDodging = false;
	bool bIsBlocking = false;

	// Track active montages so stale end-delegate callbacks are ignored
	// (same pattern as CurrentComboMontage / CurrentReactionMontage).
	UPROPERTY()
	TObjectPtr<UAnimMontage> CurrentDodgeMontage;

	UPROPERTY()
	TObjectPtr<UAnimMontage> CurrentBlockMontage;

	UAnimMontage* SelectDodgeMontage() const;
	void PlayBlockMontage(UAnimMontage* Montage);

	UFUNCTION()
	void OnDodgeMontageEnded(UAnimMontage* Montage, bool bInterrupted);

	UFUNCTION()
	void OnBlockMontageEnded(UAnimMontage* Montage, bool bInterrupted);
};
