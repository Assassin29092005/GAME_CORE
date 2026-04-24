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
	CurrentHealth = MaxHealth;
	ResetCombo();
	UE_LOG(LogTemp, Log, TEXT("CombatComponent: Reset for new round — health restored, combo cleared"));
}

// --- Combo / Montage System ---

void UCombatComponent::RequestAttack()
{
	if (bIsDead) return;
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
	}
	else if (!bComboWindowOpen)
	{
		// Montage finished naturally without combo continuation
		ResetCombo();
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
