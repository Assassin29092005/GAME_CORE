#pragma once

#include "CoreMinimal.h"
#include "AIController.h"
#include "MinionAIController.generated.h"

class UBehaviorTree;

/**
 * AI controller for ANPCMinionCharacter. Runs BehaviorTreeAsset at possess and
 * seeds HomeLocation from the pawn's spawn spot.
 *
 * FALLBACK BRAIN: if BehaviorTreeAsset is null at possess, the controller does
 * NOT idle — it runs a built-in timer-driven brain (FallbackBrainInterval,
 * default 0.2s) that mirrors the intended BT recipe exactly:
 *   - hero (player 0) dead/absent  -> patrol PatrolPoints (same cycling logic
 *     the BT service uses, via ANPCMinionCharacter::AdvancePatrolAndGetDestination)
 *   - Dist <= AttackRange          -> CombatComponent::RequestAttack (public API
 *     only — hit-guard safety) when the shared ComputeCanAct gate passes; SetFocus
 *   - Dist <= AggroRange           -> MoveTo(hero) with acceptance strictly
 *     inside AttackRange and capsule-radius reach inflation OFF (so arrival
 *     always lands in swing range); SetFocus within FallbackFocusRange
 *   - else                         -> patrol, ClearFocus
 * Authoring a BehaviorTree asset overrides the fallback entirely.
 *
 * BLACKBOARD KEYS CONTRACT — the Blackboard asset assigned to BehaviorTreeAsset
 * MUST define exactly these keys (names are matched by the FName constants below,
 * written by BTService_MinionCombatState unless noted):
 *
 *   TargetActor       Object (base class Actor) — the hero pawn; cleared while
 *                     the hero is dead so MoveTo/attack branches fall through.
 *   DistanceToTarget  Float — cm from minion to hero, refreshed ~5x/s.
 *   bCanAct           Bool  — !IsReacting() && !IsDead() && !IsAttacking(),
 *                     mirrors the boss's action gate. For observers/abort
 *                     triggers only; the hard gate is BTDecorator_MinionCanAct,
 *                     which re-reads the components live.
 *   bTargetDead       Bool  — hero's CombatComponent reports dead.
 *   HomeLocation      Vector — set ONCE here at possess, from the pawn location.
 *   PatrolLocation    Vector — current patrol destination for the stock
 *                     BTTask_MoveTo (cycles ANPCMinionCharacter::PatrolPoints,
 *                     falls back to HomeLocation when the route is empty).
 */
UCLASS()
class GAME_CORE_API AMinionAIController : public AAIController
{
	GENERATED_BODY()

public:
	/** Behavior tree started at possess. Null = the built-in fallback brain runs instead. */
	UPROPERTY(EditDefaultsOnly, Category = "Minion")
	TObjectPtr<UBehaviorTree> BehaviorTreeAsset;

	// --- Fallback brain tuning (only consulted when BehaviorTreeAsset is null) ---

	/** Within this range (cm) the fallback brain stops and swings via RequestAttack. */
	UPROPERTY(EditAnywhere, Category = "Minion|Fallback", meta = (ClampMin = "0.0"))
	float AttackRange = 250.0f;

	/** Within this range (cm) the fallback brain chases the hero (MoveTo with acceptance = max(50, AttackRange - 100), no capsule-radius reach inflation). */
	UPROPERTY(EditAnywhere, Category = "Minion|Fallback", meta = (ClampMin = "0.0"))
	float AggroRange = 2500.0f;

	/** Within this range (cm) the fallback brain keeps SetFocus on the hero (matches the BT service's FocusRange). */
	UPROPERTY(EditAnywhere, Category = "Minion|Fallback", meta = (ClampMin = "0.0"))
	float FallbackFocusRange = 800.0f;

	/** Distance (cm) at which a patrol point counts as reached (matches the BT service's PatrolAcceptanceRadius). */
	UPROPERTY(EditAnywhere, Category = "Minion|Fallback", meta = (ClampMin = "0.0"))
	float FallbackPatrolAcceptanceRadius = 150.0f;

	/** Fallback brain think cadence in seconds (matches the BT service's 0.2s interval). */
	UPROPERTY(EditAnywhere, Category = "Minion|Fallback", meta = (ClampMin = "0.05"))
	float FallbackBrainInterval = 0.2f;

	// Blackboard key names — single source of truth shared by the BT node kit.
	static const FName TargetActorKey;
	static const FName DistanceToTargetKey;
	static const FName CanActKey;
	static const FName TargetDeadKey;
	static const FName HomeLocationKey;
	static const FName PatrolLocationKey;

	/**
	 * THE minion action gate, shared by BTService_MinionCombatState (BB mirror),
	 * BTDecorator_MinionCanAct (hard gate) and the fallback brain:
	 * Combat && !IsDead() && !IsAttacking() && (!HitReaction || !IsReacting()).
	 * Live component read every call — never caches (corpse components are
	 * destroyed deferred, so cached pointers dangle).
	 */
	static bool ComputeCanAct(const APawn* Pawn);

	/**
	 * Stops the fallback brain: clears the think timer, aborts any in-flight
	 * move and drops focus. Idempotent; safe when the brain never started.
	 * Called from ANPCMinionCharacter::HandleDeath (alongside BrainComponent::
	 * StopLogic for the BT path) and from OnUnPossess.
	 */
	void StopBrain();

	/** True while the timer-driven fallback brain is running (no BT assigned). */
	bool IsFallbackBrainActive() const { return FallbackBrainTimerHandle.IsValid(); }

protected:
	virtual void OnPossess(APawn* InPawn) override;
	virtual void OnUnPossess() override;

private:
	/** One think step of the fallback brain (~FallbackBrainInterval cadence). */
	void TickFallbackBrain();

	/** Patrol leg of the fallback brain: cycle PatrolPoints / fall back to home. */
	void FallbackPatrol(APawn& MinionPawn);

	FTimerHandle FallbackBrainTimerHandle;

	/** Possess-time pawn location — same anchor the BT path writes into HomeLocation. */
	FVector FallbackHomeLocation = FVector::ZeroVector;

	/** Last destination issued to MoveToLocation, so the 0.2s brain doesn't re-path every think. */
	FVector FallbackPatrolDestination = FVector::ZeroVector;
};
