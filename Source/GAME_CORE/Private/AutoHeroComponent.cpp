#include "AutoHeroComponent.h"
#include "CombatComponent.h"
#include "BossActionComponent.h"
#include "Animation/AnimInstance.h"
#include "Components/SkeletalMeshComponent.h"
#include "EngineUtils.h"
#include "EnhancedInputSubsystems.h"
#include "Engine/LocalPlayer.h"
#include "GameFramework/Controller.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "InputAction.h"
#include "InputActionValue.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

namespace
{
	// Movement evade burst length (stand-in for a real dodge until guide.md 1.3).
	constexpr float EvadeDuration = 0.35f;
	// Only bother evading swings that start inside this range.
	constexpr float EvadeTriggerRange = 420.0f;
	// Counter persona: how long the post-swing punish window stays open.
	constexpr float PunishWindow = 0.6f;
	// Comfort band around PreferredRange before the bot corrects distance.
	constexpr float RangeSlack = 40.0f;
}

UAutoHeroComponent::UAutoHeroComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	// Tick after Mover has integrated movement/rotation, same as
	// BossActionComponent — otherwise Mover overwrites our facing each frame.
	PrimaryComponentTick.TickGroup = TG_PostPhysics;
}

bool UAutoHeroComponent::LoadPersona(const FString& InName)
{
	const FString Key = InName.ToLower();
	FAutoHeroPersona P;

	// Distances retuned for hand-socket trace (~110cm reach). PreferredRange =
	// where the bot hovers; AttackRange (160cm default) is the press-button gate.
	if (Key == TEXT("rusher"))
	{
		P.Aggression = 0.9f;  P.PreferredRange = 110.f; P.EvadeReactChance = 0.1f;
		P.ComboCommitment = 0.9f; P.DecisionInterval = 0.2f; P.StrafeBias = 0.2f;
		P.DirectionalAttackChance = 0.5f; P.bPunishAfterBossSwing = false;
		P.BlockChance = 0.05f;
	}
	else if (Key == TEXT("turtle"))
	{
		P.Aggression = 0.25f; P.PreferredRange = 220.f; P.EvadeReactChance = 0.3f;
		P.ComboCommitment = 0.4f; P.DecisionInterval = 0.35f; P.StrafeBias = 0.35f;
		P.DirectionalAttackChance = 0.4f; P.bPunishAfterBossSwing = false;
		P.BlockChance = 0.6f;
	}
	else if (Key == TEXT("kiter"))
	{
		P.Aggression = 0.45f; P.PreferredRange = 280.f; P.EvadeReactChance = 0.5f;
		P.ComboCommitment = 0.5f; P.DecisionInterval = 0.25f; P.StrafeBias = 0.7f;
		P.DirectionalAttackChance = 0.6f; P.bPunishAfterBossSwing = false;
		P.BlockChance = 0.1f;
	}
	else if (Key == TEXT("counter"))
	{
		P.Aggression = 0.35f; P.PreferredRange = 160.f; P.EvadeReactChance = 0.4f;
		P.ComboCommitment = 0.7f; P.DecisionInterval = 0.2f; P.StrafeBias = 0.4f;
		P.DirectionalAttackChance = 0.5f; P.bPunishAfterBossSwing = true;
		P.BlockChance = 0.4f;
	}
	else if (Key == TEXT("chaotic"))
	{
		P.Aggression = 0.6f;  P.PreferredRange = 180.f; P.EvadeReactChance = 0.3f;
		P.ComboCommitment = 0.5f; P.DecisionInterval = 0.15f; P.StrafeBias = 0.5f;
		P.DirectionalAttackChance = 1.0f; P.bPunishAfterBossSwing = false;
		P.BlockChance = 0.25f;
	}
	else
	{
		UE_LOG(LogTemp, Warning, TEXT("AutoHero: Unknown persona '%s' — keeping current values"), *InName);
		return false;
	}

	Persona = P;
	PersonaName = Key;
	return true;
}

