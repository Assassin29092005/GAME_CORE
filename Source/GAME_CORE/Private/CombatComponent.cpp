#include "CombatComponent.h"
#include "Animation/AnimInstance.h"
#include "GameFramework/Character.h"
#include "Components/SkeletalMeshComponent.h"
#include "MotionWarpingComponent.h"

UCombatComponent::UCombatComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
	MaxHealth = 100.0f;
}

void UCombatComponent::BeginPlay()
{
	Super::BeginPlay();
	CurrentHealth = MaxHealth;
}

// --- Health ---

void UCombatComponent::ApplyDamage(float DamageAmount)
{
	if (bIsDead || CurrentHealth <= 0.0f) return;

	CurrentHealth = FMath::Clamp(CurrentHealth - DamageAmount, 0.0f, MaxHealth);

	if (CurrentHealth <= 0.0f)
	{
		bIsDead = true;
		OnHealthDepleted.Broadcast();
	}
}

void UCombatComponent::MarkHitLanded()
{
	bHitLandedThisAttack = true;
}

void UCombatComponent::ResetForNewRound()
{
	bIsDead = false;
	bInAttackCooldown = false;
	CurrentHealth = MaxHealth;

	UWorld* World = GetWorld();
	if (World)
	{
		World->GetTimerManager().ClearTimer(CooldownTimerHandle);
	}

	ResetCombo();
	UE_LOG(LogTemp, Log, TEXT("CombatComponent: Reset for new round — health restored, combo cleared"));
}

// --- Combo / Montage System ---

void UCombatComponent::SetMovementInput(FVector2D InputValue)
{
	if (InputValue.IsNearlyZero(0.01f))
	{
		LastMovementInput = FVector::ZeroVector;
		return;
	}

	AActor* Owner = GetOwner();
	if (!Owner) return;

	// Transform from controller-local (camera-relative) to world-space.
	// IA_Move convention: X = A/D axis, Y = W/S axis.
	FRotator ControlRot = Owner->GetActorRotation();
	if (APawn* Pawn = Cast<APawn>(Owner))
	{
		if (AController* Controller = Pawn->GetController())
		{
			ControlRot = Controller->GetControlRotation();
		}
	}
	ControlRot.Pitch = 0.0f;
	ControlRot.Roll  = 0.0f;

	const FRotationMatrix RotMat(ControlRot);
	const FVector Fwd   = RotMat.GetUnitAxis(EAxis::X);
	const FVector Right = RotMat.GetUnitAxis(EAxis::Y);

	LastMovementInput = (Fwd * InputValue.Y + Right * InputValue.X).GetSafeNormal();
}

void UCombatComponent::ClearMovementInput()
{
	LastMovementInput = FVector::ZeroVector;
}

void UCombatComponent::SelectComboByDirection()
{
	AActor* Owner = GetOwner();
	if (!Owner) return;

	// Priority order for picking the combo direction:
	//   1) LastMovementInput pushed from the pawn BP (IA_Move) — immediate, works even before Mover has moved anything.
	//   2) Owner velocity above threshold — fallback if BP isn't hooked up yet.
	// Both fail → neutral combo.
	FVector DirVec = FVector::ZeroVector;

	if (!LastMovementInput.IsNearlyZero(0.1f))
	{
		DirVec = LastMovementInput;
	}
	else
	{
		FVector Velocity = Owner->GetVelocity();
		Velocity.Z = 0.0f;
		if (Velocity.Size() >= MovementComboThreshold)
		{
			DirVec = Velocity.GetSafeNormal();
		}
	}

	// No movement direction detected — neutral combo
	if (DirVec.IsNearlyZero(0.1f))
	{
		if (NeutralComboConfig) CombatConfig = NeutralComboConfig;
		UE_LOG(LogTemp, Log, TEXT("CombatComponent: SelectCombo → Neutral (no input/velocity)"));
		return;
	}

	const FVector Forward = Owner->GetActorForwardVector();
	const FVector Right   = Owner->GetActorRightVector();

	const float ForwardDot = FVector::DotProduct(Forward, DirVec);
	const float RightDot   = FVector::DotProduct(Right,   DirVec);

	UE_LOG(LogTemp, Log, TEXT("CombatComponent: SelectCombo → FwdDot=%.2f RightDot=%.2f"), ForwardDot, RightDot);

	if (FMath::Abs(ForwardDot) >= FMath::Abs(RightDot))
	{
		// Primarily forward or backward
		if (ForwardDot >= 0.0f && ForwardComboConfig)
		{
			CombatConfig = ForwardComboConfig;
			UE_LOG(LogTemp, Log, TEXT("CombatComponent: SelectCombo → Forward"));
		}
		else if (ForwardDot < 0.0f && BackwardComboConfig)
		{
			CombatConfig = BackwardComboConfig;
			UE_LOG(LogTemp, Log, TEXT("CombatComponent: SelectCombo → Backward"));
		}
		else if (NeutralComboConfig)
		{
			CombatConfig = NeutralComboConfig;
		}
	}
	else
	{
		// Primarily sideways
		if (SideComboConfig)
		{
			CombatConfig = SideComboConfig;
			UE_LOG(LogTemp, Log, TEXT("CombatComponent: SelectCombo → Side"));
		}
		else if (NeutralComboConfig)
		{
			CombatConfig = NeutralComboConfig;
		}
	}
}

