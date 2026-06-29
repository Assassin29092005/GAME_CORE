#include "CombatComponent.h"
#include "Animation/AnimInstance.h"
#include "GameFramework/Character.h"
#include "Components/SkeletalMeshComponent.h"
#include "MotionWarpingComponent.h"
#include "EngineUtils.h"
#include "BossActionComponent.h"
#include "HitReactionComponent.h"
#include "MoverComponent.h"
#include "DefaultMovementSet/InstantMovementEffects/BasicInstantMovementEffects.h"

UCombatComponent::UCombatComponent()
{
	// Tick is on but only does work during a dodge window — early-returns otherwise.
	PrimaryComponentTick.bCanEverTick = true;
	MaxHealth = 100.0f;
}

void UCombatComponent::BeginPlay()
{
	Super::BeginPlay();
	CurrentHealth = MaxHealth;

	// Remember the spawn pose so ResetForNewRound can put the actor back here
	// at the start of each round (souls-like arena reset).
	if (AActor* Owner = GetOwner())
	{
		SpawnTransform = Owner->GetActorTransform();
		bSpawnTransformCaptured = true;
	}
}

void UCombatComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	if (!bIsDodging || DodgeDuration <= 0.0f || DodgeDistance <= 0.0f) return;

	AActor* Owner = GetOwner();
	if (!Owner) return;

	// Linear push at constant speed for DodgeDuration. AddActorWorldOffset with
	// sweep=true respects collisions (won't shove the hero through a wall) but
	// bypasses Mover's input producer, which is fine — we WANT a guaranteed
	// displacement regardless of what Mover would do with player input.
	const float Remaining = FMath::Max(0.0f, DodgeDuration - DodgeElapsed);
	const float StepTime  = FMath::Min(DeltaTime, Remaining);
	if (StepTime <= 0.0f) return;

	const FVector StepOffset = DodgeDirection * (DodgeDistance / DodgeDuration) * StepTime;
	FHitResult SweepHit;
	Owner->AddActorWorldOffset(StepOffset, /*bSweep*/ true, &SweepHit, ETeleportType::None);

	DodgeElapsed += StepTime;
}

// --- Health ---

void UCombatComponent::ApplyDamage(float DamageAmount, AActor* InstigatorActor, FName DamageType)
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
		const bool bHeavyAttack = (DamageType == FName("Heavy"));
		if (bHeavyAttack && BlockBreakMontage)
		{
			// Block break: Heavy attacks shatter the guard. Full damage, drop
			// the block flag (so OnBlockMontageEnded won't re-chain idle), play
			// the break montage. ANS_DealDamage's bBlocked cache is sampled
			// BEFORE this call, so the flinch is still suppressed for this hit —
			// the break montage IS the reaction.
			PlayBlockMontage(BlockBreakMontage);
			bIsBlocking = false;
			UE_LOG(LogTemp, Log, TEXT("CombatComponent: BLOCK BROKEN by Heavy — full %.1f dmg"), DamageAmount);
		}
		else
		{
			// Normal block: reduce damage, play block-impact; idle loop continues.
			FinalDamage *= BlockDamageMultiplier;

			if (BlockHitMontage)
			{
				PlayBlockMontage(BlockHitMontage);
			}

			UE_LOG(LogTemp, Log, TEXT("CombatComponent: BLOCKED (%s) — %.1f reduced to %.1f"),
				*DamageType.ToString(), DamageAmount, FinalDamage);
		}
	}

	CurrentHealth = FMath::Clamp(CurrentHealth - FinalDamage, 0.0f, MaxHealth);

	if (CurrentHealth <= 0.0f)
	{
		bIsDead = true;
		bIsBlocking = false;   // death montage takes over; don't resume the block loop

		// Play the death montage if one is assigned (hero path). The boss leaves
		// this empty and animates via BossActionComponent::HandleDeath instead.
		if (DeathMontage)
		{
			if (UAnimInstance* AnimInstance = GetOwnerAnimInstance())
			{
				AnimInstance->Montage_Play(DeathMontage, 1.0f);
			}
		}

		OnHealthDepleted.Broadcast();

		// Auto round reset: whichever fighter dies schedules a full-arena reset
		// after RoundResetDelay (death montage plays during the wait). The BP
		// death-montage binding still fires off OnHealthDepleted above.
		ScheduleRoundReset();
	}
}

