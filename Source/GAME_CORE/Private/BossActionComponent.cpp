#include "BossActionComponent.h"
#include "Animation/AnimInstance.h"
#include "GameFramework/Pawn.h"
#include "Components/SkeletalMeshComponent.h"
#include "Kismet/GameplayStatics.h"
#include "HitReactionComponent.h"
#include "CombatComponent.h"
#include "RLBridgeComponent.h"
#include "MoverComponent.h"
#include "Engine/Engine.h"
#include "HAL/IConsoleManager.h"

// Guide 8.2: one toggle for the combat feel debug overlay. Type `combat.DebugHUD 1`
// in the console mid-fight. Boss lines use fixed keys 101-102 so they repaint in
// place instead of scrolling; player lines (Track B) use 111+.
static TAutoConsoleVariable<int32> CVarFeelDebug(
	TEXT("combat.DebugHUD"), 0, TEXT("1 = combat feel debug overlay"));

UBossActionComponent::UBossActionComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	// Tick AFTER Mover has integrated its own movement/rotation for the frame.
	// At default priority, Mover overwrites SetActorRotation each frame and the boss
	// never visibly turns to face the hero. PostPhysics runs after Mover's update.
	PrimaryComponentTick.TickGroup = TG_PostPhysics;
}

void UBossActionComponent::BeginPlay()
{
	Super::BeginPlay();

	// Auto-acquire the player pawn as the rotation/movement target if BP didn't
	// assign one. Removes the dependency on a BP "SetupBossAI" step firing —
	// the boss now faces the hero out of the box.
	if (!TargetActor)
	{
		if (APawn* PlayerPawn = UGameplayStatics::GetPlayerPawn(this, 0))
		{
			TargetActor = PlayerPawn;
			UE_LOG(LogTemp, Log, TEXT("BossAction: Auto-acquired player pawn '%s' as TargetActor."), *PlayerPawn->GetName());
		}
	}

	// Phase 0.3: tick after the bridge so an action received this frame executes this
	// frame (without the prerequisite, BossActionComponent may tick first and add up to
	// one frame of latency on every bridge action). Also cached for the Phase 4.6
	// fallback-brain watchdog. No-hard-references convention: FindComponentByClass.
	if (URLBridgeComponent* BridgeComp = GetOwner()->FindComponentByClass<URLBridgeComponent>())
	{
		AddTickPrerequisiteComponent(BridgeComp);
		Bridge = BridgeComp;
	}

	// Cross-component per-frame read: ExecuteActionEnum gates on
	// HitReactionComponent::IsReacting() (montage + grace period). Cached here;
	// no tick-order dependency — IsReacting() is time-based, not tick-produced.
	CachedHitReaction = GetOwner()->FindComponentByClass<UHitReactionComponent>();

	// Parry is player-only (guide.md 3.5). DoBlock routes through the shared
	// UCombatComponent::SetBlocking, whose parry stamp would otherwise open a
	// 0.15s parry window on EVERY RL/fallback Block — a random-feeling hard
	// counter the player can't read and the trained policy never saw. Force it
	// off here rather than trusting a BP checkbox.
	if (UCombatComponent* Combat = GetOwner()->FindComponentByClass<UCombatComponent>())
	{
		Combat->bParryEnabled = false;
	}

	// CRITICAL Mover fix: the boss drives facing (SetActorRotation) and movement
	// (AddActorWorldOffset) from outside Mover's input pipeline. By default Mover
	// treats those as "external movement", logs a warning, and reconciles them
	// AWAY from its authoritative sim state next frame — so the boss never turned
	// to face the hero and its run/dodge barely displaced (~half speed + jitter).
	// Telling Mover to ACCEPT external movement makes it ingest our per-tick
	// transform changes into the sim state instead of fighting them.
	if (AActor* Owner = GetOwner())
	{
		if (UMoverComponent* MoverComp = Owner->FindComponentByClass<UMoverComponent>())
		{
			MoverComp->bAcceptExternalMovement = true;
			MoverComp->bWarnOnExternalMovement = false; // silence the 6000+ out-of-band warnings
			UE_LOG(LogTemp, Log, TEXT("BossAction: Mover set to accept external movement (facing/move fix)."));
		}
	}
}

void UBossActionComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	AActor* Owner = GetOwner();
	if (!Owner) return;

	// Always smoothly rotate to face the hero (skip if dead).
	// Yaw-only and TeleportPhysics so we set the authoritative rotation outright instead of
	// asking the physics scene to sweep — Mover's velocity-driven facing would otherwise
	// snap back to the movement direction next frame.
	if (!bIsDead && TargetActor)
	{
		FVector ToTarget = TargetActor->GetActorLocation() - Owner->GetActorLocation();
		ToTarget.Z = 0.0f; // Ignore vertical difference — keep rotation on the horizontal plane
		if (!ToTarget.IsNearlyZero(1.0f))
		{
			const FRotator CurrentRot = Owner->GetActorRotation();
			FRotator TargetRot = ToTarget.Rotation();
			TargetRot.Pitch = CurrentRot.Pitch;
			TargetRot.Roll = CurrentRot.Roll;
			const FRotator NewRot = FMath::RInterpTo(CurrentRot, TargetRot, DeltaTime, RotationInterpSpeed);
			Owner->SetActorRotation(NewRot, ETeleportType::TeleportPhysics);

			// Verbose-by-default debug log so we can diagnose whether rotation is actually
			// firing in PIE. If this never prints, TargetActor is null or ToTarget is zero;
			// if it prints but the boss doesn't visibly turn, Mover is overwriting us
			// despite TG_PostPhysics + TeleportPhysics (next step: check Mover modes).
			// Throttle to once per second to avoid log spam.
			static double LastLogTime = 0.0;
			const double Now = GetWorld()->GetTimeSeconds();
			if (Now - LastLogTime > 1.0)
			{
				LastLogTime = Now;
				UE_LOG(LogTemp, Log,
					TEXT("BossAction: Rotation tick — CurYaw=%.1f TgtYaw=%.1f NewYaw=%.1f InterpSpeed=%.1f Dt=%.4f"),
					CurrentRot.Yaw, TargetRot.Yaw, NewRot.Yaw, RotationInterpSpeed, DeltaTime);
			}
		}
	}
	else if (!bIsDead)
	{
		// TargetActor is null — log once so SetupBossAI failures are obvious.
		static double LastNullLogTime = 0.0;
		const double Now = GetWorld()->GetTimeSeconds();
		if (Now - LastNullLogTime > 5.0)
		{
			LastNullLogTime = Now;
			UE_LOG(LogTemp, Warning, TEXT("BossAction: TargetActor is null — rotation skipped. SetupBossAI may not have run."));
		}
	}

	if (bIsMoving && !MoveDirection.IsNearlyZero() && CurrentMoveSpeed > 0.0f)
	{
		// Code-driven displacement (sweep) — NOT AddMovementInput. The boss is a
		// Mover pawn and Mover ignores APawn::AddMovementInput (the same gotcha the
		// hero hits), so the boss played its run/dodge animation but never moved.
		// AddActorWorldOffset per tick is the proven path (the hero dodge uses it).
		const FVector StepOffset = MoveDirection.GetSafeNormal() * CurrentMoveSpeed * DeltaTime;
		FHitResult SweepHit;
		Owner->AddActorWorldOffset(StepOffset, /*bSweep*/ true, &SweepHit, ETeleportType::None);
	}

	// Guide 8.2: boss feel-debug lines (toggle with `combat.DebugHUD 1`).
	// Fixed keys + zero duration -> one stable line per key, repainted every frame.
	if (GEngine && CVarFeelDebug.GetValueOnGameThread() > 0)
	{
		const double Now = GetWorld()->GetTimeSeconds();
		GEngine->AddOnScreenDebugMessage(101, 0.f, FColor::Yellow, FString::Printf(
			TEXT("Boss action: %s  commit: %.2fs  lockout: %.2fs"),
			*UEnum::GetValueAsString(CurrentAction),
			FMath::Max(0.0, (ActionStartTime + CurrentMinDuration) - Now),
			FMath::Max(0.0, ActionLockoutUntil - Now)));

		const bool bBridgeUp = IsBridgeAlive(Now);
		GEngine->AddOnScreenDebugMessage(102, 0.f, FColor::Orange, FString::Printf(
			TEXT("Boss reacting: %s  stagger: %.1f  mask[Attack]: %s  brain: %s"),
			(CachedHitReaction.IsValid() && CachedHitReaction->IsReacting()) ? TEXT("YES") : TEXT("no"),
			CachedHitReaction.IsValid() ? CachedHitReaction->GetCurrentStagger() : 0.0f,
			IsAttackLegal() ? TEXT("legal") : TEXT("masked"),
			bBridgeUp ? TEXT("RL bridge") : TEXT("FALLBACK")));
	}

	// Phase 4.6: fallback brain — engage when the bridge is disconnected past
	// FallbackTimeout, or connected but silent past FallbackTimeoutConnected
	// (a routine SB3 learn() pause between rollouts is indistinguishable from a
	// hang at 1.5s — see IsBridgeAlive). Routes through ExecuteActionEnum, so
	// commitment/hysteresis/mask/recovery/telegraph all apply.
	if (!bIsDead && !IsBridgeAlive(GetWorld()->GetTimeSeconds()))
	{
		TickFallbackBrain();
	}
}

