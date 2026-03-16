#include "PlayerProfileComponent.h"
#include "CombatComponent.h"
#include "GameFramework/Character.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonWriter.h"
#include "Serialization/JsonSerializer.h"

// ============================================================================
// FPlayerProfile
// ============================================================================

TArray<float> FPlayerProfile::ToFloatArray() const
{
	return {
		AggressionScore,
		DodgeTendency,
		BlockTendency,
		OpenerAggression,
		PressureResponse,
		KitingScore,
		ComboCompletionRate,
		PositionalVariance
	};
}

FString FPlayerProfile::ToJsonString() const
{
	return FString::Printf(
		TEXT("[%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f]"),
		AggressionScore, DodgeTendency, BlockTendency, OpenerAggression,
		PressureResponse, KitingScore, ComboCompletionRate, PositionalVariance
	);
}

void FPlayerProfile::FromJsonObject(const TSharedPtr<FJsonObject>& Obj)
{
	if (!Obj.IsValid()) return;

	AggressionScore = Obj->GetNumberField(TEXT("aggression"));
	DodgeTendency = Obj->GetNumberField(TEXT("dodge"));
	BlockTendency = Obj->GetNumberField(TEXT("block"));
	OpenerAggression = Obj->GetNumberField(TEXT("opener"));
	PressureResponse = Obj->GetNumberField(TEXT("pressure"));
	KitingScore = Obj->GetNumberField(TEXT("kiting"));
	ComboCompletionRate = Obj->GetNumberField(TEXT("combo_completion"));
	PositionalVariance = Obj->GetNumberField(TEXT("positional_variance"));
}

float FPlayerProfile::GetDimension(int32 Index) const
{
	switch (Index)
	{
	case 0: return AggressionScore;
	case 1: return DodgeTendency;
	case 2: return BlockTendency;
	case 3: return OpenerAggression;
	case 4: return PressureResponse;
	case 5: return KitingScore;
	case 6: return ComboCompletionRate;
	case 7: return PositionalVariance;
	default: return 0.5f;
	}
}

void FPlayerProfile::SetDimension(int32 Index, float Value)
{
	switch (Index)
	{
	case 0: AggressionScore = Value; break;
	case 1: DodgeTendency = Value; break;
	case 2: BlockTendency = Value; break;
	case 3: OpenerAggression = Value; break;
	case 4: PressureResponse = Value; break;
	case 5: KitingScore = Value; break;
	case 6: ComboCompletionRate = Value; break;
	case 7: PositionalVariance = Value; break;
	default: break;
	}
}

// ============================================================================
// UPlayerProfileComponent
// ============================================================================

UPlayerProfileComponent::UPlayerProfileComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
}

void UPlayerProfileComponent::BeginPlay()
{
	Super::BeginPlay();

	PositionHistory.SetNum(PositionHistorySize);
	BindToCombatComponent();
	ResetEncounterTracking();
}

void UPlayerProfileComponent::BindToCombatComponent()
{
	AActor* Owner = GetOwner();
	if (!Owner) return;

	OwnerCombatComp = Owner->FindComponentByClass<UCombatComponent>();
	if (OwnerCombatComp)
	{
		OwnerCombatComp->OnAttackLanded.AddDynamic(this, &UPlayerProfileComponent::OnOwnerAttackLanded);
	}
}

void UPlayerProfileComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	SampleAccumulator += DeltaTime;
	if (SampleAccumulator < SampleInterval) return;
	SampleAccumulator -= SampleInterval;

	AActor* Owner = GetOwner();
	if (!Owner) return;

	EncounterStepCount++;

	// --- Distance sampling ---
	if (BossActor)
	{
		const float Dist = FVector::Dist(Owner->GetActorLocation(), BossActor->GetActorLocation());
		if (Dist < MeleeRangeThreshold)
		{
			MeleeSamples++;
		}
		else
		{
			RangeSamples++;
		}

		// Update kiting EMA
		const int32 TotalDistSamples = MeleeSamples + RangeSamples;
		if (TotalDistSamples > 0)
		{
			const float InstantKiting = static_cast<float>(RangeSamples) / TotalDistSamples;
			EmaKitingRate = EmaAlpha * InstantKiting + (1.0f - EmaAlpha) * EmaKitingRate;
		}
	}

	// --- Position history for variance ---
	{
		const FVector Loc = Owner->GetActorLocation();
		PositionHistory[PositionHistoryIndex] = FVector2D(Loc.X, Loc.Y);
		PositionHistoryIndex = (PositionHistoryIndex + 1) % PositionHistorySize;
	}

	// --- Opener phase tracking ---
	// The opener is the first 20% of the encounter. We estimate encounter length
	// by checking if enough samples have been taken. After 200 samples (~50 seconds
	// at 4 Hz), we close the opener window if not already closed.
	if (!bOpenerPhaseComplete)
	{
		OpenerStepCount++;

		// Check if player is attacking during opener
		if (OwnerCombatComp && OwnerCombatComp->IsAttacking())
		{
			OpenerAttackCount++;
		}

		// Close opener at 20% of a typical encounter (~40 samples = 10 seconds)
		if (OpenerStepCount >= 40)
		{
			bOpenerPhaseComplete = true;
		}
	}

	// --- Pressure response sampling ---
	if (OwnerCombatComp)
	{
		const float HpPercent = (OwnerCombatComp->MaxHealth > 0.0f)
			? OwnerCombatComp->CurrentHealth / OwnerCombatComp->MaxHealth
			: 1.0f;

		if (HpPercent < 0.3f)
		{
			LowHpSamples++;
			if (OwnerCombatComp->IsAttacking())
			{
				LowHpAttackSamples++;
			}
		}
	}
}

