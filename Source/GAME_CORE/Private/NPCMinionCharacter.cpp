#include "NPCMinionCharacter.h"
#include "MinionAIController.h"
#include "CombatComponent.h"
#include "HitReactionComponent.h"
#include "HitFeedbackComponent.h"
#include "AIController.h"
#include "BrainComponent.h"
#include "Components/CapsuleComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "TimerManager.h"

ANPCMinionCharacter::ANPCMinionCharacter()
{
	PrimaryActorTick.bCanEverTick = true;

	CombatComponent      = CreateDefaultSubobject<UCombatComponent>(TEXT("CombatComponent"));
	HitReactionComponent = CreateDefaultSubobject<UHitReactionComponent>(TEXT("HitReactionComponent"));
	HitFeedbackComponent = CreateDefaultSubobject<UHitFeedbackComponent>(TEXT("HitFeedbackComponent"));

	// LockOnComponent targets by this actor tag (same convention as BP_Boss).
	Tags.Add(FName(TEXT("Enemy")));

	// Possess automatically whether hand-placed or spawned by the encounter spawner.
	AutoPossessAI = EAutoPossessAI::PlacedInWorldOrSpawned;
	AIControllerClass = AMinionAIController::StaticClass();

	// Facing: the AI controller's focus (hero in combat range, move direction
	// otherwise) drives control rotation; CharacterMovement interpolates the pawn
	// toward it. See the class comment for why this beats orient-to-movement here.
	bUseControllerRotationYaw = false;
	if (UCharacterMovementComponent* Move = GetCharacterMovement())
	{
		Move->bOrientRotationToMovement = false;
		Move->bUseControllerDesiredRotation = true;
		Move->RotationRate = FRotator(0.0f, 360.0f, 0.0f);
	}
}

void ANPCMinionCharacter::BeginPlay()
{
	Super::BeginPlay();

	if (CombatComponent)
	{
		// HARD RULE: a dying minion must never trigger the full-arena round reset
		// (TriggerRoundReset resets EVERY combatant to spawn + full HP). Force the
		// flag off even if a BP child ticked it by accident.
		CombatComponent->bAutoResetRoundOnDeath = false;

		// HARD RULE #2: a minion must never BE reset by the arena sweep either.
		// TriggerRoundReset (hero or boss death) iterates every CombatComponent;
		// without this opt-out a live minion gets healed + teleported to its ring
		// point mid-encounter, and a corpse inside CorpseLifetime gets "revived"
		// into an unpossessed, collision-less ghost the pending SetLifeSpan then
		// destroys mid-round.
		CombatComponent->bParticipatesInArenaReset = false;

		CombatComponent->OnHealthDepleted.AddDynamic(this, &ANPCMinionCharacter::HandleDeath);
	}
}

FVector ANPCMinionCharacter::AdvancePatrolAndGetDestination(const FVector& FallbackDestination, float AcceptanceRadius)
{
	const int32 NumPoints = PatrolPoints.Num();
	if (NumPoints == 0)
	{
		return FallbackDestination;
	}

	int32 Index = FMath::Clamp(CurrentPatrolIndex, 0, NumPoints - 1);
	const AActor* Point = PatrolPoints[Index];

	// Reached (or lost) the current point → advance the route.
	if (!Point || FVector::Dist2D(GetActorLocation(), Point->GetActorLocation()) <= AcceptanceRadius)
	{
		Index = (Index + 1) % NumPoints;
		CurrentPatrolIndex = Index;
		Point = PatrolPoints[Index];
	}

	return Point ? Point->GetActorLocation() : FallbackDestination;
}

void ANPCMinionCharacter::HandleDeath()
{
	// Stop the brain first so no in-flight BT task fires an action into the corpse.
	if (AAIController* AICon = Cast<AAIController>(GetController()))
	{
		if (UBrainComponent* Brain = AICon->GetBrainComponent())
		{
			Brain->StopLogic(TEXT("Dead"));
		}
		// The fallback code-brain (runs when no BT asset is assigned) has its own
		// timer — stop it the same way StopLogic stops the BT. Idempotent.
		if (AMinionAIController* MinionCon = Cast<AMinionAIController>(AICon))
		{
			MinionCon->StopBrain();
		}
		AICon->ClearFocus(EAIFocusPriority::Gameplay);
	}

	// Corpse state: no capsule collision (the hero shouldn't be body-blocked by a
	// body, and ANS_DealDamage sweeps ECC_Pawn — a colliding corpse would still
	// absorb single-target swings meant for someone else), no movement, no
	// controller. DeathMontage was already played inside CombatComponent::
	// ApplyDamage — deliberately NOT played again here.
	GetCapsuleComponent()->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	if (UCharacterMovementComponent* Move = GetCharacterMovement())
	{
		Move->StopMovementImmediately();
		Move->DisableMovement();
	}

	DetachFromControllerPendingDestroy();
	SetLifeSpan(FMath::Max(CorpseLifetime, 0.1f));

	// Drop out of every targeting/scan path immediately: the corpse must not be
	// soft-locked by LockOnComponent nor sampled by PlayerProfileComponent's
	// nearest-live-opponent tag scan for the CorpseLifetime window.
	Tags.Remove(FName(TEXT("Enemy")));

	// Belt-and-braces vs. the arena round-reset sweep (and any other
	// FindComponentByClass consumer): strip the combat state off the corpse so
	// nothing can find/reset/damage it. Deferred to the next tick — HandleDeath
	// runs inside CombatComponent's own OnHealthDepleted broadcast, so destroying
	// the component inline would rip state out from under the broadcasting code.
	if (UWorld* World = GetWorld())
	{
		World->GetTimerManager().SetTimerForNextTick(FTimerDelegate::CreateWeakLambda(this, [this]()
		{
			if (CombatComponent)
			{
				CombatComponent->DestroyComponent();
				CombatComponent = nullptr;
			}
			if (HitReactionComponent)
			{
				HitReactionComponent->DestroyComponent();
				HitReactionComponent = nullptr;
			}
		}));
	}

	UE_LOG(LogTemp, Log, TEXT("NPCMinionCharacter[%s]: dead — corpse despawns in %.1fs"),
		*GetName(), CorpseLifetime);
}
