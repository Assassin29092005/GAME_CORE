#include "BossActionComponent.h"
#include "Animation/AnimInstance.h"
#include "GameFramework/Pawn.h"
#include "Components/SkeletalMeshComponent.h"

UBossActionComponent::UBossActionComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
}

void UBossActionComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	AActor* Owner = GetOwner();
	if (!Owner) return;

	// Always smoothly rotate to face the hero (skip if dead)
	if (!bIsDead && TargetActor)
	{
		FVector ToTarget = TargetActor->GetActorLocation() - Owner->GetActorLocation();
		ToTarget.Z = 0.0f; // Ignore vertical difference — keep rotation on the horizontal plane
		if (!ToTarget.IsNearlyZero(1.0f))
		{
			const FRotator TargetRot = ToTarget.Rotation();
			const FRotator NewRot = FMath::RInterpTo(Owner->GetActorRotation(), TargetRot, DeltaTime, RotationInterpSpeed);
			Owner->SetActorRotation(NewRot);
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
