#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Animation/AnimMontage.h"
#include "BossActionComponent.generated.h"

UENUM(BlueprintType)
enum class EBossAction : uint8
{
	Attack   = 0,
	Block    = 1,
	Dodge    = 2,
	Approach = 3,
	Retreat  = 4,
	Count    UMETA(Hidden)
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnBossDied);

UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UBossActionComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UBossActionComponent();

	// --- Action Montages ---
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "BossAction|Montages")
	TObjectPtr<UAnimMontage> AttackMontage;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "BossAction|Montages")
	TObjectPtr<UAnimMontage> BlockMontage;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "BossAction|Montages")
	TObjectPtr<UAnimMontage> DodgeMontage;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "BossAction|Montages")
	TObjectPtr<UAnimMontage> DeathMontage;

	// --- Movement ---
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Movement")
	float ApproachSpeed = 400.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Movement")
	float RetreatSpeed = 300.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Movement")
	float MoveDuration = 0.5f;

	/** How fast the boss rotates to face the hero (degrees/sec interpolation speed). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Movement")
	float RotationInterpSpeed = 8.0f;

	// The hero actor to move toward/away from
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction")
	TObjectPtr<AActor> TargetActor;

	// Execute an action by index (called from RLBridge)
	UFUNCTION(BlueprintCallable, Category = "BossAction")
	void ExecuteAction(int32 ActionIndex);

	UFUNCTION(BlueprintCallable, Category = "BossAction")
	void ExecuteActionEnum(EBossAction Action);

	/** Called when boss health hits zero. Plays DeathMontage and broadcasts OnBossDied. */
	UFUNCTION(BlueprintCallable, Category = "BossAction")
	void HandleDeath();

	/** Fired after HandleDeath() is called. Bind this in Blueprint to trigger round reset. */
	UPROPERTY(BlueprintAssignable, Category = "BossAction")
	FOnBossDied OnBossDied;

	UFUNCTION(BlueprintPure, Category = "BossAction")
	bool IsPerformingAction() const { return bIsPerformingAction; }

	UFUNCTION(BlueprintPure, Category = "BossAction")
	bool IsDead() const { return bIsDead; }

	// --- Locomotion state for ABP_Boss state machine ---

	/** True while a movement command (Approach/Retreat) is actively driving input. Use for idle ↔ locomotion transition. */
	UFUNCTION(BlueprintPure, Category = "BossAction|Locomotion")
	bool IsMoving() const { return bIsMoving; }

	/** True when the active movement is an Approach (faster, toward hero). False during Retreat or when idle. Use for slide/charge anim. */
	UFUNCTION(BlueprintPure, Category = "BossAction|Locomotion")
	bool IsApproaching() const { return bIsMoving && CurrentMoveSpeed >= ApproachSpeed; }

	/** Intended movement speed in cm/s for the current command. Zero when idle. Drives blendspace speed axis. */
	UFUNCTION(BlueprintPure, Category = "BossAction|Locomotion")
	float GetIntendedMoveSpeed() const { return bIsMoving ? CurrentMoveSpeed : 0.0f; }

	/** World-space direction of the current movement command. Zero vector when idle. */
	UFUNCTION(BlueprintPure, Category = "BossAction|Locomotion")
	FVector GetIntendedMoveDirection() const { return bIsMoving ? MoveDirection : FVector::ZeroVector; }

	/** Call after round reset to re-enable actions (pairs with ResetForNewRound on CombatComponent). */
	UFUNCTION(BlueprintCallable, Category = "BossAction")
	void ResetForNewRound();

	UFUNCTION(BlueprintPure, Category = "BossAction")
	static int32 GetActionCount() { return static_cast<int32>(EBossAction::Count); }

private:
	void DoAttack();
	void DoBlock();
	void DoDodge();
	void DoApproach();
	void DoRetreat();
	void MoveInDirection(const FVector& Direction, float Speed, float Duration);

	void PlayMontage(UAnimMontage* Montage);

	UFUNCTION()
	void OnActionMontageEnded(UAnimMontage* Montage, bool bInterrupted);

	void StopMovement();

	bool bIsPerformingAction = false;
	bool bIsDead = false;
	bool bIsMoving = false;
	FVector MoveDirection = FVector::ZeroVector;
	float CurrentMoveSpeed = 0.0f;
	FTimerHandle MoveTimerHandle;

protected:
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;
};
