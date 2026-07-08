#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "CombatCameraComponent.generated.h"

class APlayerController;
class UCameraComponent;
class ULockOnComponent;
class USpringArmComponent;
class UBossActionComponent;

/** Camera behavior mode (Tier 4 overworld). Combat = today's behavior
 *  (tight arm, boss-close FOV widen, soft framing on). Exploration = looser
 *  arm and FOV, no soft framing, no boss-close widen — for walking the
 *  overworld outside encounter volumes. Switched at runtime by
 *  UGameFeelSubsystem::SetCameraMode; smooth arm/FOV interp handles the
 *  transition so entering/leaving an encounter volume doesn't snap. */
UENUM(BlueprintType)
enum class ECameraMode : uint8
{
	Combat      UMETA(DisplayName = "Combat"),
	Exploration UMETA(DisplayName = "Exploration"),
};

/**
 * Combat camera for the hero (guide.md Phase 5). Self-installed at runtime by
 * UGameFeelSubsystem — no BP wiring, no edits to existing components.
 *
 * Responsibilities:
 *  - Optionally push the guide 5.1 spring-arm/camera defaults at BeginPlay
 *    (bApplyCameraDefaults in UGameFeelSettings).
 *  - Per-tick FOV lerp (FInterpTo, FOVInterpSpeed) toward the max of all FOV
 *    requests; currently BaseFOV plus the boss-close widen ramp
 *    (BaseFOV → BaseFOV + BossCloseFOVBoost as boss distance drops below
 *    BossCloseWidenDistance) — guide 5.2 step 5.
 *  - Soft framing (guide 5.2 step 4): when NOT hard-locked (LockOnComponent has
 *    no target) and the boss is alive within SoftFramingRange, drift the control
 *    rotation toward the boss at SoftFramingInterpSpeed, scaled by the
 *    (1 - LookInputMagnitude) yield factor — bias, never override.
 *
 * Mover-pawn safe: reads the PlayerController and writes ControlRotation only,
 * finds SpringArm/Camera via FindComponentByClass (never Cast<ACharacter>).
 */
UCLASS(ClassGroup = (Camera), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UCombatCameraComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UCombatCameraComponent();

	/**
	 * 0-1 magnitude of the player's current look input, combined from mouse delta
	 * (normalized by UGameFeelSettings::LookYieldMouseScale) and the gamepad right
	 * stick. Shared with ULockOnComponent so both yield rules agree on "the player
	 * is steering". Returns 0 for a null controller.
	 */
	static float ComputeLookInputMagnitude(const APlayerController* PC);

	/** Runtime camera mode. Default Combat. Setting Exploration widens the arm and
	 *  FOV to UGameFeelSettings::Exploration* targets, disables soft framing and
	 *  boss-close FOV widen, and (through UGameFeelSubsystem::SetCameraMode)
	 *  deactivates the LockOnComponent. Idempotent. */
	UFUNCTION(BlueprintCallable, Category = "Camera")
	void SetCameraMode(ECameraMode NewMode);

	UFUNCTION(BlueprintPure, Category = "Camera")
	ECameraMode GetCameraMode() const { return CurrentMode; }

protected:
	virtual void BeginPlay() override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	void ApplyCameraDefaults();
	void UpdateBossReference();
	void UpdateFOV(float DeltaTime, float BossDistance, bool bBossAlive);
	void UpdateSoftFraming(float DeltaTime, float BossDistance, bool bBossAlive);

	/** Yield factor in [0,1]: (1 - look magnitude) gated by the post-input recovery
	 *  ramp, so auto-framing suspends while the player steers and blends back over
	 *  LookYieldRecoverySeconds of look-input silence. */
	float ComputeYieldFactor(const APlayerController* PC);

	UPROPERTY()
	TObjectPtr<USpringArmComponent> SpringArm;

	UPROPERTY()
	TObjectPtr<UCameraComponent> Camera;

	UPROPERTY()
	TObjectPtr<ULockOnComponent> LockOn;

	/** The boss (first Enemy-tagged actor with a BossActionComponent). Weak: the HUD
	 *  and camera must survive the boss dying/resetting without dangling. */
	TWeakObjectPtr<AActor> BossActor;
	TWeakObjectPtr<UBossActionComponent> BossAction;

	/** World seconds of the last non-zero look input (drives the recovery ramp). */
	float LastLookInputTime = -1000.0f;

	/** Active camera mode. Default Combat preserves BossArena behavior for
	 *  clients that never call SetCameraMode. */
	ECameraMode CurrentMode = ECameraMode::Combat;
};
