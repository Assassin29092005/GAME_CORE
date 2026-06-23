#include "BossActionComponent.h"
#include "Animation/AnimInstance.h"
#include "GameFramework/Pawn.h"
#include "Components/SkeletalMeshComponent.h"
#include "HitReactionComponent.h"
#include "CombatComponent.h"

UBossActionComponent::UBossActionComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	// Tick AFTER Mover has integrated its own movement/rotation for the frame.
	// At default priority, Mover overwrites SetActorRotation each frame and the boss
	// never visibly turns to face the hero. PostPhysics runs after Mover's update.
	PrimaryComponentTick.TickGroup = TG_PostPhysics;
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

	if (bIsMoving)
	{
		APawn* OwnerPawn = Cast<APawn>(Owner);
		if (OwnerPawn)
		{
			// Use AddMovementInput so the Mover/CharacterMover handles gravity, collision, and velocity.
			// Scale: 1.0 = max speed for approach, reduced for retreat.
			const float Scale = (CurrentMoveSpeed >= ApproachSpeed) ? 1.0f : 0.75f;
			OwnerPawn->AddMovementInput(MoveDirection, Scale);
		}
	}
}

void UBossActionComponent::ExecuteAction(int32 ActionIndex)
{
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

	UE_LOG(LogTemp, Log, TEXT("BossAction: Boss has died — OnBossDied broadcast"));
}

void UBossActionComponent::ExecuteActionEnum(EBossAction Action)
{
	if (bIsDead || bIsPerformingAction) return;

	// Lock out RL actions while a hit reaction is playing — otherwise the next action
	// arriving from the bridge (~15 Hz) interrupts the flinch montage and the boss
	// pops straight into Attack/Block/etc. mid-stagger.
	if (AActor* Owner = GetOwner())
	{
		if (UHitReactionComponent* HitReaction = Owner->FindComponentByClass<UHitReactionComponent>())
		{
			if (HitReaction->IsReacting()) return;
		}
	}

	switch (Action)
	{
	case EBossAction::Attack:   DoAttack();   break;
	case EBossAction::Block:    DoBlock();    break;
	case EBossAction::Dodge:    DoDodge();    break;
	case EBossAction::Approach: DoApproach(); break;
	case EBossAction::Retreat:  DoRetreat();  break;
	default: break;
	}
}

void UBossActionComponent::DoAttack()
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

		bIsPerformingAction = true;
		PlayMontage(AttackMontage);
		UE_LOG(LogTemp, Log, TEXT("BossAction: Attack"));
	}
}

void UBossActionComponent::DoBlock()
{
	if (BlockMontage)
	{
		bIsPerformingAction = true;
		PlayMontage(BlockMontage);
		UE_LOG(LogTemp, Log, TEXT("BossAction: Block"));
	}
}

void UBossActionComponent::DoDodge()
{
	if (DodgeMontage)
	{
		bIsPerformingAction = true;
		PlayMontage(DodgeMontage);
		UE_LOG(LogTemp, Log, TEXT("BossAction: Dodge"));
	}
}

void UBossActionComponent::DoApproach()
{
	if (!TargetActor || !GetOwner()) return;

	const FVector ToTarget = (TargetActor->GetActorLocation() - GetOwner()->GetActorLocation()).GetSafeNormal();
	MoveInDirection(ToTarget, ApproachSpeed, MoveDuration);
	UE_LOG(LogTemp, Log, TEXT("BossAction: Approach"));
}

void UBossActionComponent::DoRetreat()
{
	if (!TargetActor || !GetOwner()) return;

	const FVector AwayFromTarget = (GetOwner()->GetActorLocation() - TargetActor->GetActorLocation()).GetSafeNormal();
	MoveInDirection(AwayFromTarget, RetreatSpeed, MoveDuration);
	UE_LOG(LogTemp, Log, TEXT("BossAction: Retreat"));
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
}

void UBossActionComponent::ResetForNewRound()
{
	bIsDead = false;
	bIsPerformingAction = false;
	bIsMoving = false;
	MoveDirection = FVector::ZeroVector;
	CurrentMoveSpeed = 0.0f;

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

void UBossActionComponent::PlayMontage(UAnimMontage* Montage)
{
	AActor* Owner = GetOwner();
	if (!Owner) return;

	USkeletalMeshComponent* Mesh = Owner->FindComponentByClass<USkeletalMeshComponent>();
	if (!Mesh) return;

	UAnimInstance* AnimInstance = Mesh->GetAnimInstance();
	if (!AnimInstance) return;

	AnimInstance->Montage_Play(Montage, 1.0f);

	// Bind end delegate AFTER Montage_Play so the montage instance exists
	FOnMontageEnded EndDelegate;
	EndDelegate.BindUObject(this, &UBossActionComponent::OnActionMontageEnded);
	AnimInstance->Montage_SetEndDelegate(EndDelegate, Montage);
}

void UBossActionComponent::OnActionMontageEnded(UAnimMontage* Montage, bool bInterrupted)
{
	bIsPerformingAction = false;
}
