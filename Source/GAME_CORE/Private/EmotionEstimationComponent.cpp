#include "EmotionEstimationComponent.h"

FString FEmotionEstimate::ToJsonString() const
{
	return FString::Printf(
		TEXT("{\"frustration\":%.3f,\"flow\":%.3f,\"boredom\":%.3f,\"dominant\":\"%s\"}"),
		FrustrationScore, FlowScore, BoredomScore,
		*UEnum::GetValueAsString(DominantState)
	);
}

UEmotionEstimationComponent::UEmotionEstimationComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.TickInterval = 0.25f; // 4 Hz sampling
}

void UEmotionEstimationComponent::TickComponent(float DeltaTime, ELevelTick TickType,
	FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	EncounterElapsedTime += DeltaTime;
	TimeSinceLastAction += DeltaTime;

	// Check for emotion state changes and broadcast if changed
	FEmotionEstimate Current = EstimateEmotion();
	if (Current.DominantState != PreviousDominantState)
	{
		OnEmotionEstimateUpdated.Broadcast(Current);
		PreviousDominantState = Current.DominantState;
	}
}

FEmotionEstimate UEmotionEstimationComponent::EstimateEmotion() const
{
	FEmotionEstimate Estimate;

	Estimate.FrustrationScore = FMath::Clamp(ComputeFrustration(), 0.0f, 1.0f);
	Estimate.FlowScore = FMath::Clamp(ComputeFlow(), 0.0f, 1.0f);
	Estimate.BoredomScore = FMath::Clamp(ComputeBoredom(), 0.0f, 1.0f);

	// Determine dominant state
	const float MaxScore = FMath::Max3(
		Estimate.FrustrationScore,
		Estimate.FlowScore,
		Estimate.BoredomScore
	);

	if (MaxScore < DominanceThreshold)
	{
		Estimate.DominantState = EPlayerEmotionalState::Neutral;
	}
	else if (MaxScore == Estimate.FrustrationScore)
	{
		Estimate.DominantState = EPlayerEmotionalState::Frustrated;
	}
	else if (MaxScore == Estimate.FlowScore)
	{
		Estimate.DominantState = EPlayerEmotionalState::Flow;
	}
	else
	{
		Estimate.DominantState = EPlayerEmotionalState::Bored;
	}

	return Estimate;
}

void UEmotionEstimationComponent::RecordEncounterOutcome(
	bool bBossWon, float DurationSeconds, float HeroHPAtEnd, float BossHPAtEnd)
{
	FEncounterOutcome Outcome;
	Outcome.bBossWon = bBossWon;
	Outcome.DurationSeconds = DurationSeconds;
	Outcome.HeroHPAtEnd = HeroHPAtEnd;
	Outcome.BossHPAtEnd = BossHPAtEnd;

	RecentEncounters.Add(Outcome);

	// Keep only recent encounters
	while (RecentEncounters.Num() > MaxRecentEncounters)
	{
		RecentEncounters.RemoveAt(0);
	}
}

void UEmotionEstimationComponent::RecordPlayerAction(int32 ActionIndex)
{
	ActionHistory.Add(ActionIndex);
	ActionCountThisEncounter++;
	TimeSinceLastAction = 0.0f;
}

void UEmotionEstimationComponent::ResetEncounterTracking()
{
	ActionHistory.Empty();
	EncounterElapsedTime = 0.0f;
	TimeSinceLastAction = 0.0f;
	ActionCountThisEncounter = 0;
}

// --- Scoring Functions ---

