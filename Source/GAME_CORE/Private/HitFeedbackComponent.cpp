#include "HitFeedbackComponent.h"
#include "Animation/AnimInstance.h"
#include "CameraShakes.h"
#include "GameFramework/Character.h"
#include "Kismet/GameplayStatics.h"
#include "Components/SkeletalMeshComponent.h"
#include "Sound/SoundBase.h"

UHitFeedbackComponent::UHitFeedbackComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
}

void UHitFeedbackComponent::TriggerHitFeedback(AActor* Attacker)
{
	// No-argument path (BP callers, boss/minion hits): component defaults.
	TriggerHitFeedback(Attacker, HitStopDuration, CameraShakeScale);
}

void UHitFeedbackComponent::TriggerHitFeedback(AActor* Attacker, float StopDuration, float ShakeScale)
{
	if (bEnableHitStop)
	{
		ApplyHitStop(StopDuration, HitStopTimeDilation);
	}

	if (bPauseAttackerAnim && Attacker)
	{
		PauseAttackerAnim(Attacker, AnimPauseDuration);
	}

	PlayCameraShake(ShakeScale);
	PlayImpactSound(/*bHeavy*/ false);
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

	PlayCameraShake(CameraShakeScale * 1.5f, /*bHeavy*/ true);
	PlayImpactSound(/*bHeavy*/ true);
}

void UHitFeedbackComponent::PlayImpactSound(bool bHeavy)
{
	// Impact audio (guide.md 7.1.2): fires only from the confirmed-hit path, so
	// whiffs stay silent. At-location (not 2D) so distance/panning read correctly.
	USoundBase* Sound = bHeavy ? (HeavyImpactSound ? HeavyImpactSound.Get() : ImpactSound.Get()) : ImpactSound.Get();
	AActor* Owner = GetOwner();
	if (Sound && Owner)
	{
		UGameplayStatics::PlaySoundAtLocation(GetWorld(), Sound, Owner->GetActorLocation());
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
	if (!Attacker) return;

	USkeletalMeshComponent* Mesh = Attacker->FindComponentByClass<USkeletalMeshComponent>();
	if (!Mesh) return;

	UAnimInstance* AnimInstance = Mesh->GetAnimInstance();
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

	USkeletalMeshComponent* Mesh = Attacker->FindComponentByClass<USkeletalMeshComponent>();
	if (!Mesh) return;

	UAnimInstance* AnimInstance = Mesh->GetAnimInstance();
	if (!AnimInstance) return;

	UAnimMontage* CurrentMontage = AnimInstance->GetCurrentActiveMontage();
	if (CurrentMontage)
	{
		AnimInstance->Montage_Resume(CurrentMontage);
	}

	PendingResumeAttacker.Reset();
}

void UHitFeedbackComponent::PlayCameraShake(float Scale, bool bHeavy)
{
	APlayerController* PC = UGameplayStatics::GetPlayerController(this, 0);
	if (!PC) return;

	// BP-assigned shake wins; otherwise the code-only defaults (guide.md 3.4)
	// keep camera punch working with zero content setup.
	TSubclassOf<UCameraShakeBase> ShakeClass = HitCameraShake;
	if (!ShakeClass)
	{
		ShakeClass = bHeavy ? UCS_HitHeavy::StaticClass() : UCS_HitLight::StaticClass();
	}

	if (ShakeClass)
	{
		PC->ClientStartCameraShake(ShakeClass, Scale);
	}
}
