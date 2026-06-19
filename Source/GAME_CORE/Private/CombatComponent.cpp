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

void UCombatComponent::ApplyDamage(float DamageAmount, AActor* InstigatorActor)
{
	if (bIsDead || CurrentHealth <= 0.0f) return;

	// Brief grace period right after ResetForNewRound — combo hits that landed during
	// the death→reset transition (e.g., the second hit of a 2-hit combo) would otherwise
	// drain the freshly restored HP back to zero and trigger the death montage twice.
	if (bIsInvulnerable) return;

	if (InstigatorActor && GetOwner())
	{
		LastHitDirection = (GetOwner()->GetActorLocation() - InstigatorActor->GetActorLocation()).GetSafeNormal2D();
	}

	float FinalDamage = DamageAmount;
	if (IsBlockingAgainst(InstigatorActor))
	{
		FinalDamage *= BlockDamageMultiplier;

		// Blocked impact: interrupts the block-idle hold; its end delegate
		// chains back into the idle loop while the button stays held.
		if (BlockHitMontage)
		{
			PlayBlockMontage(BlockHitMontage);
		}

		UE_LOG(LogTemp, Log, TEXT("CombatComponent: BLOCKED — %.1f reduced to %.1f"), DamageAmount, FinalDamage);
	}

	CurrentHealth = FMath::Clamp(CurrentHealth - FinalDamage, 0.0f, MaxHealth);

	if (CurrentHealth <= 0.0f)
	{
		bIsDead = true;
		bIsBlocking = false;   // death montage takes over; don't resume the block loop
		OnHealthDepleted.Broadcast();
	}
}

bool UCombatComponent::IsBlockingAgainst(const AActor* Attacker) const
{
	if (!bIsBlocking) return false;
	if (!Attacker || !GetOwner()) return true; // unknown source: blocking still counts

	const FVector ToAttacker = (Attacker->GetActorLocation() - GetOwner()->GetActorLocation()).GetSafeNormal2D();
	return FVector::DotProduct(GetOwner()->GetActorForwardVector(), ToAttacker) > 0.3f;
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

	// Clear dodge/roll/block state so an interrupted evade or a held guard
	// from the previous round can't leak into the new one.
	bIsDodging = false;
	bIsRolling = false;
	bIsBlocking = false;
	CurrentDodgeMontage = nullptr;
	CurrentRollMontage = nullptr;
	CurrentBlockMontage = nullptr;

	// Open a brief invulnerability window so any in-flight combo damage from the
	// previous round (notify-state hits that were already in their damage tick)
	// can't immediately re-deplete the just-restored HP.
	if (World && PostResetInvulnerabilityDuration > 0.0f)
	{
		bIsInvulnerable = true;
		World->GetTimerManager().ClearTimer(InvulnTimerHandle);
		World->GetTimerManager().SetTimer(
			InvulnTimerHandle,
			this,
			&UCombatComponent::ClearInvulnerability,
			PostResetInvulnerabilityDuration,
			false
		);
	}

	UE_LOG(LogTemp, Log, TEXT("CombatComponent: Reset for new round — health restored, combo cleared, invuln=%.2fs"),
		PostResetInvulnerabilityDuration);
}