void UBossActionComponent::ExecuteAction(int32 ActionIndex)
{
	// Phase 4.6 watchdog: this is the bridge's entry point (BP binds OnRLActionReceived
	// here). The fallback brain calls ExecuteActionEnum directly, so it never
	// refreshes its own watchdog.
	if (UWorld* World = GetWorld())
	{
		LastBridgeActionTime = World->GetTimeSeconds();
	}

	if (bIsDead) return;

	if (ActionIndex < 0 || ActionIndex >= static_cast<int32>(EBossAction::Count))
	{
		UE_LOG(LogTemp, Warning, TEXT("BossAction: Invalid action index %d"), ActionIndex);
		return;
	}

	ExecuteActionEnum(static_cast<EBossAction>(ActionIndex));
}

void UBossActionComponent::HandleDeath()
{
	if (bIsDead) return; // Already handling death

	bIsDead = true;
	bIsPerformingAction = true; // Prevent any further actions
	bIsMoving = false;

	// Clear Phase 4 execution-layer state so nothing leaks across the death boundary.
	CurrentAction = EBossAction::Count;
	CurrentMinDuration = 0.0f;
	ActionLockoutUntil = 0.0;
	LastMovementAction = EBossAction::Count;
	PendingMovementAction = EBossAction::Count;
	PendingMovementVoteCount = 0;
	LastDirectionChangeTime = -1000.0;
	NextFallbackDecisionTime = 0.0;
	LastFallbackAttackTime = -10.0;

	// Stop any in-progress movement timer
	UWorld* World = GetWorld();
	if (World)
	{
		World->GetTimerManager().ClearTimer(MoveTimerHandle);
	}

	// Play death montage if assigned
	if (DeathMontage)
	{
		PlayMontage(DeathMontage);
	}

	// Notify Blueprint so it can trigger round reset after a delay
	OnBossDied.Broadcast();

	// Insurance: schedule the full-arena reset directly off the boss's death too,
	// so it fires even if the boss's HP didn't run through CombatComponent::ApplyDamage's
	// death branch. ScheduleRoundReset self-gates on bAutoResetRoundOnDeath, so this is a
	// no-op in shipped play and harmless (one-shot timer) if ApplyDamage already scheduled.
	if (AActor* Owner = GetOwner())
	{
		if (UCombatComponent* Combat = Owner->FindComponentByClass<UCombatComponent>())
		{
			Combat->ScheduleRoundReset();
		}
	}

	UE_LOG(LogTemp, Log, TEXT("BossAction: Boss has died — OnBossDied broadcast"));
}