float UEmotionEstimationComponent::ComputeFrustration() const
{
	float Score = 0.0f;

	// Factor 1: Consecutive losses (strongest signal, 0.4 weight)
	const int32 Losses = GetConsecutiveLosses();
	if (Losses >= FrustrationLossStreak)
	{
		Score += FMath::Min(0.4f, (Losses - FrustrationLossStreak + 1) * 0.13f);
	}

	// Factor 2: Decreasing fight duration (0.2 weight)
	// Getting killed faster each time = frustration
	if (IsFightDurationDecreasing() && RecentEncounters.Num() >= 3)
	{
		Score += 0.2f;
	}

	// Factor 3: Action spam — high action rate relative to elapsed time (0.2 weight)
	if (EncounterElapsedTime > 2.0f)
	{
		const float ActionsPerSecond = ActionCountThisEncounter / EncounterElapsedTime;
		const float AverageRate = 2.0f; // ~2 actions/sec is normal for combat
		if (ActionsPerSecond > AverageRate * SpamRateMultiplier)
		{
			const float SpamExcess = (ActionsPerSecond - AverageRate * SpamRateMultiplier) / AverageRate;
			Score += FMath::Min(0.2f, SpamExcess * 0.1f);
		}
	}

	// Factor 4: Low action variety — doing the same thing repeatedly (0.2 weight)
	const float Entropy = GetActionEntropy();
	if (Entropy < 0.5f && ActionHistory.Num() > 10)
	{
		Score += (0.5f - Entropy) * 0.4f; // Max 0.2 when entropy = 0
	}

	return Score;
}

float UEmotionEstimationComponent::ComputeFlow() const
{
	if (RecentEncounters.Num() < 2)
	{
		return 0.0f;
	}

	float Score = 0.0f;

	// Factor 1: Mixed win/loss ratio (0.35 weight)
	// Flow = balanced challenge, ~40-60% win rate for the player
	const float WinRate = GetRecentWinRate();
	const float BossWinRate = 1.0f - WinRate;
	// Ideal: boss wins 40-60% → player wins 40-60%
	if (BossWinRate >= 0.35f && BossWinRate <= 0.65f)
	{
		const float Balance = 1.0f - FMath::Abs(BossWinRate - 0.5f) * 4.0f;
		Score += Balance * 0.35f;
	}

	// Factor 2: Close HP differentials at fight end (0.25 weight)
	const float AvgHPDiff = GetAverageHPDifferential();
	if (AvgHPDiff < 0.3f)
	{
		Score += (0.3f - AvgHPDiff) / 0.3f * 0.25f;
	}

	// Factor 3: High action variety / entropy (0.2 weight)
	const float Entropy = GetActionEntropy();
	if (Entropy > 1.0f && ActionHistory.Num() > 10)
	{
		Score += FMath::Min(0.2f, (Entropy - 1.0f) * 0.2f);
	}

	// Factor 4: Stable or increasing fight duration (0.2 weight)
	if (!IsFightDurationDecreasing() && RecentEncounters.Num() >= 3)
	{
		Score += 0.2f;
	}

	return Score;
}

float UEmotionEstimationComponent::ComputeBoredom() const
{
	float Score = 0.0f;

	// Factor 1: Low action rate (0.3 weight)
	if (EncounterElapsedTime > 5.0f)
	{
		const float ActionsPerSecond = ActionCountThisEncounter / EncounterElapsedTime;
		if (ActionsPerSecond < 0.5f)
		{
			Score += FMath::Min(0.3f, (0.5f - ActionsPerSecond) * 0.6f);
		}
	}

	// Factor 2: High idle time (0.25 weight)
	if (TimeSinceLastAction > BoredomIdleThreshold)
	{
		const float IdleExcess = (TimeSinceLastAction - BoredomIdleThreshold) / BoredomIdleThreshold;
		Score += FMath::Min(0.25f, IdleExcess * 0.125f);
	}

	// Factor 3: Retreat-heavy play — disengagement (0.25 weight)
	if (ActionHistory.Num() > 5)
	{
		int32 RetreatCount = 0;
		for (int32 Action : ActionHistory)
		{
			if (Action == 4) // Retreat
			{
				RetreatCount++;
			}
		}
		const float RetreatFraction = static_cast<float>(RetreatCount) / ActionHistory.Num();
		if (RetreatFraction > 0.4f)
		{
			Score += (RetreatFraction - 0.4f) * 0.5f; // Max 0.25 at 90% retreat
		}
	}

	// Factor 4: Dominant wins (too easy = boring) (0.2 weight)
	if (RecentEncounters.Num() >= 3)
	{
		const float WinRate = GetRecentWinRate();
		if (WinRate > 0.8f) // Player winning easily
		{
			Score += (WinRate - 0.8f) * 1.0f; // Max 0.2 at 100% win rate
		}
	}

	return Score;
}