void UCombatComponent::ScheduleRoundReset()
{
	if (!bAutoResetRoundOnDeath)
	{
		UE_LOG(LogTemp, Log, TEXT("CombatComponent[%s]: death but bAutoResetRoundOnDeath is OFF — no auto round reset."),
			GetOwner() ? *GetOwner()->GetName() : TEXT("?"));
		return;
	}

	UWorld* World = GetWorld();
	if (!World) return;

	World->GetTimerManager().ClearTimer(RoundResetTimerHandle);
	World->GetTimerManager().SetTimer(
		RoundResetTimerHandle,
		this,
		&UCombatComponent::TriggerRoundReset,
		FMath::Max(RoundResetDelay, 0.01f),
		false
	);

	UE_LOG(LogTemp, Log, TEXT("CombatComponent[%s]: scheduled full-arena round reset in %.2fs."),
		GetOwner() ? *GetOwner()->GetName() : TEXT("?"), FMath::Max(RoundResetDelay, 0.01f));
}

void UCombatComponent::TriggerRoundReset()
{
	UWorld* World = GetWorld();
	if (!World) return;

	// Reset every combatant in the arena (hero + boss in a 1v1). All the
	// ResetForNewRound variants are idempotent, so an actor carrying more than
	// one of these components is safe to touch through each branch.
	int32 ResetCount = 0;
	for (TActorIterator<AActor> It(World); It; ++It)
	{
		AActor* Actor = *It;
		if (!Actor) continue;

		bool bTouched = false;
		if (UCombatComponent* Combat = Actor->FindComponentByClass<UCombatComponent>())
		{
			Combat->ResetForNewRound();
			bTouched = true;
		}
		if (UBossActionComponent* BossAction = Actor->FindComponentByClass<UBossActionComponent>())
		{
			BossAction->ResetForNewRound();   // stops death montage, clears action/stagger state
			bTouched = true;
		}
		else if (UHitReactionComponent* HitReaction = Actor->FindComponentByClass<UHitReactionComponent>())
		{
			// Non-boss combatants (the hero) need their stagger cleared too;
			// the boss's HitReaction is already reset inside BossAction's reset.
			HitReaction->ResetForNewRound();
			bTouched = true;
		}

		if (bTouched) ResetCount++;
	}

	UE_LOG(LogTemp, Log, TEXT("CombatComponent: TriggerRoundReset — %d combatant(s) reset for a new round."), ResetCount);
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
		// NOTE: deliberately NOT clearing RoundResetTimerHandle here. An individual
		// ResetForNewRound (e.g. legacy BP boss-death wiring resetting only the boss)
		// must not cancel a pending FULL-arena TriggerRoundReset, or the other fighter
		// never gets reset. The timer is one-shot and idempotent if it fires post-reset.
	}

	// Stop any lingering montage (death, flinch, combo) so the actor returns to
	// its locomotion/idle state on reset instead of freezing in a dead pose.
	// (BossActionComponent::ResetForNewRound does this for the boss too — harmless
	// to repeat; this covers the hero whose death montage is BP-played.)
	if (UAnimInstance* AnimInstance = GetOwnerAnimInstance())
	{
		AnimInstance->StopAllMontages(0.2f);
	}

	ResetCombo();

	// Clear dodge/block state so an interrupted dodge or a held guard from
	// the previous round can't leak into the new one.
	bIsDodging = false;
	bIsBlocking = false;
	DodgeDirection = FVector::ZeroVector;
	DodgeElapsed = 0.0f;
	CurrentDodgeMontage = nullptr;
	CurrentBlockMontage = nullptr;

	// Teleport the actor back to its spawn pose. Mover pawns hold their own
	// authoritative position in the sim — a plain SetActorTransform gets snapped
	// back the next tick — so route through Mover's FTeleportEffect when a
	// MoverComponent is present. Fall back to SetActorTransform for non-Mover
	// actors (or if the effect can't be queued).
	if (bRestoreSpawnTransformOnReset && bSpawnTransformCaptured)
	{
		if (AActor* Owner = GetOwner())
		{
			bool bTeleported = false;
			if (UMoverComponent* MoverComp = Owner->FindComponentByClass<UMoverComponent>())
			{
				TSharedPtr<FTeleportEffect> Effect = MakeShared<FTeleportEffect>();
				Effect->TargetLocation = SpawnTransform.GetLocation();
				Effect->bUseActorRotation = false;
				Effect->TargetRotation = SpawnTransform.GetRotation().Rotator();
				MoverComp->QueueInstantMovementEffect(Effect);
				bTeleported = true;
			}

			if (!bTeleported)
			{
				Owner->SetActorTransform(SpawnTransform, /*bSweep*/ false, nullptr, ETeleportType::TeleportPhysics);
				if (UPrimitiveComponent* RootPrim = Cast<UPrimitiveComponent>(Owner->GetRootComponent()))
				{
					RootPrim->SetPhysicsLinearVelocity(FVector::ZeroVector);
				}
			}
		}
	}

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
	if (bIsDodging) return;       // commit to the dodge; cancel windows arrive in guide.md 3.2
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