void UBossActionComponent::ExecuteActionEnum(EBossAction Action)
{
	// Gate order is load-bearing (guide Phase 4):
	//   dead -> committed -> lockout -> reacting -> hysteresis -> mask -> dispatch.
	// Both the bridge (via ExecuteAction) and the fallback brain come through this
	// front door, so every gate applies to scripted decisions for free.
	if (bIsDead || bIsPerformingAction) return;

	UWorld* World = GetWorld();
	if (!World) return;
	const double Now = World->GetTimeSeconds();

	// Phase 4.1 — Commitment: once an action starts, drop new decisions on the floor
	// until it has held its minimum duration.
	if (CurrentAction != EBossAction::Count && Now - ActionStartTime < CurrentMinDuration)
	{
		return; // committed
	}

	// Phase 4.5 — Recovery lockout: post-attack punish window; the boss cannot act.
	if (Now < ActionLockoutUntil) return;

	// Lock out RL actions while a hit reaction is playing (montage + grace period) —
	// otherwise the next action arriving from the bridge (~15 Hz) interrupts the
	// flinch montage and the boss pops straight into Attack/Block/etc. mid-stagger.
	// (Cached in BeginPlay; per-frame read of HitReactionComponent state.)
	if (UHitReactionComponent* HitReaction = CachedHitReaction.Get())
	{
		if (HitReaction->IsReacting()) return;
	}

	// Phase 4.2 — Hysteresis: Approach<->Retreat flip-flopping at bridge cadence is the
	// worst-looking artifact. A direction REVERSAL is only accepted once the current
	// direction has been held DirectionCommitmentSeconds, or after MovementFlipVotes
	// consecutive identical opposite decisions. (The old gate compared against the
	// per-action commitment — which had always elapsed by the time dispatch was
	// reachable, so the hold-course branch was dead code and 5 Hz flips shipped.)
	const bool bIsMove = (Action == EBossAction::Approach || Action == EBossAction::Retreat);
	if (bIsMove && LastMovementAction != EBossAction::Count && Action != LastMovementAction)
	{
		PendingMovementVoteCount = (Action == PendingMovementAction) ? PendingMovementVoteCount + 1 : 1;
		PendingMovementAction = Action;
		const bool bDirectionHeldLongEnough = (Now - LastDirectionChangeTime) >= DirectionCommitmentSeconds;
		if (!bDirectionHeldLongEnough && PendingMovementVoteCount < MovementFlipVotes)
		{
			return; // hold course
		}
	}

	// Phase 4.3 — Mask: illegal action -> nearest legal substitute (Attack out of
	// range/facing -> Approach).
	Action = ApplyActionMask(Action);

	bool bDispatched = false;
	switch (Action)
	{
	case EBossAction::Attack:   bDispatched = DoAttack();   break;
	case EBossAction::Block:    bDispatched = DoBlock();    break;
	case EBossAction::Dodge:    bDispatched = DoDodge();    break;
	case EBossAction::Approach: bDispatched = DoApproach(); break;
	case EBossAction::Retreat:  bDispatched = DoRetreat();  break;
	default: break;
	}

	// A failed dispatch (montage refused to play, no target) must not record a
	// commitment or touch hysteresis — otherwise a bad montage assignment locks
	// the boss out of acting for the phantom action's duration.
	if (!bDispatched)
	{
		return;
	}

	// Phase 4.2 bookkeeping AFTER the mask so an Attack->Approach substitution
	// counts as movement too (previously it bypassed hysteresis entirely).
	if (Action == EBossAction::Approach || Action == EBossAction::Retreat)
	{
		if (Action != LastMovementAction)
		{
			LastDirectionChangeTime = Now;
		}
		LastMovementAction = Action;
		PendingMovementVoteCount = 0;
		PendingMovementAction = EBossAction::Count;
	}

	// Phase 4.1 — record the commitment the dispatched action just started.
	CurrentAction = Action;
	ActionStartTime = Now;
	switch (Action)
	{
	case EBossAction::Attack:
		CurrentMinDuration = AttackMontage ? AttackMontage->GetPlayLength() : 0.0f;
		break;
	case EBossAction::Dodge:
		CurrentMinDuration = DodgeMontage ? DodgeMontage->GetPlayLength() : 0.0f;
		break;
	case EBossAction::Block:
		CurrentMinDuration = FMath::Max(BlockMontage ? BlockMontage->GetPlayLength() : 0.0f, MinBlockDuration);
		break;
	case EBossAction::Approach:
	case EBossAction::Retreat:
		CurrentMinDuration = MoveDuration;
		break;
	default:
		CurrentMinDuration = 0.0f;
		break;
	}
}

