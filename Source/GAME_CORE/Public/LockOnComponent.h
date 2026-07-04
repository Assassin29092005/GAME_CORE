#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "LockOnComponent.generated.h"

/**
 * Auto-engage soft lock-on for the player. When an actor tagged with EnemyTag
 * is within LockOnRange, smoothly rotates the player's controller yaw toward it,
 * plus a gentle pitch framing (guide.md 5.2 step 3: pitch clamped to frame
 * slightly above the target's root). Existing controller-yaw-relative WASD
 * becomes strafe-around-enemy naturally.
 *
 * Bias, never override: the correction is scaled by (1 - LookInputMagnitude)
 * (mouse delta + gamepad right stick, via UCombatCameraComponent), so the moment
 * the player touches the look input the lock yields completely.
 *
 * Targets are picked by Actor Tag (default "Enemy"). Add the tag to BP_Boss
 * (and any future NPC enemy) under Class Defaults → Actor → Tags.
 *
 * Mover-pawn safe: only reads the owning pawn's PlayerController and writes
 * its ControlRotation. No assumption of ACharacter.
 */
UCLASS(ClassGroup = (Combat), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API ULockOnComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	ULockOnComponent();

	/** Actor tag that marks valid lock-on targets. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "LockOn")
	FName EnemyTag = FName(TEXT("Enemy"));

	/** Engage range (cm). Acquire a target when one is within this distance. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "LockOn", meta = (ClampMin = "0.0"))
	float LockOnRange = 800.0f;

	/** Disengage range (cm). Drop the current target when it exceeds this. Wider than
	 *  LockOnRange so the lock doesn't flicker near the boundary. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "LockOn", meta = (ClampMin = "0.0"))
	float DisengageRange = 1100.0f;

	/** When true, YawInterpRate below is used verbatim. When false (default), the
	 *  interp speed comes from UGameFeelSettings::LockOnInterpSpeed so it can be
	 *  tuned centrally with every other feel number (guide.md Phase 8.1). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "LockOn")
	bool bOverrideInterpSpeed = false;

	/** Smoothing rate for FMath::RInterpTo when bOverrideInterpSpeed is set.
	 *  Higher = snappier (8 ≈ ~250ms to settle). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "LockOn", meta = (ClampMin = "0.0", EditCondition = "bOverrideInterpSpeed"))
	float YawInterpRate = 8.0f;

	UFUNCTION(BlueprintPure, Category = "LockOn")
	AActor* GetLockedTarget() const { return LockedTarget; }

	UFUNCTION(BlueprintPure, Category = "LockOn")
	bool IsLockedOn() const { return LockedTarget != nullptr; }

protected:
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	UPROPERTY()
	TObjectPtr<AActor> LockedTarget;

	AActor* FindNearestEnemy() const;
	void UpdateControllerRotation(float DeltaTime);
};
