#include "CombatCameraComponent.h"

#include "BossActionComponent.h"
#include "Camera/CameraComponent.h"
#include "CombatComponent.h"
#include "GameFeelSettings.h"
#include "GameFeelSubsystem.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/SpringArmComponent.h"
#include "LockOnComponent.h"

UCombatCameraComponent::UCombatCameraComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	// Default tick group is fine: we only write ControlRotation and FOV, both of
	// which the spring arm consumes on its own tick. No Mover sim state is touched
	// (the TG_PostPhysics rule applies to actor-transform writes, not these).
}

void UCombatCameraComponent::BeginPlay()
{
	Super::BeginPlay();

	AActor* Owner = GetOwner();
	if (!Owner) return;

	// Mover pawn: never Cast<ACharacter> — component lookup only.
	SpringArm = Owner->FindComponentByClass<USpringArmComponent>();
	Camera = Owner->FindComponentByClass<UCameraComponent>();
	LockOn = Owner->FindComponentByClass<ULockOnComponent>();

	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();
	if (Settings->bApplyCameraDefaults)
	{
		ApplyCameraDefaults();
	}
}

void UCombatCameraComponent::ApplyCameraDefaults()
{
	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();

	if (SpringArm)
	{
		// guide.md 5.1 steps 2-4 (mid-distance follow variant).
		SpringArm->bEnableCameraLag = true;
		SpringArm->CameraLagSpeed = Settings->CameraLagSpeed;              // 9: higher = less lag
		SpringArm->bEnableCameraRotationLag = true;
		SpringArm->CameraRotationLagSpeed = Settings->CameraRotationLagSpeed; // 10: slightly snappier than position
		SpringArm->CameraLagMaxDistance = Settings->CameraLagMaxDistance;  // 75: fast pivots never leave the pawn behind
		SpringArm->bUseCameraLagSubstepping = true;                        // kills lag jitter at uneven frame times

		SpringArm->bDoCollisionTest = true;
		SpringArm->ProbeSize = Settings->CameraProbeSize;                  // 12 (go 16 if near-wall clipping shows)
		SpringArm->ProbeChannel = ECC_Camera;

		SpringArm->TargetArmLength = Settings->TargetArmLength;            // 400
		SpringArm->SocketOffset = Settings->CameraSocketOffset;            // (0,40,20)
		SpringArm->TargetOffset = Settings->CameraTargetOffset;            // (0,0,40): orbit the torso, not the feet
	}

	if (Camera)
	{
		Camera->SetFieldOfView(Settings->BaseFOV);
	}
}

void UCombatCameraComponent::UpdateBossReference()
{
	// Round resets keep the same boss actor alive, so this normally resolves once.
	// Re-resolve only if the cached actor was actually destroyed (level change etc.).
	if (BossActor.IsValid() && BossAction.IsValid()) return;

	AActor* Boss = UGameFeelSubsystem::FindBossActor(GetWorld());
	BossActor = Boss;
	BossAction = Boss ? Boss->FindComponentByClass<UBossActionComponent>() : nullptr;
}

float UCombatCameraComponent::ComputeLookInputMagnitude(const APlayerController* PC)
{
	if (!PC) return 0.0f;

	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();

	float MouseX = 0.0f, MouseY = 0.0f;
	PC->GetInputMouseDelta(MouseX, MouseY);
	float Magnitude = FVector2D(MouseX, MouseY).Size() / FMath::Max(Settings->LookYieldMouseScale, KINDA_SMALL_NUMBER);

	// Gamepad right stick is already normalized 0-1 per axis — but this is the RAW
	// key state (Enhanced Input deadzones do NOT apply here). A pad sitting idle on
	// the desk drifts 2-8%, which would register as "player is steering" every
	// frame, pin LastLookInputTime, and permanently kill soft framing even for a
	// mouse/keyboard player with a controller plugged in. Apply a deadzone and
	// rescale the remainder to 0-1.
	float StickX = 0.0f, StickY = 0.0f;
	PC->GetInputAnalogStickState(EControllerAnalogStick::CAS_RightStick, StickX, StickY);
	constexpr float StickDeadzone = 0.15f;
	float StickMag = FVector2D(StickX, StickY).Size();
	StickMag = StickMag > StickDeadzone ? (StickMag - StickDeadzone) / (1.0f - StickDeadzone) : 0.0f;
	Magnitude = FMath::Max(Magnitude, StickMag);

	return FMath::Clamp(Magnitude, 0.0f, 1.0f);
}

float UCombatCameraComponent::ComputeYieldFactor(const APlayerController* PC)
{
	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();
	const float LookMagnitude = ComputeLookInputMagnitude(PC);
	const float Now = GetWorld() ? GetWorld()->GetTimeSeconds() : 0.0f;

	// Require a deliberate input before refreshing the recovery timer — residual
	// post-deadzone noise must not hold RecoveryAlpha at 0 forever.
	constexpr float LookRefreshThreshold = 0.05f;
	if (LookMagnitude > LookRefreshThreshold)
	{
		LastLookInputTime = Now;
	}

	// While the player steers, (1 - magnitude) suppresses the correction; after they
	// stop, blend authority back over LookYieldRecoverySeconds instead of snapping
	// (cheat-sheet rule: resume after stick silence, at reduced rate).
	const float RecoveryAlpha = Settings->LookYieldRecoverySeconds > KINDA_SMALL_NUMBER
		? FMath::Clamp((Now - LastLookInputTime) / Settings->LookYieldRecoverySeconds, 0.0f, 1.0f)
		: 1.0f;

	return (1.0f - LookMagnitude) * RecoveryAlpha;
}

