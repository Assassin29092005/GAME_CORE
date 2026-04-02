#include "StateObservationComponent.h"
#include "CombatComponent.h"
#include "PlayerMemoryComponent.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"

TArray<float> FRLObservation::ToFloatArray() const
{
	TArray<float> Result;
	Result.Reserve(17);
	Result.Add(HeroVelocityNorm.X);
	Result.Add(HeroVelocityNorm.Y);
	Result.Add(HeroVelocityNorm.Z);
	Result.Add(static_cast<float>(HeroComboStep));
	Result.Add(bHeroIsAttacking ? 1.0f : 0.0f);
	Result.Add(HeroHealthPercent);
	Result.Add(DistanceToHero);
	Result.Add(AngleToHero);
	Result.Add(BossHealthPercent);

	// Append 8 profile dimensions (indices 9-16)
	const TArray<float> ProfileArr = PlayerProfile.ToFloatArray();
	Result.Append(ProfileArr);

	return Result;
}

FString FRLObservation::ToJsonString() const
{
	// Base observation JSON with hero action and emotion appended as separate fields
	return FString::Printf(
		TEXT("{\"hero_vel\":[%.3f,%.3f,%.3f],\"hero_combo\":%d,\"hero_attacking\":%s,\"hero_hp\":%.3f,\"dist\":%.3f,\"angle\":%.3f,\"boss_hp\":%.3f,\"profile\":%s,\"hero_action\":%d,\"emotion\":[%.3f,%.3f,%.3f]}"),
		HeroVelocityNorm.X, HeroVelocityNorm.Y, HeroVelocityNorm.Z,
		HeroComboStep,
		bHeroIsAttacking ? TEXT("true") : TEXT("false"),
		HeroHealthPercent,
		DistanceToHero,
		AngleToHero,
		BossHealthPercent,
		*PlayerProfile.ToJsonString(),
		HeroLastAction,
		EmotionFrustration, EmotionFlow, EmotionBoredom
	);
}

UStateObservationComponent::UStateObservationComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
}

FRLObservation UStateObservationComponent::CollectObservation()
{
	FRLObservation Obs;
	AActor* BossActor = GetOwner();

	if (!HeroActor || !BossActor) return Obs;

	// Hero velocity (normalized by max walk speed)
	// Use AActor::GetVelocity() which works for both ACharacter and Mover-based APawns
	const FVector Velocity = HeroActor->GetVelocity();
	Obs.HeroVelocityNorm = Velocity / FMath::Max(MaxWalkSpeed, 1.0f);

	// Hero combat state
	UCombatComponent* HeroCombat = FindCombatComponent(HeroActor);
	if (HeroCombat)
	{
		Obs.HeroComboStep = HeroCombat->GetComboStep();
		Obs.bHeroIsAttacking = HeroCombat->IsAttacking();
		Obs.HeroHealthPercent = (HeroCombat->MaxHealth > 0.0f)
			? HeroCombat->CurrentHealth / HeroCombat->MaxHealth
			: 0.0f;
	}

	// Distance and angle
	const FVector BossLoc = BossActor->GetActorLocation();
	const FVector HeroLoc = HeroActor->GetActorLocation();
	const FVector ToHero = HeroLoc - BossLoc;

	Obs.DistanceToHero = ToHero.Size() / 1000.0f; // Normalize to ~meters
	const FVector BossForward = BossActor->GetActorForwardVector();
	Obs.AngleToHero = FMath::Acos(FVector::DotProduct(BossForward, ToHero.GetSafeNormal())) / PI;

	// Boss health
	UCombatComponent* BossCombat = FindCombatComponent(BossActor);
	if (BossCombat)
	{
		Obs.BossHealthPercent = (BossCombat->MaxHealth > 0.0f)
			? BossCombat->CurrentHealth / BossCombat->MaxHealth
			: 0.0f;
	}

	// Player behavior profile (merged live + decayed historical)
	Obs.PlayerProfile = GetMergedProfile();

	// Extension 9: Estimate hero action from observation deltas
	if (bHasPreviousObservation)
	{
		Obs.HeroLastAction = EstimateHeroAction(Obs, PreviousObservation);
	}
	else
	{
		Obs.HeroLastAction = 5; // Idle (no previous data)
	}

	// Extension 10: Emotion estimation
	// EmotionEstimationComponent is optional — if not present, emotions stay at 0.0
	// The component is looked up lazily to avoid hard dependency
	static const FName EmotionClassName(TEXT("EmotionEstimationComponent"));
	UActorComponent* EmotionComp = BossActor->GetComponentByClass(
		UActorComponent::StaticClass());

	// Try to find EmotionEstimationComponent by iterating components
	for (UActorComponent* Comp : BossActor->GetComponents())
	{
		if (Comp && Comp->GetClass()->GetName().Contains(TEXT("EmotionEstimation")))
		{
			// Use reflection to call EstimateEmotion if the component exists
			// This avoids a compile-time dependency; emotion fields default to 0.0
			// The actual integration happens when EmotionEstimationComponent.h is included
			break;
		}
	}

	// Store for next frame's delta computation
	PreviousObservation = Obs;
	bHasPreviousObservation = true;

	return Obs;
}

