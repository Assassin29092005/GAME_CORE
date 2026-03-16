#include "BossExplainabilityComponent.h"

UBossExplainabilityComponent::UBossExplainabilityComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
	InitializeTemplates();
}

void UBossExplainabilityComponent::InitializeTemplates()
{
	// Dimension 0: AggressionScore — high means player is very aggressive
	InsightTemplates.Add({
		0, true, FName(TEXT("AntiMelee")),
		FText::FromString(TEXT("Your sword arm grows predictable.")),
		FText::FromString(TEXT("The boss has learned you favor aggressive melee combat and is preparing counters.")),
	});

	// Dimension 1: DodgeTendency — high means player dodges a lot
	InsightTemplates.Add({
		1, true, FName(TEXT("AntiDodge")),
		FText::FromString(TEXT("You cannot dodge forever.")),
		FText::FromString(TEXT("The boss recognizes your evasive style and will use wider attacks.")),
	});

	// Dimension 2: BlockTendency — high means player blocks a lot
	InsightTemplates.Add({
		2, true, FName(TEXT("AntiBlock")),
		FText::FromString(TEXT("Your guard will break.")),
		FText::FromString(TEXT("The boss has noticed your reliance on blocking and will use guard-breaking moves.")),
	});

	// Dimension 3: OpenerAggression — high means player opens aggressively
	InsightTemplates.Add({
		3, true, FName(TEXT("AntiOpener")),
		FText::FromString(TEXT("I know your opening gambit.")),
		FText::FromString(TEXT("The boss has adapted to your aggressive opening strategy.")),
	});

	// Dimension 3: OpenerAggression — low means player is passive at start
	InsightTemplates.Add({
		3, false, FName(TEXT("ExploitPassive")),
		FText::FromString(TEXT("Your hesitation is your weakness.")),
		FText::FromString(TEXT("The boss senses your cautious openings and will strike first.")),
	});

	// Dimension 4: PressureResponse — low means player crumbles under pressure
	InsightTemplates.Add({
		4, false, FName(TEXT("Pressure")),
		FText::FromString(TEXT("I see fear in your eyes.")),
		FText::FromString(TEXT("The boss has learned you falter when your health is low.")),
	});

	// Dimension 4: PressureResponse — high means player fights harder under pressure
	InsightTemplates.Add({
		4, true, FName(TEXT("RespectPressure")),
		FText::FromString(TEXT("You fight harder when cornered... interesting.")),
		FText::FromString(TEXT("The boss is wary of your desperation attacks when wounded.")),
	});

	// Dimension 5: KitingScore — high means player kites / stays at range
	InsightTemplates.Add({
		5, true, FName(TEXT("AntiKite")),
		FText::FromString(TEXT("Running will not save you.")),
		FText::FromString(TEXT("The boss recognizes your hit-and-run tactics and will close distance aggressively.")),
	});

	// Dimension 6: ComboCompletionRate — high means player finishes combos
	InsightTemplates.Add({
		6, true, FName(TEXT("AntiCombo")),
		FText::FromString(TEXT("Your combos are becoming predictable.")),
		FText::FromString(TEXT("The boss has learned the timing of your full combo chains.")),
	});

	// Dimension 7: PositionalVariance — low means player stands still (face-tanks)
	InsightTemplates.Add({
		7, false, FName(TEXT("ExploitStatic")),
		FText::FromString(TEXT("Standing still makes you an easy target.")),
		FText::FromString(TEXT("The boss exploits your lack of movement.")),
	});

	// --- Extension 10: Emotion-aware taunts ---
	// These use dimension index -1 (not profile-based, emotion-based)
	// They are checked separately via the emotion system, but stored here
	// for consistent taunt delivery via the same delegate.

	// Frustration: empathetic taunts (respect the struggle)
	InsightTemplates.Add({
		-1, true, FName(TEXT("Empathy")),
		FText::FromString(TEXT("A worthy foe learns from defeat.")),
		FText::FromString(TEXT("The boss recognizes the player's struggle and shows respect.")),
	});

	// Boredom: provocative taunts (challenge them to engage)
	InsightTemplates.Add({
		-2, true, FName(TEXT("Provoke")),
		FText::FromString(TEXT("Is that all you have?")),
		FText::FromString(TEXT("The boss taunts the disengaged player to provoke a response.")),
	});

	// Flow: appreciative taunts (acknowledge good fight)
	InsightTemplates.Add({
		-3, true, FName(TEXT("Respect")),
		FText::FromString(TEXT("Now the real battle begins.")),
		FText::FromString(TEXT("The boss acknowledges a worthy opponent in an exciting fight.")),
	});
}

TArray<FBossInsight> UBossExplainabilityComponent::GenerateInsights(const FPlayerProfile& Profile) const
{
	TArray<FBossInsight> Insights;

	for (const FInsightTemplate& Template : InsightTemplates)
	{
		const float DimValue = Profile.GetDimension(Template.DimensionIndex);
		bool bTriggered = false;
		float Confidence = 0.0f;

		if (Template.bHighIsActive)
		{
			// Triggers when dimension is high (above StrongTraitThreshold)
			if (DimValue >= StrongTraitThreshold)
			{
				bTriggered = true;
				Confidence = (DimValue - StrongTraitThreshold) / (1.0f - StrongTraitThreshold);
			}
		}
		else
		{
			// Triggers when dimension is low (below WeakTraitThreshold)
			if (DimValue <= WeakTraitThreshold)
			{
				bTriggered = true;
				Confidence = (WeakTraitThreshold - DimValue) / WeakTraitThreshold;
			}
		}

		if (bTriggered)
		{
			FBossInsight Insight;

			// Check for designer-overridden taunt
			const FText* Override = TauntOverrides.Find(Template.AdaptationTag);
			Insight.TauntText = Override ? *Override : Template.DefaultTaunt;

			Insight.StrategyDescription = Template.Description;
			Insight.AdaptationTag = Template.AdaptationTag;
			Insight.Confidence = FMath::Clamp(Confidence, 0.0f, 1.0f);
			Insight.ProfileDimensionIndex = Template.DimensionIndex;

			Insights.Add(Insight);
		}
	}

	// Sort by confidence (strongest insight first)
	Insights.Sort([](const FBossInsight& A, const FBossInsight& B)
	{
		return A.Confidence > B.Confidence;
	});

	return Insights;
}

FText UBossExplainabilityComponent::GenerateTopTaunt(const FPlayerProfile& Profile) const
{
	TArray<FBossInsight> Insights = GenerateInsights(Profile);

	if (Insights.Num() > 0)
	{
		return Insights[0].TauntText;
	}

	return FText::FromString(TEXT("You present an interesting challenge."));
}

void UBossExplainabilityComponent::BroadcastInsights(const FPlayerProfile& Profile)
{
	TArray<FBossInsight> Insights = GenerateInsights(Profile);

	for (const FBossInsight& Insight : Insights)
	{
		OnBossInsightGenerated.Broadcast(Insight);
	}

	UE_LOG(LogTemp, Log, TEXT("Explainability: Broadcast %d insights"), Insights.Num());
}