void UCombatCameraComponent::SetCameraMode(ECameraMode NewMode)
{
	// Idempotent: same mode twice is a no-op. Actual transition happens
	// smoothly in TickComponent via arm/FOV FInterpTo.
	CurrentMode = NewMode;
}

void UCombatCameraComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	AActor* Owner = GetOwner();
	if (!Owner) return;

	UpdateBossReference();

	bool bBossAlive = false;
	float BossDistance = TNumericLimits<float>::Max();
	if (BossActor.IsValid())
	{
		const UCombatComponent* BossCombat = BossActor->FindComponentByClass<UCombatComponent>();
		bBossAlive = BossCombat ? !BossCombat->IsDead() : true;
		BossDistance = FVector::Dist(Owner->GetActorLocation(), BossActor->GetActorLocation());
	}

	// Mode-driven arm/lag interp. Only owned by us when bApplyCameraDefaults is
	// on (the "we manage the SpringArm" opt-in). If BP-authored, we leave the
	// SpringArm alone in either mode — the ExplorationFOV still applies, but
	// arm/lag stay the BP's responsibility.
	if (SpringArm)
	{
		const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();
		if (Settings->bApplyCameraDefaults)
		{
			const float TargetArm = (CurrentMode == ECameraMode::Exploration)
				? Settings->ExplorationArmLength
				: Settings->TargetArmLength;
			SpringArm->TargetArmLength = FMath::FInterpTo(
				SpringArm->TargetArmLength, TargetArm, DeltaTime, Settings->ModeArmInterpSpeed);

			const float TargetLag = (CurrentMode == ECameraMode::Exploration)
				? Settings->ExplorationLagSpeed
				: Settings->CameraLagSpeed;
			SpringArm->CameraLagSpeed = FMath::FInterpTo(
				SpringArm->CameraLagSpeed, TargetLag, DeltaTime, Settings->ModeArmInterpSpeed);
		}
	}

	UpdateFOV(DeltaTime, BossDistance, bBossAlive);
	// Soft framing is a combat-only behavior (drift toward the boss). While
	// exploring the world, the player's stick / mouse is the sole rotation source.
	if (CurrentMode == ECameraMode::Combat)
	{
		UpdateSoftFraming(DeltaTime, BossDistance, bBossAlive);
	}
}

void UCombatCameraComponent::UpdateFOV(float DeltaTime, float BossDistance, bool bBossAlive)
{
	if (!Camera) return;

	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();

	// One FInterpTo handles every FOV source: compute the max requested FOV per
	// frame (guide 5.2 step 5). In Combat mode the extra source is boss-close
	// widen; a future sprint boost just raises TargetFOV here. In Exploration
	// mode the base FOV is wider and the boss-close widen is suppressed.
	float TargetFOV = (CurrentMode == ECameraMode::Exploration)
		? Settings->ExplorationFOV
		: Settings->BaseFOV;
	if (CurrentMode == ECameraMode::Combat && bBossAlive && BossDistance < Settings->BossCloseWidenDistance)
	{
		const float Alpha = 1.0f - FMath::Clamp(BossDistance / Settings->BossCloseWidenDistance, 0.0f, 1.0f);
		TargetFOV = FMath::Max(TargetFOV, Settings->BaseFOV + Settings->BossCloseFOVBoost * Alpha);
	}

	Camera->SetFieldOfView(FMath::FInterpTo(Camera->FieldOfView, TargetFOV, DeltaTime, Settings->FOVInterpSpeed));
}

void UCombatCameraComponent::UpdateSoftFraming(float DeltaTime, float BossDistance, bool bBossAlive)
{
	// Hard lock active → LockOnComponent owns the control rotation this frame.
	if (LockOn && LockOn->IsLockedOn()) return;
	if (!bBossAlive || !BossActor.IsValid()) return;

	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();
	if (BossDistance > Settings->SoftFramingRange) return;

	APawn* Pawn = Cast<APawn>(GetOwner());
	APlayerController* PC = Pawn ? Cast<APlayerController>(Pawn->GetController()) : nullptr;
	if (!PC) return;

	const float YieldFactor = ComputeYieldFactor(PC);
	const float InterpSpeed = Settings->SoftFramingInterpSpeed * YieldFactor;
	if (InterpSpeed <= KINDA_SMALL_NUMBER) return; // player is steering — never wrestle the stick

	const FVector ToTarget = BossActor->GetActorLocation() - GetOwner()->GetActorLocation();
	if (ToTarget.IsNearlyZero()) return;

	const FRotator CurrentRot = PC->GetControlRotation();
	const FRotator RawDesired = ToTarget.Rotation();
	// Same framing rule as hard lock (guide 5.2 step 3), just at a drift-speed interp.
	const FRotator Desired(
		FMath::Clamp(RawDesired.Pitch + Settings->LockOnPitchOffset, Settings->LockOnPitchMin, Settings->LockOnPitchMax),
		RawDesired.Yaw,
		CurrentRot.Roll);

	PC->SetControlRotation(FMath::RInterpTo(CurrentRot, Desired, DeltaTime, InterpSpeed));
}