void UCombatComponent::StartCooldown()
{
	bInAttackCooldown = true;
	UWorld* World = GetWorld();
	if (World && AttackCooldownDuration > 0.0f)
	{
		World->GetTimerManager().SetTimer(
			CooldownTimerHandle,
			this,
			&UCombatComponent::ClearCooldown,
			AttackCooldownDuration,
			false
		);
	}
	else
	{
		bInAttackCooldown = false;
	}
}

void UCombatComponent::ClearCooldown()
{
	bInAttackCooldown = false;
}

void UCombatComponent::RequestAttack()
{
	if (bIsDead) return;
	if (bInAttackCooldown) return;

	// Snap to the right directional combo at the START of a new chain
	if (!bIsAttacking)
	{
		SelectComboByDirection();
	}

	if (!CombatConfig || CombatConfig->GetComboLength() == 0) return;

	// If currently attacking, buffer input for combo continuation
	if (bIsAttacking)
	{
		// Buffer input regardless of combo window — will be consumed when window opens
		bInputBuffered = true;
		return;
	}

	const FAttackAnimData* AttackData = CombatConfig->GetAttackData(ComboStep);
	if (!AttackData || !AttackData->Montage) return;

	PlayComboMontage(*AttackData);
}

void UCombatComponent::PlayComboMontage(const FAttackAnimData& AttackData)
{
	UAnimInstance* AnimInstance = GetOwnerAnimInstance();
	if (!AnimInstance) return;

	bIsAttacking = true;
	bComboWindowOpen = false;
	bInputBuffered = false;
	bHitLandedThisAttack = false; // Fresh swing — allow one hit to land

	UAnimMontage* Montage = AttackData.Montage;
	CurrentComboMontage = Montage;

	// Configure montage blend times and root motion
	// NOTE: This mutates the shared asset. Safe as long as each combo step uses a unique montage.
	Montage->BlendIn.SetBlendTime(AttackData.BlendInTime);
	Montage->BlendOut.SetBlendTime(AttackData.BlendOutTime);
	Montage->bEnableRootMotionTranslation = AttackData.bEnableRootMotion;
	Montage->bEnableRootMotionRotation = AttackData.bEnableRootMotion;

	// Update motion warp target before playing
	UpdateMotionWarpTarget();

	// Play the montage with configured rate
	const float Duration = AnimInstance->Montage_Play(Montage, AttackData.PlayRate);

	if (Duration > 0.0f)
	{
		// Bind delegates AFTER Montage_Play so the montage instance exists
		FOnMontageEnded EndDelegate;
		EndDelegate.BindUObject(this, &UCombatComponent::OnMontageEnded);
		AnimInstance->Montage_SetEndDelegate(EndDelegate, Montage);

		FOnMontageEnded BlendOutDelegate;
		BlendOutDelegate.BindUObject(this, &UCombatComponent::OnMontageBlendingOut);
		AnimInstance->Montage_SetBlendingOutDelegate(BlendOutDelegate, Montage);

		if (AttackData.StartSection != NAME_None)
		{
			AnimInstance->Montage_JumpToSection(AttackData.StartSection, Montage);
		}

		// Open combo window at ~50% through the montage
		// Duration already accounts for PlayRate, so no additional division needed
		const float WindowOpenDelay = Duration * 0.5f;

		UWorld* World = GetWorld();
		if (World)
		{
			World->GetTimerManager().SetTimer(
				ComboWindowTimerHandle,
				this,
				&UCombatComponent::OpenComboWindow,
				WindowOpenDelay,
				false
			);
		}

		UE_LOG(LogTemp, Log, TEXT("CombatComponent: Playing combo step %d, Rate=%.2f, BlendIn=%.2f, BlendOut=%.2f"),
			ComboStep, AttackData.PlayRate, AttackData.BlendInTime, AttackData.BlendOutTime);
	}
}