bool UBossActionComponent::DoAttack()
{
	if (AttackMontage)
	{
		// Fresh swing — allow one hit to land. Hero combos get this from
		// PlayComboMontage; boss attacks bypass that path, so clear the per-swing
		// guard here. (Previously cleared in ANS_DealDamage::NotifyBegin, but
		// hit-stop's Montage_Pause/Resume re-fires NotifyBegin mid-swing, which
		// re-armed the guard every pause cycle — one swing became ~25 hits.)
		if (AActor* Owner = GetOwner())
		{
			if (UCombatComponent* Combat = Owner->FindComponentByClass<UCombatComponent>())
			{
				Combat->bHitLandedThisAttack = false;
			}
		}

		// Commit state (and broadcast the telegraph) ONLY if the montage actually
		// started — a 0-duration play has no end delegate, so bIsPerformingAction
		// would stick true forever and the boss would stand inert all round.
		if (PlayMontage(AttackMontage) <= 0.0f)
		{
			return false;
		}
		bIsPerformingAction = true;

		// Phase 4.4 telegraph slow-in + Phase 5.3 off-screen rule: stretch the wind-up
		// so the anticipation reads; AN_RestoreRate at the start of the Active section
		// snaps back to 1.0 for the swing. WasRecentlyRendered covers both frustum
		// culling and occlusion — a boss winding up behind a pillar gets the longer
		// telegraph too. Rate rides on the montage asset, which is unique to the boss
		// (montage mutation caveat — never share montages across characters).
		const bool bOffScreen = !GetOwner()->WasRecentlyRendered(0.2f);
		const float WindupRate = bOffScreen ? OffscreenWindupPlayRate : WindupPlayRate;
		if (UAnimInstance* AnimInstance = GetOwnerAnimInstance())
		{
			AnimInstance->Montage_SetPlayRate(AttackMontage, WindupRate);
		}

		// Cross-track contract #1: telegraph broadcast, right after the montage starts.
		// Fires for fallback-brain attacks too (they route through DoAttack).
		// WindupSeconds = telegraph hold time after the slow-in: measured "Windup"
		// section length when the montage has one, authored fallback length otherwise.
		const bool bHeavyUnblockable = HeavyAttackMontages.Contains(AttackMontage);
		float WindupSectionLength = FallbackWindupSectionLength;
		const int32 WindupSectionIdx = AttackMontage->GetSectionIndex(FName(TEXT("Windup")));
		if (WindupSectionIdx != INDEX_NONE)
		{
			WindupSectionLength = AttackMontage->GetSectionLength(WindupSectionIdx);
		}
		const float WindupSeconds = WindupSectionLength / FMath::Max(WindupRate, 0.01f);
		OnBossTelegraph.Broadcast(bHeavyUnblockable, WindupSeconds);

		UE_LOG(LogTemp, Log, TEXT("BossAction: Attack (windup rate %.2f%s, telegraph %.2fs%s)"),
			WindupRate, bOffScreen ? TEXT(" off-screen") : TEXT(""),
			WindupSeconds, bHeavyUnblockable ? TEXT(", HEAVY") : TEXT(""));
		return true;
	}
	return false;
}

bool UBossActionComponent::DoBlock()
{
	if (BlockMontage)
	{
		if (PlayMontage(BlockMontage) <= 0.0f)
		{
			return false; // failed play must not leave bIsPerformingAction stuck
		}
		bIsPerformingAction = true;

		// Activate the actual block damage-reduction on CombatComponent so the
		// RL "Block" action isn't visual-only. Cleared in OnActionMontageEnded.
		// (No parry: BeginPlay forces bParryEnabled=false on the boss.)
		if (UCombatComponent* Combat = GetOwner() ? GetOwner()->FindComponentByClass<UCombatComponent>() : nullptr)
		{
			Combat->SetBlocking(true);
		}

		UE_LOG(LogTemp, Log, TEXT("BossAction: Block"));
		return true;
	}
	return false;
}

bool UBossActionComponent::DoDodge()
{
	if (DodgeMontage)
	{
		if (PlayMontage(DodgeMontage) <= 0.0f)
		{
			return false;
		}
		bIsPerformingAction = true;

		// Displace the boss during the dodge (montage alone has no root motion that
		// Mover consumes). Evade away from the target via the same AddActorWorldOffset
		// movement burst the approach/retreat path uses.
		FVector DodgeDir = -GetOwner()->GetActorForwardVector();
		if (TargetActor)
		{
			const FVector Away = (GetOwner()->GetActorLocation() - TargetActor->GetActorLocation()).GetSafeNormal2D();
			if (!Away.IsNearlyZero()) DodgeDir = Away;
		}
		MoveInDirection(DodgeDir, DodgeSpeed, DodgeDuration);

		UE_LOG(LogTemp, Log, TEXT("BossAction: Dodge -> %s"), *DodgeDir.ToCompactString());
		return true;
	}
	return false;
}