void UCombatComponent::RequestDodge()
{
	if (bIsDead || bIsDodging) return;
	if (bIsAttacking) return;     // dodge-cancel arrives with guide.md 3.2 cancel windows
	// NOTE: deliberately NOT gated on bInAttackCooldown — cooldown gates attacks, never escapes.

	if (!DodgeMontage) return;

	UAnimInstance* AnimInstance = GetOwnerAnimInstance();
	if (!AnimInstance) return;

	AActor* Owner = GetOwner();
	if (!Owner) return;

	// Dodging drops the guard.
	if (bIsBlocking)
	{
		SetBlocking(false);
	}

	// Mutates the shared asset — safe per the project rule (unique montage per
	// character). Root motion is turned OFF here: displacement is driven by
	// AddActorWorldOffset in TickComponent so the actor moves a guaranteed
	// DodgeDistance regardless of what the source anim has authored.
	DodgeMontage->BlendIn.SetBlendTime(DodgeBlendInTime);
	DodgeMontage->BlendOut.SetBlendTime(0.15f);
	DodgeMontage->bEnableRootMotionTranslation = false;
	DodgeMontage->bEnableRootMotionRotation = false;

	if (AnimInstance->Montage_Play(DodgeMontage, 1.0f) > 0.0f)
	{
		bIsDodging = true;
		CurrentDodgeMontage = DodgeMontage;

		// Always backstep along -ActorForward, regardless of WASD.
		DodgeDirection = -Owner->GetActorForwardVector();
		DodgeElapsed = 0.0f;

		FOnMontageEnded EndDelegate;
		EndDelegate.BindUObject(this, &UCombatComponent::OnDodgeMontageEnded);
		AnimInstance->Montage_SetEndDelegate(EndDelegate, DodgeMontage);

		UE_LOG(LogTemp, Log, TEXT("CombatComponent: Dodge (%s) -> %s, %.0fcm over %.2fs"),
			*DodgeMontage->GetName(), *DodgeDirection.ToCompactString(), DodgeDistance, DodgeDuration);
	}
}

void UCombatComponent::OnDodgeMontageEnded(UAnimMontage* Montage, bool bInterrupted)
{
	if (Montage != CurrentDodgeMontage) return;
	bIsDodging = false;
	CurrentDodgeMontage = nullptr;
}

// --- Block ---

void UCombatComponent::SetBlocking(bool bNewBlocking)
{
	if (bNewBlocking == bIsBlocking) return;
	if (bNewBlocking && (bIsDead || bIsDodging || bIsAttacking)) return;

	bIsBlocking = bNewBlocking;

	UE_LOG(LogTemp, Log, TEXT("CombatComponent[%s]: SetBlocking(%s)"),
		GetOwner() ? *GetOwner()->GetName() : TEXT("?"), bIsBlocking ? TEXT("true") : TEXT("false"));

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

	// The idle pose is replayed via OnBlockMontageEnded as a manual hold-loop.
	// At each loop seam (when the authored idle reaches its end and replays),
	// the default BlendOut + BlendIn produced a visible "drop and raise" of the
	// guard around the 10s mark when the user held block continuously. Force
	// zero blend on the idle so the seam is invisible. Start/end montages keep
	// their authored blends for the raise/lower flourish.
	if (Montage == BlockIdleMontage)
	{
		Montage->BlendIn.SetBlendTime(0.0f);
		Montage->BlendOut.SetBlendTime(0.0f);
	}

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
