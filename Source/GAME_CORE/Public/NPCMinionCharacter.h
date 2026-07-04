#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "NPCMinionCharacter.generated.h"

class UCombatComponent;
class UHitReactionComponent;
class UHitFeedbackComponent;

/**
 * BT-driven patrol minion (ROADMAP M3). Deliberately ACharacter-based — unlike
 * BP_NeuralHero / BP_Boss (Mover pawns) — so stock AIController + BehaviorTree
 * MoveTo pathing works out of the box with zero Mover workarounds.
 *
 * Reuses the full combat stack via components: CombatComponent (attacks, HP,
 * death), HitReactionComponent (flinch + stagger), HitFeedbackComponent
 * (hit-stop). ANS_DealDamage finds all of them via FindComponentByClass, so a
 * minion trades hits with the hero with no extra wiring.
 *
 * MONTAGE MUTATION CAVEAT (project-wide, applies here with force): minion BPs
 * MUST use DUPLICATED montage assets and their OWN CombatAnimConfig assets.
 * PlayComboMontage / RequestDodge / PlayHitReaction write BlendIn/BlendOut and
 * root-motion flags onto the montage asset before play — sharing any montage
 * with the hero, the boss, or another minion class interleaves those writes.
 * Ctrl+D-duplicate every montage before assigning it in the minion BP.
 *
 * Setup notes for the BP child class:
 * - DeathMontage: assign on CombatComponent — ApplyDamage plays it at HP→0.
 *   HandleDeath here deliberately does NOT play anything (no double-play).
 * - HitFeedbackComponent: leave HitCameraShake UNSET — PlayCameraShake always
 *   shakes player controller 0, so a minion getting hit across the map would
 *   shake the player's camera. Per-actor hit-stop still works.
 * - Tagged "Enemy" in the ctor so the hero's LockOnComponent soft-locks minions.
 *   Side effect: a minion closer than the boss steals the soft-lock.
 *
 * Facing choice: bUseControllerRotationYaw=false, orient-to-movement=false,
 * bUseControllerDesiredRotation=true. The AI controller's focus (set by
 * BTService_MinionCombatState) drives control rotation, and CharacterMovement
 * interpolates the pawn toward it at RotationRate — smooth facing toward the
 * hero in combat, and path-direction facing while patrolling (with no focus
 * set, AAIController::UpdateControlRotation falls back to the move direction).
 */
UCLASS()
class GAME_CORE_API ANPCMinionCharacter : public ACharacter
{
	GENERATED_BODY()

public:
	ANPCMinionCharacter();

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Minion")
	TObjectPtr<UCombatComponent> CombatComponent;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Minion")
	TObjectPtr<UHitReactionComponent> HitReactionComponent;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Minion")
	TObjectPtr<UHitFeedbackComponent> HitFeedbackComponent;

	/** Seconds the corpse persists after death before the actor is destroyed. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Minion", meta = (ClampMin = "0.0"))
	float CorpseLifetime = 8.0f;

	/** Ordered patrol route. Filled by AMinionEncounterSpawner at spawn (or set by
	 *  hand on placed minions). BTService_MinionCombatState cycles through these,
	 *  writing the current destination into the PatrolLocation blackboard key for
	 *  the stock BTTask_MoveTo. Empty = patrol destination falls back to HomeLocation. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Minion")
	TArray<TObjectPtr<AActor>> PatrolPoints;

	/** Index of the patrol point currently being walked to. Advanced by
	 *  AdvancePatrolAndGetDestination (called from BTService_MinionCombatState
	 *  or the controller's fallback brain) when the minion reaches it. */
	UPROPERTY(Transient)
	int32 CurrentPatrolIndex = 0;

	/**
	 * Shared patrol-route logic (single source of truth for BOTH brains: the BT
	 * service's PatrolLocation feed and AMinionAIController's fallback brain).
	 * Advances CurrentPatrolIndex when the pawn is within AcceptanceRadius (2D)
	 * of the current point (or the point went away), then returns the location
	 * of the point now being walked to. Returns FallbackDestination when the
	 * route is empty (convention: the possess-time home location).
	 */
	FVector AdvancePatrolAndGetDestination(const FVector& FallbackDestination, float AcceptanceRadius);

protected:
	virtual void BeginPlay() override;

	/** Bound to CombatComponent::OnHealthDepleted. Stops the brain, drops collision,
	 *  detaches the controller, and lets the corpse linger for CorpseLifetime.
	 *  Also removes the "Enemy" tag (so LockOn / profile scans drop the corpse)
	 *  and destroys Combat/HitReaction components on the next tick so no
	 *  FindComponentByClass consumer can touch combat state on a corpse.
	 *  Does NOT touch montages — ApplyDamage already played DeathMontage. */
	UFUNCTION()
	void HandleDeath();
};