FPlayerProfile UPlayerProfileComponent::GetProfile() const
{
	FPlayerProfile Profile;

	// Aggression: ratio of attacks to total actions
	Profile.AggressionScore = EmaAttackRate;

	// Dodge tendency: ratio of dodges to incoming attacks
	Profile.DodgeTendency = EmaDodgeRate;

	// Block tendency: ratio of blocks to incoming attacks
	Profile.BlockTendency = EmaBlockRate;

	// Opener aggression: attack rate in first 20% of encounter
	if (bOpenerPhaseComplete && OpenerStepCount > 0)
	{
		Profile.OpenerAggression = FMath::Clamp(
			static_cast<float>(OpenerAttackCount) / OpenerStepCount, 0.0f, 1.0f);
	}
	else
	{
		Profile.OpenerAggression = 0.5f; // neutral until opener phase completes
	}

	// Pressure response: attack rate when HP < 30%
	if (LowHpSamples > 5) // need enough samples for meaningful data
	{
		Profile.PressureResponse = FMath::Clamp(
			static_cast<float>(LowHpAttackSamples) / LowHpSamples, 0.0f, 1.0f);
	}
	else
	{
		Profile.PressureResponse = 0.5f;
	}

	// Kiting score: EMA of time at range vs melee
	Profile.KitingScore = FMath::Clamp(EmaKitingRate, 0.0f, 1.0f);

	// Combo completion rate
	if (CombosStarted > 0)
	{
		Profile.ComboCompletionRate = FMath::Clamp(
			static_cast<float>(CombosCompleted) / CombosStarted, 0.0f, 1.0f);
	}
	else
	{
		Profile.ComboCompletionRate = 0.5f;
	}

	// Positional variance
	Profile.PositionalVariance = FMath::Clamp(ComputePositionalVariance(), 0.0f, 1.0f);

	return Profile;
}

void UPlayerProfileComponent::ResetEncounterTracking()
{
	TotalActions = 0;
	AttackActions = 0;
	IncomingAttacks = 0;
	DodgedAttacks = 0;
	BlockedAttacks = 0;
	CombosStarted = 0;
	CombosCompleted = 0;
	EncounterStepCount = 0;
	OpenerStepCount = 0;
	OpenerAttackCount = 0;
	bOpenerPhaseComplete = false;
	LowHpSamples = 0;
	LowHpAttackSamples = 0;
	MeleeSamples = 0;
	RangeSamples = 0;
	PositionHistoryIndex = 0;
	SampleAccumulator = 0.0f;

	for (int32 i = 0; i < PositionHistory.Num(); i++)
	{
		PositionHistory[i] = FVector2D::ZeroVector;
	}
}

void UPlayerProfileComponent::RecordAttack()
{
	TotalActions++;
	AttackActions++;

	// Update aggression EMA
	if (TotalActions > 0)
	{
		const float InstantRate = static_cast<float>(AttackActions) / TotalActions;
		EmaAttackRate = EmaAlpha * InstantRate + (1.0f - EmaAlpha) * EmaAttackRate;
	}
}

void UPlayerProfileComponent::RecordDodge()
{
	IncomingAttacks++;
	DodgedAttacks++;

	if (IncomingAttacks > 0)
	{
		const float InstantRate = static_cast<float>(DodgedAttacks) / IncomingAttacks;
		EmaDodgeRate = EmaAlpha * InstantRate + (1.0f - EmaAlpha) * EmaDodgeRate;
	}
}

void UPlayerProfileComponent::RecordBlock()
{
	IncomingAttacks++;
	BlockedAttacks++;

	if (IncomingAttacks > 0)
	{
		const float InstantRate = static_cast<float>(BlockedAttacks) / IncomingAttacks;
		EmaBlockRate = EmaAlpha * InstantRate + (1.0f - EmaAlpha) * EmaBlockRate;
	}
}

void UPlayerProfileComponent::RecordHitTaken()
{
	IncomingAttacks++;

	// Update dodge and block EMA (they didn't dodge or block)
	if (IncomingAttacks > 0)
	{
		const float DodgeRate = static_cast<float>(DodgedAttacks) / IncomingAttacks;
		EmaDodgeRate = EmaAlpha * DodgeRate + (1.0f - EmaAlpha) * EmaDodgeRate;

		const float BlockRate = static_cast<float>(BlockedAttacks) / IncomingAttacks;
		EmaBlockRate = EmaAlpha * BlockRate + (1.0f - EmaAlpha) * EmaBlockRate;
	}
}

void UPlayerProfileComponent::RecordComboStarted()
{
	CombosStarted++;
}

void UPlayerProfileComponent::RecordComboCompleted()
{
	CombosCompleted++;
}

void UPlayerProfileComponent::OnOwnerAttackLanded(float DamageAmount, FName DamageType)
{
	RecordAttack();
}

float UPlayerProfileComponent::ComputePositionalVariance() const
{
	if (EncounterStepCount < PositionHistorySize) return 0.5f;

	// Compute centroid
	FVector2D Centroid = FVector2D::ZeroVector;
	for (const FVector2D& Pos : PositionHistory)
	{
		Centroid += Pos;
	}
	Centroid /= PositionHistory.Num();

	// Compute variance (average squared distance from centroid)
	float Variance = 0.0f;
	for (const FVector2D& Pos : PositionHistory)
	{
		Variance += FVector2D::DistSquared(Pos, Centroid);
	}
	Variance /= PositionHistory.Num();

	// Normalize: sqrt(variance) / a reference distance (500 units = moderate mobility)
	const float StdDev = FMath::Sqrt(Variance);
	return FMath::Clamp(StdDev / 500.0f, 0.0f, 1.0f);
}