void UCombatComponent::OpenComboWindow()
{
	bComboWindowOpen = true;

	// Auto-close after configured duration
	UWorld* World = GetWorld();
	if (World)
	{
		World->GetTimerManager().SetTimer(
			ComboWindowTimerHandle,
			this,
			&UCombatComponent::CloseComboWindow,
			CombatConfig ? CombatConfig->ComboWindowDuration : 0.6f,
			false
		);
	}

	// If input was buffered, advance combo immediately
	if (bInputBuffered)
	{
		bInputBuffered = false;
		bComboWindowOpen = false;

		if (World)
		{
			World->GetTimerManager().ClearTimer(ComboWindowTimerHandle);
		}

		ComboStep++;
		if (ComboStep >= CombatConfig->GetComboLength())
		{
			ComboStep = 0;
		}

		const FAttackAnimData* NextAttack = CombatConfig->GetAttackData(ComboStep);
		if (NextAttack && NextAttack->Montage)
		{
			PlayComboMontage(*NextAttack);
		}
	}
}

void UCombatComponent::CloseComboWindow()
{
	bComboWindowOpen = false;
}

void UCombatComponent::OnMontageBlendingOut(UAnimMontage* Montage, bool bInterrupted)
{
	// Fires when blend-out starts
}

void UCombatComponent::OnMontageEnded(UAnimMontage* Montage, bool bInterrupted)
{
	// Ignore callbacks from old montages (e.g., previous combo step interrupted by the next one)
	if (Montage != CurrentComboMontage)
	{
		return;
	}

	bIsAttacking = false;

	UWorld* World = GetWorld();
	if (World)
	{
		World->GetTimerManager().ClearTimer(ComboWindowTimerHandle);
	}

	if (bInterrupted)
	{
		ResetCombo();
		StartCooldown();
	}
	else if (!bComboWindowOpen)
	{
		// Montage finished naturally without combo continuation — apply cooldown
		ResetCombo();
		StartCooldown();
	}
}

void UCombatComponent::ResetCombo()
{
	ComboStep = 0;
	bIsAttacking = false;
	bComboWindowOpen = false;
	bInputBuffered = false;
	bHitLandedThisAttack = false;
	CurrentComboMontage = nullptr;

	UWorld* World = GetWorld();
	if (World)
	{
		World->GetTimerManager().ClearTimer(ComboWindowTimerHandle);
	}
}

// --- Motion Warping ---

void UCombatComponent::SetWarpTarget(AActor* Target)
{
	WarpTargetActor = Target;
}

void UCombatComponent::UpdateMotionWarpTarget()
{
	if (!bEnableMotionWarping || !WarpTargetActor) return;

	AActor* Owner = GetOwner();
	if (!Owner) return;

	UMotionWarpingComponent* WarpComp = Owner->FindComponentByClass<UMotionWarpingComponent>();
	if (!WarpComp) return;

	// Set warp target to the target actor's location
	FMotionWarpingTarget WarpTarget;
	WarpTarget.Name = WarpTargetName;
	WarpTarget.Location = WarpTargetActor->GetActorLocation();
	WarpTarget.Rotation = (WarpTargetActor->GetActorLocation() - Owner->GetActorLocation()).Rotation();

	WarpComp->AddOrUpdateWarpTarget(WarpTarget);
}

// --- Utility ---

UAnimInstance* UCombatComponent::GetOwnerAnimInstance() const
{
	AActor* Owner = GetOwner();
	if (!Owner) return nullptr;

	// Try ACharacter::GetMesh() first, fall back to FindComponentByClass for Mover pawns
	if (const ACharacter* OwnerChar = Cast<ACharacter>(Owner))
	{
		USkeletalMeshComponent* Mesh = OwnerChar->GetMesh();
		if (Mesh) return Mesh->GetAnimInstance();
	}

	USkeletalMeshComponent* Mesh = Owner->FindComponentByClass<USkeletalMeshComponent>();
	return Mesh ? Mesh->GetAnimInstance() : nullptr;
}