void UAutoHeroComponent::BeginPlay()
{
	Super::BeginPlay();

	Combat = GetOwner() ? GetOwner()->FindComponentByClass<UCombatComponent>() : nullptr;

	// -AutoHero=<persona> activates the bot for unattended training runs
	// (Tools/run_training.ps1 passes this).
	FString ArgPersona;
	if (FParse::Value(FCommandLine::Get(), TEXT("AutoHero="), ArgPersona) && !ArgPersona.IsEmpty())
	{
		LoadPersona(ArgPersona);
		bEnabled = true;
	}

	if (bEnabled)
	{
		UE_LOG(LogTemp, Log, TEXT("AutoHero: ENABLED — persona=%s (aggr=%.2f range=%.0f evade=%.2f)"),
			*PersonaName, Persona.Aggression, Persona.PreferredRange, Persona.EvadeReactChance);

		if (!Combat)
		{
			UE_LOG(LogTemp, Warning, TEXT("AutoHero: owner has no CombatComponent — bot cannot attack"));
		}
	}
}

void UAutoHeroComponent::FindBoss()
{
	for (TActorIterator<APawn> It(GetWorld()); It; ++It)
	{
		if (*It == GetOwner()) continue;
		if (UBossActionComponent* Action = It->FindComponentByClass<UBossActionComponent>())
		{
			BossActor = *It;
			BossAction = Action;
			BossCombat = It->FindComponentByClass<UCombatComponent>();
			UE_LOG(LogTemp, Log, TEXT("AutoHero: target acquired — %s"), *It->GetName());
			return;
		}
	}
}

bool UAutoHeroComponent::IsBossSwinging() const
{
	if (!BossActor.IsValid() || !BossAction.IsValid() || !BossAction->AttackMontage) return false;

	const USkeletalMeshComponent* Mesh = BossActor->FindComponentByClass<USkeletalMeshComponent>();
	const UAnimInstance* Anim = Mesh ? Mesh->GetAnimInstance() : nullptr;
	return Anim && Anim->Montage_IsPlaying(BossAction->AttackMontage);
}

void UAutoHeroComponent::StartEvade(const FVector& ToBossDir, double Now)
{
	// Sideways-and-back relative to the boss, random side.
	const FVector Side = FVector::CrossProduct(FVector::UpVector, ToBossDir).GetSafeNormal2D();
	const float Sign = (FMath::FRand() < 0.5f) ? 1.f : -1.f;
	EvadeDir = (Side * Sign - ToBossDir * 0.5f).GetSafeNormal2D();
	EvadeUntil = Now + EvadeDuration;

	// Prefer a REAL dodge when montages are assigned: feed the evade direction
	// into the combo-direction cache first so directional selection picks the
	// matching roll. Falls through to the movement burst when no montage exists
	// (RequestDodge no-ops) or while attacking.
	if (Combat)
	{
		Combat->SetMovementInput(WorldDirToInputSpace(EvadeDir));
		Combat->RequestDodge();
	}
}

void UAutoHeroComponent::StartBlock(double Now)
{
	if (!Combat) return;
	// SetBlocking self-gates (refuses while attacking/dodging/dead).
	Combat->SetBlocking(true);
	if (Combat->IsBlocking())
	{
		bBlockingNow = true;
		BlockUntil = Now + FMath::Max(Persona.BlockHoldDuration, 0.1f);
	}
}

void UAutoHeroComponent::ReleaseBlock()
{
	bBlockingNow = false;
	if (Combat)
	{
		Combat->SetBlocking(false);
	}
}

FVector2D UAutoHeroComponent::WorldDirToInputSpace(const FVector& WorldDir) const
{
	const APawn* Pawn = Cast<APawn>(GetOwner());
	FRotator Rot = (Pawn && Pawn->GetController())
		? Pawn->GetController()->GetControlRotation()
		: (GetOwner() ? GetOwner()->GetActorRotation() : FRotator::ZeroRotator);
	Rot.Pitch = 0.f;
	Rot.Roll = 0.f;

	const FRotationMatrix RotMat(Rot);
	return FVector2D(
		FVector::DotProduct(WorldDir, RotMat.GetUnitAxis(EAxis::Y)),   // X = right
		FVector::DotProduct(WorldDir, RotMat.GetUnitAxis(EAxis::X)));  // Y = forward
}