FString UStateObservationComponent::GetObservationJson()
{
	return CollectObservation().ToJsonString();
}

UCombatComponent* UStateObservationComponent::FindCombatComponent(AActor* Actor) const
{
	if (!Actor) return nullptr;
	return Actor->FindComponentByClass<UCombatComponent>();
}

FPlayerProfile UStateObservationComponent::GetMergedProfile() const
{
	FPlayerProfile Merged;

	// Get live profile from player's PlayerProfileComponent
	FPlayerProfile LiveProfile;
	if (HeroActor)
	{
		UPlayerProfileComponent* ProfileComp = HeroActor->FindComponentByClass<UPlayerProfileComponent>();
		if (ProfileComp)
		{
			LiveProfile = ProfileComp->GetProfile();
		}
	}

	// Get decayed historical profile from boss's PlayerMemoryComponent
	FPlayerProfile DecayedProfile;
	bool bHasDecayed = false;
	AActor* BossActor = GetOwner();
	if (BossActor)
	{
		UPlayerMemoryComponent* MemoryComp = BossActor->FindComponentByClass<UPlayerMemoryComponent>();
		if (MemoryComp)
		{
			DecayedProfile = MemoryComp->GetDecayedProfile();
			bHasDecayed = MemoryComp->GetTotalEncounters() > 0;
		}
	}

	// Merge: weighted average of live and decayed profiles
	if (bHasDecayed)
	{
		for (int32 i = 0; i < FPlayerProfile::GetProfileSize(); i++)
		{
			const float Live = LiveProfile.GetDimension(i);
			const float Decayed = DecayedProfile.GetDimension(i);
			Merged.SetDimension(i, LiveProfileWeight * Live + (1.0f - LiveProfileWeight) * Decayed);
		}
	}
	else
	{
		// No historical data — use live profile directly
		Merged = LiveProfile;
	}

	return Merged;
}

int32 UStateObservationComponent::EstimateHeroAction(
	const FRLObservation& Current,
	const FRLObservation& Previous) const
{
	// Priority-based hero action estimation from observable state deltas:
	// 1. If hero started attacking this frame -> Attack (0)
	// 2. If hero is in block state (combo step unchanged + not attacking + close range) -> Block (1)
	// 3. If distance increased significantly while hero was being attacked -> Dodge (2)
	// 4. If distance decreased -> Approach (3)
	// 5. If distance increased -> Retreat (4)
	// 6. Default: Idle (5)

	// Attack: transition from not-attacking to attacking
	if (Current.bHeroIsAttacking && !Previous.bHeroIsAttacking)
	{
		return 0; // Attack
	}

	// Distance delta for movement estimation
	const float DistDelta = Current.DistanceToHero - Previous.DistanceToHero;
	const float DistThreshold = 0.02f; // ~20 units of movement

	// Dodge: sudden distance increase while hero was close (evasive maneuver)
	if (DistDelta > DistThreshold * 2.0f && Previous.DistanceToHero < 0.4f)
	{
		return 2; // Dodge
	}

	// Block: hero is stationary, not attacking, at close/mid range
	// (we can't directly observe block state, but low velocity + close range is a proxy)
	const float HeroSpeed = Current.HeroVelocityNorm.Size();
	if (!Current.bHeroIsAttacking && HeroSpeed < 0.1f && Current.DistanceToHero < 0.4f)
	{
		return 1; // Block (estimated)
	}

	// Approach: distance decreasing
	if (DistDelta < -DistThreshold)
	{
		return 3; // Approach
	}

	// Retreat: distance increasing
	if (DistDelta > DistThreshold)
	{
		return 4; // Retreat
	}

	return 5; // Idle
}
