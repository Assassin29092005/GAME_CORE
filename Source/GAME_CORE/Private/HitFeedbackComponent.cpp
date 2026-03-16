#include "HitFeedbackComponent.h"
#include "Animation/AnimInstance.h"
#include "GameFramework/Character.h"
#include "Kismet/GameplayStatics.h"
#include "Components/SkeletalMeshComponent.h"

UHitFeedbackComponent::UHitFeedbackComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
}

void UHitFeedbackComponent::TriggerHitFeedback(AActor* Attacker)
{
	if (bEnableHitStop)
	{
		ApplyHitStop(HitStopDuration, HitStopTimeDilation);
	}

	if (bPauseAttackerAnim && Attacker)
	{
		PauseAttackerAnim(Attacker, AnimPauseDuration);
	}

	if (HitCameraShake)
	{
		PlayCameraShake(CameraShakeScale);
	}
}

void UHitFeedbackComponent::TriggerHeavyHitFeedback(AActor* Attacker)
{
	if (bEnableHitStop)
	{
		// Heavier hit stop: longer duration, slower dilation
		ApplyHitStop(HitStopDuration * 2.0f, HitStopTimeDilation * 0.5f);
	}

	if (bPauseAttackerAnim && Attacker)
	{
		PauseAttackerAnim(Attacker, AnimPauseDuration * 2.0f);
	}

	if (HitCameraShake)
	{
		PlayCameraShake(CameraShakeScale * 1.5f);
	}
}

void UHitFeedbackComponent::ApplyHitStop(float Duration, float Dilation)
{
	AActor* Owner = GetOwner();
	if (!Owner) return;

	UWorld* World = GetWorld();
	if (!World) return;

	// Clear any existing hit stop
	World->GetTimerManager().ClearTimer(HitStopTimerHandle);

	// Per-actor time dilation: only slows this actor's animations/tick,
	// not the entire world (avoids disrupting RL bridge timing)
	Owner->CustomTimeDilation = FMath::Max(Dilation, 0.01f);

	// World timer runs at normal speed, so Duration is real-time seconds
	World->GetTimerManager().SetTimer(
		HitStopTimerHandle,
		this,
		&UHitFeedbackComponent::RestoreTimeDilation,
		Duration,
		false
	);
}

void UHitFeedbackComponent::RestoreTimeDilation()
{
	AActor* Owner = GetOwner();
	if (Owner)
	{
		Owner->CustomTimeDilation = 1.0f;
	}
}

void UHitFeedbackComponent::PauseAttackerAnim(AActor* Attacker, float Duration)
{
	ACharacter* AttackerChar = Cast<ACharacter>(Attacker);
	if (!AttackerChar || !AttackerChar->GetMesh()) return;

	UAnimInstance* AnimInstance = AttackerChar->GetMesh()->GetAnimInstance();
	if (!AnimInstance) return;

	// Pause the current montage
	UAnimMontage* CurrentMontage = AnimInstance->GetCurrentActiveMontage();
	if (CurrentMontage)
	{
		AnimInstance->Montage_Pause(CurrentMontage);

		PendingResumeAttacker = Attacker;

		UWorld* World = GetWorld();
		if (World)
		{
			World->GetTimerManager().ClearTimer(AnimPauseTimerHandle);

			FTimerDelegate ResumeDelegate;
			ResumeDelegate.BindUObject(this, &UHitFeedbackComponent::ResumeAttackerAnim);

			World->GetTimerManager().SetTimer(
				AnimPauseTimerHandle,
				ResumeDelegate,
				Duration,
				false
			);
		}
	}
}

void UHitFeedbackComponent::ResumeAttackerAnim()
{
	AActor* Attacker = PendingResumeAttacker.Get();
	if (!Attacker) return;

	ACharacter* AttackerChar = Cast<ACharacter>(Attacker);
	if (!AttackerChar || !AttackerChar->GetMesh()) return;

	UAnimInstance* AnimInstance = AttackerChar->GetMesh()->GetAnimInstance();
	if (!AnimInstance) return;

	UAnimMontage* CurrentMontage = AnimInstance->GetCurrentActiveMontage();
	if (CurrentMontage)
	{
		AnimInstance->Montage_Resume(CurrentMontage);
	}

	PendingResumeAttacker.Reset();
}

void UHitFeedbackComponent::PlayCameraShake(float Scale)
{
	APlayerController* PC = UGameplayStatics::GetPlayerController(this, 0);
	if (PC && HitCameraShake)
	{
		PC->ClientStartCameraShake(HitCameraShake, Scale);
	}
}
