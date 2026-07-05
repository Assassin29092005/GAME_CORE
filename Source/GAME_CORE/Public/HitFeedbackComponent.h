#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "HitFeedbackComponent.generated.h"

class UCameraShakeBase;
class USoundBase;

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
	/** Optional BP-assigned shake. Leave unset to fall back to the code-only
	 *  defaults (UCS_HitLight for normal hits, UCS_HitHeavy for the heavy tier). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitFeedback|CameraShake")
	TSubclassOf<UCameraShakeBase> HitCameraShake;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitFeedback|CameraShake")
	float CameraShakeScale = 1.0f;

	// --- Impact Audio (guide.md 7.1.2) ---
	/** Played at the owner's location on every confirmed hit. Lives here (not on
	 *  the montages) so whiffs stay silent — TriggerHitFeedback only fires from
	 *  the ANS_DealDamage hit path, and the sound inherits the per-attack weight
	 *  scaling for free. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitFeedback|Audio")
	TObjectPtr<USoundBase> ImpactSound;

	/** Louder/lower variant for TriggerHeavyHitFeedback (combo finishers, parry
	 *  freeze). Falls back to ImpactSound when unset. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "HitFeedback|Audio")
	TObjectPtr<USoundBase> HeavyImpactSound;

	// Call this when a hit lands
	UFUNCTION(BlueprintCallable, Category = "HitFeedback")
	void TriggerHitFeedback(AActor* Attacker);

	/** Per-attack overload (guide.md 3.4): ANS_DealDamage passes the landing
	 *  attack's FAttackAnimData feedback numbers through here so weight lives in
	 *  data. Plain C++ overload, NOT a UFUNCTION — UHT can't overload; BP keeps
	 *  the no-argument version whose component defaults stay the fallback. */
	void TriggerHitFeedback(AActor* Attacker, float StopDuration, float ShakeScale);

	// Heavier variant for combo finishers
	UFUNCTION(BlueprintCallable, Category = "HitFeedback")
	void TriggerHeavyHitFeedback(AActor* Attacker);

private:
	void ApplyHitStop(float Duration, float Dilation);
	void RestoreTimeDilation();
	void PauseAttackerAnim(AActor* Attacker, float Duration);
	void ResumeAttackerAnim();
	void PlayCameraShake(float Scale, bool bHeavy = false);
	void PlayImpactSound(bool bHeavy);

	FTimerHandle HitStopTimerHandle;
	FTimerHandle AnimPauseTimerHandle;
	TWeakObjectPtr<AActor> PendingResumeAttacker;
};