bool UBossActionComponent::DoApproach()
{
	if (!TargetActor || !GetOwner()) return false;

	const FVector ToTarget = (TargetActor->GetActorLocation() - GetOwner()->GetActorLocation()).GetSafeNormal();
	MoveInDirection(ToTarget, ApproachSpeed, MoveDuration);
	UE_LOG(LogTemp, Log, TEXT("BossAction: Approach"));
	return true;
}

bool UBossActionComponent::DoRetreat()
{
	if (!TargetActor || !GetOwner()) return false;

	const FVector AwayFromTarget = (GetOwner()->GetActorLocation() - TargetActor->GetActorLocation()).GetSafeNormal();
	MoveInDirection(AwayFromTarget, RetreatSpeed, MoveDuration);
	UE_LOG(LogTemp, Log, TEXT("BossAction: Retreat"));
	return true;
}

void UBossActionComponent::MoveInDirection(const FVector& Direction, float Speed, float Duration)
{
	bIsPerformingAction = true;
	bIsMoving = true;
	MoveDirection = Direction;
	CurrentMoveSpeed = Speed;

	UWorld* World = GetWorld();
	if (!World) return;

	World->GetTimerManager().SetTimer(
		MoveTimerHandle,
		this,
		&UBossActionComponent::StopMovement,
		Duration,
		false
	);
}

void UBossActionComponent::StopMovement()
{
	bIsMoving = false;
	bIsPerformingAction = false;
	MoveDirection = FVector::ZeroVector;
	CurrentMoveSpeed = 0.0f;

	// Phase 4.1: a movement commitment ends with its move burst. Montage-backed
	// commitments (Attack/Block/Dodge) are cleared by OnActionMontageEnded instead —
	// a Dodge's move burst (DodgeDuration) ends before its montage does, and clearing
	// its commitment here would release it early.
	if (CurrentAction == EBossAction::Approach || CurrentAction == EBossAction::Retreat)
	{
		CurrentAction = EBossAction::Count;
	}
}

void UBossActionComponent::ResetForNewRound()
{
	bIsDead = false;
	bIsPerformingAction = false;
	bIsMoving = false;
	MoveDirection = FVector::ZeroVector;
	CurrentMoveSpeed = 0.0f;

	// Clear Phase 4 execution-layer state (commitment, hysteresis votes, recovery
	// lockout, fallback cadence) so the new round starts from a clean slate.
	// LastBridgeActionTime is deliberately NOT reset — it's a bridge-liveness
	// watchdog, not round state; refreshing it here would wrongly suppress the
	// fallback brain for FallbackTimeout seconds when Python isn't attached.
	CurrentAction = EBossAction::Count;
	ActionStartTime = 0.0;
	CurrentMinDuration = 0.0f;
	ActionLockoutUntil = 0.0;
	LastMovementAction = EBossAction::Count;
	PendingMovementAction = EBossAction::Count;
	PendingMovementVoteCount = 0;
	LastDirectionChangeTime = -1000.0;
	NextFallbackDecisionTime = 0.0;
	LastFallbackAttackTime = -10.0;

	UWorld* World = GetWorld();
	if (World)
	{
		World->GetTimerManager().ClearTimer(MoveTimerHandle);
	}

	// Stop the death montage (or any other lingering action montage) so the boss
	// returns to the locomotion state machine instead of staying laid out on the floor.
	// Without this, HandleDeath's DeathMontage keeps playing through the reset.
	if (AActor* Owner = GetOwner())
	{
		if (USkeletalMeshComponent* Mesh = Owner->FindComponentByClass<USkeletalMeshComponent>())
		{
			if (UAnimInstance* AnimInstance = Mesh->GetAnimInstance())
			{
				AnimInstance->StopAllMontages(0.2f);
			}
		}

		// Reset the hit-reaction component too — otherwise post-reset hits
		// inherit the previous round's accumulated stagger (so a single light
		// hit can immediately escalate to Heavy) and the grace timer can
		// briefly lock out the first RL action of the new round.
		if (UHitReactionComponent* HitReaction = Owner->FindComponentByClass<UHitReactionComponent>())
		{
			HitReaction->ResetForNewRound();
		}
	}

	UE_LOG(LogTemp, Log, TEXT("BossAction: Reset for new round"));
}

