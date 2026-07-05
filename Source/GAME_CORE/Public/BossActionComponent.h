#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Animation/AnimMontage.h"
#include "BossActionComponent.generated.h"

UENUM(BlueprintType)
enum class EBossAction : uint8
{
	Attack   = 0,
	Block    = 1,
	Dodge    = 2,
	Approach = 3,
	Retreat  = 4,
	Count    UMETA(Hidden)
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnBossDied);

/** Cross-track contract #1: fired when a boss attack begins its wind-up.
 *  UI/VFX (telegraph rings, off-screen warnings) bind this. WindupSeconds is the
 *  real-time telegraph hold after the wind-up slow-in has been applied. */
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnBossTelegraph, bool, bIsHeavyUnblockable, float, WindupSeconds);

/** Cross-track contract #1b: fired when a telegraphed attack DIES before impact
 *  (the attack montage was interrupted mid-wind-up — no hyper-armor covers the
 *  wind-up, so a hero hit routinely kills it). UI must clear the ring/banner or
 *  the player burns dodges on phantom attacks and learns to distrust the
 *  telegraph — the opposite of the GoW honesty rule. */
DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnBossTelegraphCancelled);

class URLBridgeComponent;
class UHitReactionComponent;
class UAnimInstance;
class USoundBase;

UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UBossActionComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UBossActionComponent();

	// --- Action Montages ---
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "BossAction|Montages")
	TObjectPtr<UAnimMontage> AttackMontage;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "BossAction|Montages")
	TObjectPtr<UAnimMontage> BlockMontage;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "BossAction|Montages")
	TObjectPtr<UAnimMontage> DodgeMontage;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "BossAction|Montages")
	TObjectPtr<UAnimMontage> DeathMontage;

	// --- Movement ---
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Movement")
	float ApproachSpeed = 400.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Movement")
	float RetreatSpeed = 300.0f;

	/** Short on purpose: the RL bridge issues a new action every ~0.1-0.3s, so a
	 *  long move burst gets overwritten mid-stride (direction flips -> jitter).
	 *  Keep this near the bridge cadence so each move is a clean short impulse. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Movement")
	float MoveDuration = 0.2f;

	/** Boss dodge backstep speed (cm/s) and duration (s) — code-driven displacement
	 *  during the dodge montage, since Mover doesn't consume the montage's root motion. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Movement")
	float DodgeSpeed = 900.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Movement")
	float DodgeDuration = 0.3f;

	/** How fast the boss rotates to face the hero (degrees/sec interpolation speed). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Movement")
	float RotationInterpSpeed = 8.0f;

	// --- Commitment (Phase 4.1 / 4.2 / 4.5) ---

	/** Minimum hold time for Block, even if BlockMontage is shorter. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Commitment")
	float MinBlockDuration = 0.5f;

	/** Consecutive identical decisions required to reverse movement direction
	 *  before DirectionCommitmentSeconds has elapsed since the last reversal. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Commitment",
	          meta = (ClampMin = "1", ClampMax = "10"))
	int32 MovementFlipVotes = 3;

	/** Phase 4.2 direction commitment: after a movement direction change, a
	 *  reversal is refused for this long unless MovementFlipVotes consecutive
	 *  identical opposite decisions arrive. Deliberately LONGER than MoveDuration —
	 *  the old gate keyed off the per-action commitment (== MoveDuration), which
	 *  had always elapsed by the time a new decision could dispatch, so the
	 *  hysteresis never actually fired (5 Hz direction flips shipped anyway). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Commitment",
	          meta = (ClampMin = "0.0", ClampMax = "3.0"))
	float DirectionCommitmentSeconds = 0.6f;

	/** Post-attack recovery: the boss cannot act for this long after an attack
	 *  montage completes. This is the player's punish window. Heavier attacks: 0.9-1.2. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Commitment")
	float AttackRecoveryDuration = 0.7f;

	// --- Masking (Phase 4.3) ---

	/** Attack is only legal within this range (cm); match montage reach + warp clamp. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Masking")
	float AttackRange = 250.0f;

	/** Attack is only legal when facing the target within this many degrees. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Masking")
	float AttackFacingToleranceDeg = 45.0f;

	// --- Telegraph (Phase 4.4 / 5.3) ---

	/** Attack montages whose telegraph reads as heavy/unblockable (red ring). The boss
	 *  has no per-attack DamageType yet, so set membership drives the telegraph flavor —
	 *  add AttackMontage here to mark it heavy. Absent = light/parryable (yellow). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Telegraph")
	TSet<TObjectPtr<UAnimMontage>> HeavyAttackMontages;

	/** Wind-up slow-in play rate while the boss is on screen. AN_RestoreRate on the
	 *  montage (start of the Active section) restores 1.0 for the swing itself. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Telegraph")
	float WindupPlayRate = 0.6f;

	/** Longer telegraph when the boss attacks from off screen (Phase 5.3 fairness rule).
	 *  Applied when WasRecentlyRendered(0.2) is false. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Telegraph")
	float OffscreenWindupPlayRate = 0.45f;

	/** Authored wind-up length (s) used for the OnBossTelegraph WindupSeconds when the
	 *  attack montage has no "Windup" section to measure. Broadcast value = length / rate. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Telegraph")
	float FallbackWindupSectionLength = 0.4f;

	/** Boss vocal/boom cue fired at wind-up start (guide.md 7.1 / 4.4). Played
	 *  at-location always; ALSO played 2D when the boss is off screen so the audio
	 *  telegraph survives the mix — the Phase 5.3.3 off-screen fairness rule. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Telegraph")
	TObjectPtr<USoundBase> TelegraphSound;

	/** Fired in DoAttack right after the attack montage starts (bridge AND fallback-brain
	 *  attacks — both route through DoAttack). Bind for telegraph rings / audio cues. */
	UPROPERTY(BlueprintAssignable, Category = "BossAction|Telegraph")
	FOnBossTelegraph OnBossTelegraph;

	/** Fired when the telegraphed attack montage is interrupted before impact
	 *  (hero hit lands during the unarmored wind-up). Bind anywhere OnBossTelegraph
	 *  is bound and clear the indicator — a ring counting down to an attack that
	 *  will never land teaches the player to ignore telegraphs. */
	UPROPERTY(BlueprintAssignable, Category = "BossAction|Telegraph")
	FOnBossTelegraphCancelled OnBossTelegraphCancelled;

	// --- Fallback brain (Phase 4.6) ---

	/** Seconds of bridge silence before the scripted fallback brain takes over
	 *  while the socket is DISCONNECTED (covers reconnect blips between episodes). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Fallback")
	float FallbackTimeout = 1.5f;

	/** Silence tolerance while the socket is still CONNECTED. Much larger than
	 *  FallbackTimeout on purpose: SB3 blocks in learn() between rollouts (every
	 *  n_steps ≈ 2.3 min, for multiple seconds on the training laptop) while the
	 *  socket stays connected but silent — at 1.5s the fallback brain hijacked
	 *  every rollout boundary and injected off-policy state into training. A
	 *  genuinely hung-but-connected script still hands over after this long. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction|Fallback")
	float FallbackTimeoutConnected = 45.0f;

	// The hero actor to move toward/away from
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossAction")
	TObjectPtr<AActor> TargetActor;

	// Execute an action by index (called from RLBridge)
	UFUNCTION(BlueprintCallable, Category = "BossAction")
	void ExecuteAction(int32 ActionIndex);

	UFUNCTION(BlueprintCallable, Category = "BossAction")
	void ExecuteActionEnum(EBossAction Action);

	/** Called when boss health hits zero. Plays DeathMontage and broadcasts OnBossDied. */
	UFUNCTION(BlueprintCallable, Category = "BossAction")
	void HandleDeath();

	/** Fired after HandleDeath() is called. Bind this in Blueprint to trigger round reset. */
	UPROPERTY(BlueprintAssignable, Category = "BossAction")
	FOnBossDied OnBossDied;

	UFUNCTION(BlueprintPure, Category = "BossAction")
	bool IsPerformingAction() const { return bIsPerformingAction; }

	UFUNCTION(BlueprintPure, Category = "BossAction")
	bool IsDead() const { return bIsDead; }

	// --- Locomotion state for ABP_Boss state machine ---

	/** True while a movement command (Approach/Retreat) is actively driving input. Use for idle ↔ locomotion transition. */
	UFUNCTION(BlueprintPure, Category = "BossAction|Locomotion")
	bool IsMoving() const { return bIsMoving; }

	/** True when the active movement is an Approach (faster, toward hero). False during Retreat or when idle. Use for slide/charge anim. */
	UFUNCTION(BlueprintPure, Category = "BossAction|Locomotion")
	bool IsApproaching() const { return bIsMoving && CurrentMoveSpeed >= ApproachSpeed; }

	/** Intended movement speed in cm/s for the current command. Zero when idle. Drives blendspace speed axis. */
	UFUNCTION(BlueprintPure, Category = "BossAction|Locomotion")
	float GetIntendedMoveSpeed() const { return bIsMoving ? CurrentMoveSpeed : 0.0f; }

	/** World-space direction of the current movement command. Zero vector when idle. */
	UFUNCTION(BlueprintPure, Category = "BossAction|Locomotion")
	FVector GetIntendedMoveDirection() const { return bIsMoving ? MoveDirection : FVector::ZeroVector; }

	/** Call after round reset to re-enable actions (pairs with ResetForNewRound on CombatComponent). */
	UFUNCTION(BlueprintCallable, Category = "BossAction")
	void ResetForNewRound();

	UFUNCTION(BlueprintPure, Category = "BossAction")
	static int32 GetActionCount() { return static_cast<int32>(EBossAction::Count); }

	/** Phase 4.3: per-action legality (index = EBossAction). Shipped in the observation
	 *  JSON ("mask") so Python (MaskablePPO) can learn with the same mask C++ enforces. */
	UFUNCTION(BlueprintPure, Category = "BossAction|Masking")
	TArray<bool> GetLegalActionMask() const;