// --- Helper Functions ---

int32 UEmotionEstimationComponent::GetConsecutiveLosses() const
{
	int32 Streak = 0;
	for (int32 i = RecentEncounters.Num() - 1; i >= 0; i--)
	{
		if (RecentEncounters[i].bBossWon)
		{
			Streak++; // Boss won = player lost
		}
		else
		{
			break; // Streak broken
		}
	}
	return Streak;
}

float UEmotionEstimationComponent::GetAverageFightDuration() const
{
	if (RecentEncounters.Num() == 0)
	{
		return 30.0f; // Default
	}

	float Total = 0.0f;
	for (const FEncounterOutcome& Enc : RecentEncounters)
	{
		Total += Enc.DurationSeconds;
	}
	return Total / RecentEncounters.Num();
}

float UEmotionEstimationComponent::GetActionEntropy() const
{
	if (ActionHistory.Num() < 5)
	{
		return 1.5f; // Default: moderate entropy
	}

	// Count action frequencies (6 possible actions: 0-5)
	int32 Counts[6] = {0};
	for (int32 Action : ActionHistory)
	{
		if (Action >= 0 && Action <= 5)
		{
			Counts[Action]++;
		}
	}

	// Shannon entropy
	const float Total = static_cast<float>(ActionHistory.Num());
	float Entropy = 0.0f;
	for (int32 i = 0; i < 6; i++)
	{
		if (Counts[i] > 0)
		{
			const float P = Counts[i] / Total;
			Entropy -= P * FMath::Loge(P);
		}
	}

	return Entropy;
}

float UEmotionEstimationComponent::GetRecentWinRate() const
{
	if (RecentEncounters.Num() == 0)
	{
		return 0.5f;
	}

	int32 BossWins = 0;
	for (const FEncounterOutcome& Enc : RecentEncounters)
	{
		if (Enc.bBossWon)
		{
			BossWins++;
		}
	}
	return static_cast<float>(BossWins) / RecentEncounters.Num();
}

float UEmotionEstimationComponent::GetAverageHPDifferential() const
{
	if (RecentEncounters.Num() == 0)
	{
		return 0.5f;
	}

	float TotalDiff = 0.0f;
	for (const FEncounterOutcome& Enc : RecentEncounters)
	{
		TotalDiff += FMath::Abs(Enc.HeroHPAtEnd - Enc.BossHPAtEnd);
	}
	return TotalDiff / RecentEncounters.Num();
}

bool UEmotionEstimationComponent::IsFightDurationDecreasing() const
{
	if (RecentEncounters.Num() < 3)
	{
		return false;
	}

	// Compare average of last 3 encounters with previous 3
	const int32 N = RecentEncounters.Num();
	const int32 HalfPoint = FMath::Max(0, N - 3);

	float RecentAvg = 0.0f;
	int32 RecentCount = 0;
	for (int32 i = HalfPoint; i < N; i++)
	{
		RecentAvg += RecentEncounters[i].DurationSeconds;
		RecentCount++;
	}
	RecentAvg /= FMath::Max(1, RecentCount);

	float OlderAvg = 0.0f;
	int32 OlderCount = 0;
	const int32 OlderEnd = FMath::Min(HalfPoint, N);
	const int32 OlderStart = FMath::Max(0, OlderEnd - 3);
	for (int32 i = OlderStart; i < OlderEnd; i++)
	{
		OlderAvg += RecentEncounters[i].DurationSeconds;
		OlderCount++;
	}

	if (OlderCount == 0)
	{
		return false;
	}

	OlderAvg /= OlderCount;

	// Fight duration decreasing by >20%
	return RecentAvg < OlderAvg * 0.8f;
}