void UCombatComponent::ClearInvulnerability()
{
	bIsInvulnerable = false;
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
	if (bIsDodging || bIsRolling) return;  // committed to an evade; cancel windows arrive in guide.md 3.2
	if (bInAttackCooldown) return;

	// Attacking lowers the guard automatically.
	if (bIsBlocking)
	{
		SetBlocking(false);
	}

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

	// If input was buffered, advance combo immediately — but only if there's a next step.
	// Looping back to step 0 turned the combo into an infinite chain when the config had
	// only one attack (every press kept playing Hit1 forever). Cap at combo length and
	// let the current swing finish naturally — OnMontageEnded then applies cooldown.
	if (bInputBuffered)
	{
		bInputBuffered = false;

		const int32 NextStep = ComboStep + 1;
		if (CombatConfig && NextStep < CombatConfig->GetComboLength())
		{
			bComboWindowOpen = false;

			if (World)
			{
				World->GetTimerManager().ClearTimer(ComboWindowTimerHandle);
			}

			ComboStep = NextStep;
			const FAttackAnimData* NextAttack = CombatConfig->GetAttackData(ComboStep);
			if (NextAttack && NextAttack->Montage)
			{
				PlayComboMontage(*NextAttack);
			}
		}
		else
		{
			UE_LOG(LogTemp, Log,
				TEXT("CombatComponent: Combo exhausted at step %d (length %d) — chain ends, cooldown will apply"),
				ComboStep,
				CombatConfig ? CombatConfig->GetComboLength() : 0);
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

// --- Dodge ---

UAnimMontage* UCombatComponent::SelectDodgeMontage() const
{
	AActor* Owner = GetOwner();

	// No directional intent -> backstep, the souls-like default.
	if (!Owner || LastMovementInput.IsNearlyZero(0.1f))
	{
		return DodgeBackMontage;
	}

	// Same world-space-vs-actor-axes math as SelectComboByDirection.
	const float ForwardDot = FVector::DotProduct(Owner->GetActorForwardVector(), LastMovementInput);
	const float RightDot   = FVector::DotProduct(Owner->GetActorRightVector(),   LastMovementInput);

	if (FMath::Abs(ForwardDot) >= FMath::Abs(RightDot))
	{
		return ForwardDot >= 0.0f ? DodgeFrontMontage : DodgeBackMontage;
	}
	return RightDot >= 0.0f ? DodgeRightMontage : DodgeLeftMontage;
}

void UCombatComponent::RequestDodge()
{
	if (bIsDead || bIsDodging || bIsRolling) return;
	if (bIsAttacking) return;     // dodge-cancel arrives with guide.md 3.2 cancel windows
	// NOTE: deliberately NOT gated on bInAttackCooldown — cooldown gates attacks, never escapes.

	UAnimMontage* Montage = SelectDodgeMontage();
	if (!Montage) return;

	UAnimInstance* AnimInstance = GetOwnerAnimInstance();
	if (!AnimInstance) return;

	// Rolling drops the guard.
	if (bIsBlocking)
	{
		SetBlocking(false);
	}

	// Mutates the shared asset — safe per the project rule (unique montage per
	// character). Root motion ON so Mover integrates the roll displacement.
	Montage->BlendIn.SetBlendTime(DodgeBlendInTime);
	Montage->BlendOut.SetBlendTime(0.15f);
	Montage->bEnableRootMotionTranslation = true;
	Montage->bEnableRootMotionRotation = true;

	if (AnimInstance->Montage_Play(Montage, 1.0f) > 0.0f)
	{
		bIsDodging = true;
		CurrentDodgeMontage = Montage;

		FOnMontageEnded EndDelegate;
		EndDelegate.BindUObject(this, &UCombatComponent::OnDodgeMontageEnded);
		AnimInstance->Montage_SetEndDelegate(EndDelegate, Montage);

		UE_LOG(LogTemp, Log, TEXT("CombatComponent: Dodge (%s)"), *Montage->GetName());
	}
}

void UCombatComponent::OnDodgeMontageEnded(UAnimMontage* Montage, bool bInterrupted)
{
	if (Montage != CurrentDodgeMontage) return;
	bIsDodging = false;
	CurrentDodgeMontage = nullptr;
}

// --- Roll ---
// Same selection logic as dodge; different montage set, different blend, and
// requires movement input (the SPACEBAR-while-moving contract).

UAnimMontage* UCombatComponent::SelectRollMontage() const
{
	AActor* Owner = GetOwner();
	if (!Owner) return nullptr;

	// Defensive: this should never fire (BP gates first), but keeps the
	// invariant explicit — no idle-roll, ever.
	if (LastMovementInput.IsNearlyZero(0.1f))
	{
		return nullptr;
	}

	const float ForwardDot = FVector::DotProduct(Owner->GetActorForwardVector(), LastMovementInput);
	const float RightDot   = FVector::DotProduct(Owner->GetActorRightVector(),   LastMovementInput);

	if (FMath::Abs(ForwardDot) >= FMath::Abs(RightDot))
	{
		return ForwardDot >= 0.0f ? RollFrontMontage : RollBackMontage;
	}
	return RightDot >= 0.0f ? RollRightMontage : RollLeftMontage;
}

void UCombatComponent::RequestRoll()
{
	if (bIsDead || bIsDodging || bIsRolling) return;
	if (bIsAttacking) return;
	// NOT gated on bInAttackCooldown — same reasoning as dodge.

	UAnimMontage* Montage = SelectRollMontage();
	if (!Montage)
	{
		// No movement, or no montage assigned for this direction — silent no-op.
		return;
	}

	UAnimInstance* AnimInstance = GetOwnerAnimInstance();
	if (!AnimInstance) return;

	// Rolling drops the guard.
	if (bIsBlocking)
	{
		SetBlocking(false);
	}

	// Root motion ON so Mover integrates the larger displacement of a roll.
	Montage->BlendIn.SetBlendTime(RollBlendInTime);
	Montage->BlendOut.SetBlendTime(0.2f);
	Montage->bEnableRootMotionTranslation = true;
	Montage->bEnableRootMotionRotation = true;

	if (AnimInstance->Montage_Play(Montage, 1.0f) > 0.0f)
	{
		bIsRolling = true;
		CurrentRollMontage = Montage;

		FOnMontageEnded EndDelegate;
		EndDelegate.BindUObject(this, &UCombatComponent::OnRollMontageEnded);
		AnimInstance->Montage_SetEndDelegate(EndDelegate, Montage);

		UE_LOG(LogTemp, Log, TEXT("CombatComponent: Roll (%s)"), *Montage->GetName());
	}
}

void UCombatComponent::OnRollMontageEnded(UAnimMontage* Montage, bool bInterrupted)
{
	if (Montage != CurrentRollMontage) return;
	bIsRolling = false;
	CurrentRollMontage = nullptr;
}

// --- Block ---

void UCombatComponent::SetBlocking(bool bNewBlocking)
{
	if (bNewBlocking == bIsBlocking) return;
	if (bNewBlocking && (bIsDead || bIsDodging || bIsAttacking)) return;

	bIsBlocking = bNewBlocking;

	UAnimInstance* AnimInstance = GetOwnerAnimInstance();
	if (!AnimInstance) return;

	if (bIsBlocking)
	{
		PlayBlockMontage(BlockStartMontage ? BlockStartMontage.Get() : BlockIdleMontage.Get());
	}
	else
	{
		if (CurrentBlockMontage && AnimInstance->Montage_IsPlaying(CurrentBlockMontage))
		{
			AnimInstance->Montage_Stop(0.1f, CurrentBlockMontage);
		}
		CurrentBlockMontage = nullptr;

		if (BlockEndMontage && !bIsDead)
		{
			AnimInstance->Montage_Play(BlockEndMontage, 1.0f); // lower-guard flourish, fire and forget
		}
	}
}

void UCombatComponent::PlayBlockMontage(UAnimMontage* Montage)
{
	UAnimInstance* AnimInstance = GetOwnerAnimInstance();
	if (!AnimInstance || !Montage) return;

	// Block anims hold in place.
	Montage->bEnableRootMotionTranslation = false;
	Montage->bEnableRootMotionRotation = false;

	if (AnimInstance->Montage_Play(Montage, 1.0f) > 0.0f)
	{
		CurrentBlockMontage = Montage;

		FOnMontageEnded EndDelegate;
		EndDelegate.BindUObject(this, &UCombatComponent::OnBlockMontageEnded);
		AnimInstance->Montage_SetEndDelegate(EndDelegate, Montage);
	}
}

void UCombatComponent::OnBlockMontageEnded(UAnimMontage* Montage, bool bInterrupted)
{
	if (Montage != CurrentBlockMontage) return;
	CurrentBlockMontage = nullptr;

	// Manual hold-loop: while the button is held, chain back into the idle pose.
	// Deliberate replay through this delegate — NOT a montage section loop, and
	// NOT notify-driven (see the M0 one-click-kill postmortem for why).
	if (bIsBlocking && !bInterrupted && BlockIdleMontage)
	{
		PlayBlockMontage(BlockIdleMontage);
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