private:
	// Each Do* returns true only if the action actually started (montage played /
	// movement burst began). ExecuteActionEnum skips commitment bookkeeping for a
	// failed dispatch, so one bad montage assignment can't brick the boss.
	bool DoAttack();
	bool DoBlock();
	bool DoDodge();
	bool DoApproach();
	bool DoRetreat();
	void MoveInDirection(const FVector& Direction, float Speed, float Duration);

	/** Plays the montage and binds the end delegate ONLY on success. Returns the
	 *  Montage_Play duration (0 on failure — wrong-skeleton asset, missing slot,
	 *  null anim instance) so callers can refuse to commit state, matching the
	 *  hero-side Duration>0 pattern in CombatComponent. */
	float PlayMontage(UAnimMontage* Montage);

	/** Phase 4.6 liveness: connected sockets tolerate FallbackTimeoutConnected of
	 *  silence (SB3 learn() pauses); disconnected ones only FallbackTimeout. */
	bool IsBridgeAlive(double Now) const;

	UFUNCTION()
	void OnActionMontageEnded(UAnimMontage* Montage, bool bInterrupted);

	void StopMovement();

	/** Phase 4.3: substitute the nearest legal action (Attack out of range/facing -> Approach). */
	EBossAction ApplyActionMask(EBossAction Action) const;

	/** Shared legality predicate behind ApplyActionMask and GetLegalActionMask. */
	bool IsAttackLegal() const;

	/** Phase 4.6: scripted distance-banded policy, active while the bridge is dead/silent.
	 *  Routes through ExecuteActionEnum so every Phase 4 gate applies to it too. */
	void TickFallbackBrain();

	/** Mover-safe anim instance lookup (mesh via FindComponentByClass — never Cast<ACharacter>). */
	UAnimInstance* GetOwnerAnimInstance() const;

	bool bIsPerformingAction = false;
	bool bIsDead = false;
	bool bIsMoving = false;
	FVector MoveDirection = FVector::ZeroVector;
	float CurrentMoveSpeed = 0.0f;
	FTimerHandle MoveTimerHandle;

	// --- Phase 4.1: action commitment ---
	EBossAction CurrentAction = EBossAction::Count;  // Count == none
	double ActionStartTime = 0.0;
	float CurrentMinDuration = 0.0f;

	// --- Phase 4.2: movement hysteresis ---
	EBossAction LastMovementAction = EBossAction::Count;
	EBossAction PendingMovementAction = EBossAction::Count;
	int32 PendingMovementVoteCount = 0;
	// When the movement direction last actually changed (dispatch time, post-mask).
	double LastDirectionChangeTime = -1000.0;

	// --- Phase 4.5: post-attack recovery lockout ---
	double ActionLockoutUntil = 0.0;

	// --- Phase 4.6: fallback brain watchdog ---
	double LastBridgeActionTime = 0.0;
	double NextFallbackDecisionTime = 0.0;
	double LastFallbackAttackTime = -10.0;
	TWeakObjectPtr<URLBridgeComponent> Bridge;

	// Cached for the IsReacting() gate + debug HUD (looked up in BeginPlay,
	// no hard reference — project convention).
	TWeakObjectPtr<UHitReactionComponent> CachedHitReaction;

protected:
	virtual void BeginPlay() override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;
};
