#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "AutoHeroComponent.generated.h"

class UCombatComponent;
class UBossActionComponent;
class UInputAction;

/**
 * One sparring-bot personality. Each persona is a synthetic "player" whose
 * fights fill replays/{persona}/ — the multi-player data MAML meta-training
 * and transfer learning need (ROADMAP.md M1).
 */
USTRUCT(BlueprintType)
struct FAutoHeroPersona
{
	GENERATED_BODY()

	/** 0-1: how eagerly the bot attacks when in range. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	float Aggression = 0.6f;

	/** Distance (cm) the bot tries to hover at when not committing. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	float PreferredRange = 300.0f;

	/** 0-1: chance to dash sideways/back when the boss starts its attack montage. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	float EvadeReactChance = 0.3f;

	/** 0-1: chance to raise block (instead of dodging) when the boss starts a swing.
	 *  Rolled against before the evade roll, so a turtle persona favours guarding. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	float BlockChance = 0.2f;

	/** How long (s) the bot holds the guard once it raises block. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	float BlockHoldDuration = 0.8f;

	/** 0-1: chance per decision to buffer the next combo step while attacking. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	float ComboCommitment = 0.6f;

	/** Seconds between decisions. Human-ish: 0.15 (twitchy) to 0.4 (deliberate). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	float DecisionInterval = 0.25f;

	/** 0-1: preference for circling vs holding still when in the comfort band. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	float StrafeBias = 0.4f;

	/** 0-1: chance to feed a random WASD direction into SetMovementInput before
	 *  attacking, so all four directional combo configs get exercised. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	float DirectionalAttackChance = 0.5f;

	/** Counter-style: guaranteed punish attempt right after a boss swing ends. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	bool bPunishAfterBossSwing = false;
};

/**
 * Sparring bot that plays BP_NeuralHero so the boss can train unattended
 * (ROADMAP.md M1). Drives ONLY the existing public combat API
 * (CombatComponent::SetMovementInput / RequestAttack) plus APawn movement
 * input, so normal play is untouched when disabled.
 *
 * Activation:
 *  - launch arg:  -AutoHero=rusher   (used by Tools/run_training.ps1)
 *  - or tick bEnabled on the component in the BP for a PIE smoke test.
 *
 * Built-in personas: rusher, turtle, kiter, counter, chaotic.
 */
UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UAutoHeroComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UAutoHeroComponent();

	/** Manual switch for PIE testing. The -AutoHero= launch arg sets this too. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	bool bEnabled = false;

	/** Active persona values (overwritten by LoadPersona). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	FAutoHeroPersona Persona;

	/** Name of the active persona (for logs / replay folder naming). */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "AutoHero")
	FString PersonaName = TEXT("custom");

	/** Max distance (cm) at which RequestAttack is worth pressing.
	 *  Matches the hand-socket trace reach (hand bone extends ~80cm from the
	 *  actor center at peak + 30cm radius = ~110cm; +50cm slack for the swing
	 *  startup window where the bot would otherwise stutter). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	float AttackRange = 160.0f;

	/** Rotate the pawn to face the boss while botting (PostPhysics, same
	 *  pattern as BossActionComponent) so attack traces actually connect. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	float FaceTargetInterpSpeed = 10.0f;

	/** ASSIGN IA_Move HERE. The hero's Mover input producer reads Enhanced
	 *  Input, not APawn::AddMovementInput (CLAUDE.md Mover gotchas), so the bot
	 *  injects movement through the real input pipeline — same path as a human,
	 *  including the IA_Move -> SetMovementInput combo-direction hook.
	 *  If unset, falls back to AddMovementInput (works for boss-style pawns). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "AutoHero")
	TObjectPtr<UInputAction> MoveAction;

	/** Apply a named built-in persona. Returns false for unknown names. */
	UFUNCTION(BlueprintCallable, Category = "AutoHero")
	bool LoadPersona(const FString& InName);

protected:
	virtual void BeginPlay() override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	enum class EBotState : uint8 { Hold, Approach, Retreat, Strafe };

	void FindBoss();
	bool IsBossSwinging() const;
	void DecideState(float Dist, double Now);
	void TryAttack(float Dist, double Now);
	void ApplyMovement(const FVector& ToBossDir, float DeltaTime);
	void StartEvade(const FVector& ToBossDir, double Now);
	void StartBlock(double Now);
	void ReleaseBlock();

	/** Route a world-space move direction into the pawn — Enhanced Input
	 *  injection when MoveAction is set, AddMovementInput otherwise. */
	void InjectMove(const FVector& WorldDir);

	/** World direction -> IA_Move convention (X = right, Y = forward, in
	 *  control-rotation space) — the inverse of SetMovementInput's transform. */
	FVector2D WorldDirToInputSpace(const FVector& WorldDir) const;

	UPROPERTY()
	TObjectPtr<UCombatComponent> Combat;

	TWeakObjectPtr<AActor> BossActor;
	TWeakObjectPtr<UBossActionComponent> BossAction;
	TWeakObjectPtr<UCombatComponent> BossCombat;

	EBotState State = EBotState::Hold;
	double NextDecisionTime = 0.0;
	double NextBossSearchTime = 0.0;

	// Evade burst (movement stand-in for dodge until RequestDodge exists)
	double EvadeUntil = 0.0;
	FVector EvadeDir = FVector::ZeroVector;
	bool bEvadeRolledThisSwing = false;

	// Block hold state
	bool bBlockingNow = false;
	double BlockUntil = 0.0;

	// Counter persona: punish window after a boss swing ends
	bool bBossWasSwinging = false;
	double PunishUntil = 0.0;

	float StrafeSign = 1.0f;
};