float UBossActionComponent::PlayMontage(UAnimMontage* Montage)
{
	if (!Montage) return 0.0f;

	UAnimInstance* AnimInstance = GetOwnerAnimInstance();
	if (!AnimInstance)
	{
		UE_LOG(LogTemp, Warning, TEXT("BossAction: PlayMontage(%s) — no anim instance on owner; action skipped."),
			*Montage->GetName());
		return 0.0f;
	}

	const float Duration = AnimInstance->Montage_Play(Montage, 1.0f);
	if (Duration <= 0.0f)
	{
		// Wrong-skeleton montage assigned in BP, missing slot, zero-length asset.
		// Binding the end delegate against a montage with no active instance means
		// OnActionMontageEnded never fires — callers must NOT set bIsPerformingAction.
		UE_LOG(LogTemp, Warning, TEXT("BossAction: Montage_Play FAILED for '%s' (returned 0) — check skeleton/slot. Boss keeps acting."),
			*Montage->GetName());
		return 0.0f;
	}

	// Bind end delegate AFTER Montage_Play so the montage instance exists
	FOnMontageEnded EndDelegate;
	EndDelegate.BindUObject(this, &UBossActionComponent::OnActionMontageEnded);
	AnimInstance->Montage_SetEndDelegate(EndDelegate, Montage);
	return Duration;
}

UAnimInstance* UBossActionComponent::GetOwnerAnimInstance() const
{
	// Mover pawn: never Cast<ACharacter> — find the mesh directly.
	AActor* Owner = GetOwner();
	if (!Owner) return nullptr;

	USkeletalMeshComponent* Mesh = Owner->FindComponentByClass<USkeletalMeshComponent>();
	return Mesh ? Mesh->GetAnimInstance() : nullptr;
}

bool UBossActionComponent::IsAttackLegal() const
{
	// Phase 4.3 legality: Attack needs a target within AttackRange, inside the
	// facing cone. No target = never legal (nothing to hit).
	if (!TargetActor || !GetOwner()) return false;

	const FVector ToTarget = TargetActor->GetActorLocation() - GetOwner()->GetActorLocation();
	const float Dist = ToTarget.Size2D();
	const float FacingDeg = FMath::RadiansToDegrees(FMath::Acos(
		FVector::DotProduct(GetOwner()->GetActorForwardVector(), ToTarget.GetSafeNormal2D())));
	return Dist <= AttackRange && FacingDeg <= AttackFacingToleranceDeg;
}

EBossAction UBossActionComponent::ApplyActionMask(EBossAction Action) const
{
	// Attack out of range/facing -> Approach (nearest legal substitute). Dodge while
	// mid-dodge is already illegal via bIsPerformingAction; nothing to add there.
	// Train/inference mismatch caveat: until Python retrains with MaskablePPO on the
	// shipped "mask" field, the policy believes "Attack at range 800" does something.
	if (Action != EBossAction::Attack || !TargetActor) return Action;
	return IsAttackLegal() ? Action : EBossAction::Approach;
}

TArray<bool> UBossActionComponent::GetLegalActionMask() const
{
	// Index = EBossAction (0=Attack, 1=Block, 2=Dodge, 3=Approach, 4=Retreat).
	// Mirrors ApplyActionMask exactly — only Attack has legality conditions today,
	// so training (MaskablePPO on the JSON "mask") matches the C++ substitution.
	TArray<bool> Mask;
	Mask.Init(true, GetActionCount());
	Mask[static_cast<int32>(EBossAction::Attack)] = IsAttackLegal();
	return Mask;
}