void UAutoHeroComponent::InjectMove(const FVector& WorldDir)
{
	APawn* Pawn = Cast<APawn>(GetOwner());
	if (!Pawn || WorldDir.IsNearlyZero()) return;

	// Preferred path: drive the REAL Enhanced Input pipeline. The hero pawn's
	// Mover input producer reads IA_Move (not APawn control input — the Mover
	// gotcha), and this also fires the IA_Move -> SetMovementInput combo hook
	// exactly like a human player would.
	if (MoveAction)
	{
		if (const APlayerController* PC = Cast<APlayerController>(Pawn->GetController()))
		{
			if (ULocalPlayer* LP = PC->GetLocalPlayer())
			{
				if (UEnhancedInputLocalPlayerSubsystem* Input = LP->GetSubsystem<UEnhancedInputLocalPlayerSubsystem>())
				{
					Input->InjectInputForAction(
						MoveAction,
						FInputActionValue(WorldDirToInputSpace(WorldDir)),
						TArray<UInputModifier*>(),
						TArray<UInputTrigger*>());
					return;
				}
			}
		}
	}

	// Fallback (MoveAction unset or AI-possessed): pawn control input — the
	// path BossActionComponent uses for the boss pawn.
	Pawn->AddMovementInput(WorldDir, 1.0f);
}

void UAutoHeroComponent::DecideState(float Dist, double Now)
{
	NextDecisionTime = Now + FMath::Max(Persona.DecisionInterval, 0.05f);

	if (Dist > Persona.PreferredRange + RangeSlack)
	{
		State = EBotState::Approach;
	}
	else if (Dist < Persona.PreferredRange - RangeSlack && FMath::FRand() > Persona.Aggression)
	{
		State = EBotState::Retreat;
	}
	else if (FMath::FRand() < Persona.StrafeBias)
	{
		State = EBotState::Strafe;
		if (FMath::FRand() < 0.3f) StrafeSign = -StrafeSign;
	}
	else
	{
		State = EBotState::Hold;
	}
}

void UAutoHeroComponent::TryAttack(float Dist, double Now)
{
	if (!Combat) return;

	// Continue an in-flight combo: RequestAttack while attacking buffers the
	// next chain step (CombatComponent drains it when the combo window opens).
	if (Combat->IsAttacking())
	{
		if (FMath::FRand() < Persona.ComboCommitment)
		{
			Combat->RequestAttack();
		}
		return;
	}

	if (Dist > AttackRange) return;

	const bool bPunish = Persona.bPunishAfterBossSwing && Now < PunishUntil;
	if (!bPunish && FMath::FRand() >= Persona.Aggression) return;

	// Feed a movement direction first so SelectComboByDirection exercises all
	// four directional configs — MAML needs variety, not 100% Neutral combos.
	if (FMath::FRand() < Persona.DirectionalAttackChance)
	{
		static const FVector2D Dirs[4] = { {0.f, 1.f}, {0.f, -1.f}, {1.f, 0.f}, {-1.f, 0.f} };
		Combat->SetMovementInput(Dirs[FMath::RandRange(0, 3)]);
	}
	else
	{
		Combat->ClearMovementInput();
	}

	Combat->RequestAttack();
}

void UAutoHeroComponent::ApplyMovement(const FVector& ToBossDir, float DeltaTime)
{
	APawn* Pawn = Cast<APawn>(GetOwner());
	if (!Pawn) return;

	FVector Dir = FVector::ZeroVector;
	switch (State)
	{
	case EBotState::Approach: Dir = ToBossDir; break;
	case EBotState::Retreat:  Dir = -ToBossDir; break;
	case EBotState::Strafe:   Dir = FVector::CrossProduct(FVector::UpVector, ToBossDir).GetSafeNormal2D() * StrafeSign; break;
	default: break;
	}

	if (!Dir.IsNearlyZero())
	{
		InjectMove(Dir);
	}
}

void UAutoHeroComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	if (!bEnabled || !GetOwner()) return;

	const double Now = GetWorld()->GetTimeSeconds();

	// Dead (or mid round-reset): do nothing; state clears itself on respawn.
	if (Combat && Combat->bIsDead)
	{
		Combat->ClearMovementInput();
		return;
	}

	if (!BossActor.IsValid() || !BossAction.IsValid())
	{
		if (Now >= NextBossSearchTime)
		{
			NextBossSearchTime = Now + 2.0;
			FindBoss();
		}
		return;
	}

	// Boss dead: idle until the round resets.
	if (BossAction->IsDead() || (BossCombat.IsValid() && BossCombat->bIsDead))
	{
		return;
	}

	const FVector OwnerLoc = GetOwner()->GetActorLocation();
	const FVector BossLoc = BossActor->GetActorLocation();
	FVector ToBoss = BossLoc - OwnerLoc;
	ToBoss.Z = 0.0;
	const float Dist = ToBoss.Size2D();
	const FVector ToBossDir = ToBoss.GetSafeNormal2D();

	// ── Face the boss (yaw only) so attack traces connect. Mirrors the
	//    SetActorRotation + TeleportPhysics pattern from BossActionComponent. ──
	if (!ToBossDir.IsNearlyZero())
	{
		const FRotator CurrentRot = GetOwner()->GetActorRotation();
		FRotator TargetRot = ToBossDir.Rotation();
		TargetRot.Pitch = CurrentRot.Pitch;
		TargetRot.Roll = CurrentRot.Roll;
		GetOwner()->SetActorRotation(
			FMath::RInterpTo(CurrentRot, TargetRot, DeltaTime, FaceTargetInterpSpeed),
			ETeleportType::TeleportPhysics);
	}

	// ── Reactive defense: one dice roll per boss swing — block OR dodge. ──
	const bool bSwinging = IsBossSwinging();
	if (bSwinging && !bEvadeRolledThisSwing && Dist < EvadeTriggerRange)
	{
		bEvadeRolledThisSwing = true;
		const float Roll = FMath::FRand();
		if (Roll < Persona.BlockChance)
		{
			StartBlock(Now);
		}
		else if (Roll < Persona.BlockChance + Persona.EvadeReactChance)
		{
			StartEvade(ToBossDir, Now);
		}
	}
	if (!bSwinging && bBossWasSwinging)
	{
		bEvadeRolledThisSwing = false;
		PunishUntil = Now + PunishWindow;   // counter persona's opening
	}
	bBossWasSwinging = bSwinging;

	// ── Block hold: stay guarded until the timer expires, then release and
	//    commit to nothing else this frame (blocking is a committed stance). ──
	if (bBlockingNow)
	{
		if (Now >= BlockUntil)
		{
			ReleaseBlock();
		}
		else
		{
			return;
		}
	}

	// While a dodge roll plays, root motion owns movement entirely.
	if (Combat && Combat->IsDodging())
	{
		return;
	}

	// Evade movement burst (the fallback when no dodge montage played).
	if (Now < EvadeUntil && !(Combat && Combat->IsAttacking()))
	{
		InjectMove(EvadeDir);
		return;
	}

	// While our own attack montage runs, let root motion own movement;
	// just keep buffering combo steps.
	if (Combat && Combat->IsAttacking())
	{
		if (Now >= NextDecisionTime)
		{
			NextDecisionTime = Now + FMath::Max(Persona.DecisionInterval, 0.05f);
			TryAttack(Dist, Now);
		}
		return;
	}

	if (Now >= NextDecisionTime)
	{
		DecideState(Dist, Now);
		TryAttack(Dist, Now);
	}

	ApplyMovement(ToBossDir, DeltaTime);
}
