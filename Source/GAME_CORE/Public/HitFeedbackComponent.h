#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "HitFeedbackComponent.generated.h"

class UCameraShakeBase;

UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UHitFeedbackComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UHitFeedbackComponent();

	// --- Hit Stop (Time Dilation) ---
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitFeedback|HitStop")
	float HitStopTimeDilation = 0.05f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitFeedback|HitStop", meta = (ClampMin = "0.01", ClampMax = "0.5"))
	float HitStopDuration = 0.08f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitFeedback|HitStop")
	bool bEnableHitStop = true;

	// --- Attacker Anim Pause ---
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitFeedback|AnimPause")
	bool bPauseAttackerAnim = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitFeedback|AnimPause", meta = (ClampMin = "0.01", ClampMax = "0.3"))
	float AnimPauseDuration = 0.07f;

	// --- Camera Shake ---
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitFeedback|CameraShake")
	TSubclassOf<UCameraShakeBase> HitCameraShake;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitFeedback|CameraShake")
	float CameraShakeScale = 1.0f;

	// Call this when a hit lands
	UFUNCTION(BlueprintCallable, Category = "HitFeedback")
	void TriggerHitFeedback(AActor* Attacker);

	// Heavier variant for combo finishers
	UFUNCTION(BlueprintCallable, Category = "HitFeedback")
	void TriggerHeavyHitFeedback(AActor* Attacker);

private:
	void ApplyHitStop(float Duration, float Dilation);
	void RestoreTimeDilation();
	void PauseAttackerAnim(AActor* Attacker, float Duration);
	void ResumeAttackerAnim();
	void PlayCameraShake(float Scale);

	FTimerHandle HitStopTimerHandle;
	FTimerHandle AnimPauseTimerHandle;
	TWeakObjectPtr<AActor> PendingResumeAttacker;
};