void UBossActionComponent::TickFallbackBrain()
{
	// Phase 4.6: minimal scripted policy (distance-banded) for bridge-dead play and
	// as the A/B baseline against the RL boss. All decisions go through the
	// ExecuteActionEnum front door so every Phase 4 gate applies to them too —
	// including the DoAttack telegraph broadcast.
	const double Now = GetWorld()->GetTimeSeconds();
	if (bIsDead || bIsPerformingAction || Now < NextFallbackDecisionTime || !TargetActor)
		return;
	NextFallbackDecisionTime = Now + 0.25;  // ~4 Hz scripted cadence

	const float Dist = FVector::Dist2D(GetOwner()->GetActorLocation(),
	                                   TargetActor->GetActorLocation());

	// Reactive: chance to dodge an incoming swing at close range
	if (UCombatComponent* HeroCombat = TargetActor->FindComponentByClass<UCombatComponent>())
		if (HeroCombat->IsAttacking() && Dist < 300.f && FMath::FRand() < 0.35f)
		{
			ExecuteActionEnum(EBossAction::Dodge);
			return;
		}

	if (Dist > 600.f)
		ExecuteActionEnum(EBossAction::Approach);
	else if (Dist > 250.f)
		ExecuteActionEnum(FMath::FRand() < 0.7f ? EBossAction::Approach : EBossAction::Retreat);
	else if (Now - LastFallbackAttackTime > 2.0)
	{
		LastFallbackAttackTime = Now;
		ExecuteActionEnum(EBossAction::Attack);
	}
	else
		ExecuteActionEnum(FMath::FRand() < 0.5f ? EBossAction::Block : EBossAction::Retreat);
}

bool UBossActionComponent::IsBridgeAlive(double Now) const
{
	// A CONNECTED-but-silent socket is normal during training: SB3 blocks inside
	// learn() between rollouts for multiple seconds while no actions flow. Only
	// treat that as dead after FallbackTimeoutConnected — at the old flat 1.5s the
	// fallback brain fought scripted for every gradient update and injected an
	// off-policy discontinuity at every rollout boundary. Disconnected sockets
	// keep the short FallbackTimeout grace (covers reconnect blips).
	const bool bConnected = Bridge.IsValid() && Bridge->IsClientConnected();
	const double Silence = Now - LastBridgeActionTime;
	return Silence < static_cast<double>(bConnected ? FallbackTimeoutConnected : FallbackTimeout);
}

void UBossActionComponent::OnActionMontageEnded(UAnimMontage* Montage, bool bInterrupted)
{
	bIsPerformingAction = false;

	if (Montage == AttackMontage)
	{
		// Hyper-armor backstop: montage interruption can skip ANS_HyperArmor's
		// NotifyEnd (the same rule that gives bCancelWindowOpen and
		// bDodgeInvulnerable their montage-end force-clears). Without this a
		// heavy interrupted during its armor window leaves the boss immune to
		// Light flinches for the rest of the fight.
		if (UHitReactionComponent* HitReaction = CachedHitReaction.Get())
		{
			HitReaction->SetHyperArmor(false);
		}

		// Telegraph honesty (contract #1b): the wind-up has no hyper-armor, so a
		// hero hit routinely kills the attack mid-telegraph. Tell the UI, or the
		// red ring keeps counting down to an impact that will never come and the
		// player learns to distrust telegraphs.
		if (bInterrupted)
		{
			OnBossTelegraphCancelled.Broadcast();
		}
	}

	// Phase 4.1: release the commitment — unless the montage ended before its minimum
	// hold (Block flinching out at 0.3s must still honor MinBlockDuration = 0.5s; the
	// time gate in ExecuteActionEnum keeps holding until CurrentMinDuration elapses,
	// and a stale CurrentAction past its duration no longer gates anything).
	const double Now = GetWorld() ? GetWorld()->GetTimeSeconds() : 0.0;
	if (bInterrupted || (Now - ActionStartTime) >= CurrentMinDuration)
	{
		CurrentAction = EBossAction::Count;
	}

	// Phase 4.5: post-attack recovery — the boss cannot act for AttackRecoveryDuration
	// after a completed (not interrupted) attack. This is the player's punish window.
	if (Montage == AttackMontage && !bInterrupted)
	{
		ActionLockoutUntil = Now + AttackRecoveryDuration;
	}

	// Drop the block guard when the block montage ends so the RL Block action
	// is a momentary defensive window, not a permanent stance.
	if (Montage == BlockMontage)
	{
		if (UCombatComponent* Combat = GetOwner() ? GetOwner()->FindComponentByClass<UCombatComponent>() : nullptr)
		{
			Combat->SetBlocking(false);
		}
	}
}
