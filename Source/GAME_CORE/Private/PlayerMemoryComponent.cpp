#include "PlayerMemoryComponent.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonWriter.h"
#include "Serialization/JsonSerializer.h"
#include "HAL/PlatformFileManager.h"

UPlayerMemoryComponent::UPlayerMemoryComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
}

FString UPlayerMemoryComponent::GetSaveFilePath(const FString& PlayerId) const
{
	return FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("BossMemory"), PlayerId + TEXT(".json"));
}

void UPlayerMemoryComponent::InitializeMemoryData(const FString& PlayerId)
{
	MemoryData = FPlayerMemoryData();
	MemoryData.PlayerId = PlayerId;
	MemoryData.EncountersSinceActive.SetNumZeroed(FPlayerProfile::GetProfileSize());
}

void UPlayerMemoryComponent::LoadMemory(const FString& PlayerId)
{
	InitializeMemoryData(PlayerId);

	const FString FilePath = GetSaveFilePath(PlayerId);

	FString JsonString;
	if (!FFileHelper::LoadFileToString(JsonString, *FilePath))
	{
		UE_LOG(LogTemp, Log, TEXT("PlayerMemory: No existing memory for player '%s', starting fresh"), *PlayerId);
		return;
	}

	TSharedPtr<FJsonObject> RootObj;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonString);
	if (!FJsonSerializer::Deserialize(Reader, RootObj) || !RootObj.IsValid())
	{
		UE_LOG(LogTemp, Warning, TEXT("PlayerMemory: Failed to parse memory file for '%s'"), *PlayerId);
		return;
	}

	MemoryData.TotalEncounters = RootObj->GetIntegerField(TEXT("total_encounters"));
	MemoryData.BossWins = RootObj->GetIntegerField(TEXT("boss_wins"));

	// Load decayed profile
	const TSharedPtr<FJsonObject>* ProfileObj = nullptr;
	if (RootObj->TryGetObjectField(TEXT("decayed_profile"), ProfileObj))
	{
		MemoryData.DecayedProfile.FromJsonObject(*ProfileObj);
	}

	// Load encounters-since-active array
	const TArray<TSharedPtr<FJsonValue>>* SinceActiveArr = nullptr;
	if (RootObj->TryGetArrayField(TEXT("encounters_since_active"), SinceActiveArr))
	{
		for (int32 i = 0; i < FMath::Min(SinceActiveArr->Num(), FPlayerProfile::GetProfileSize()); i++)
		{
			MemoryData.EncountersSinceActive[i] = (*SinceActiveArr)[i]->AsNumber();
		}
	}

	// Load recent encounters
	const TArray<TSharedPtr<FJsonValue>>* EncountersArr = nullptr;
	if (RootObj->TryGetArrayField(TEXT("recent_encounters"), EncountersArr))
	{
		for (const auto& EncVal : *EncountersArr)
		{
			const TSharedPtr<FJsonObject>& EncObj = EncVal->AsObject();
			if (!EncObj.IsValid()) continue;

			FPlayerEncounterRecord Record;
			Record.EncounterIndex = EncObj->GetIntegerField(TEXT("index"));
			Record.bBossWon = EncObj->GetBoolField(TEXT("boss_won"));
			Record.FightDurationSeconds = EncObj->GetNumberField(TEXT("duration"));

			const TSharedPtr<FJsonObject>* RecProfileObj = nullptr;
			if (EncObj->TryGetObjectField(TEXT("profile"), RecProfileObj))
			{
				Record.Profile.FromJsonObject(*RecProfileObj);
			}

			MemoryData.RecentEncounters.Add(Record);
		}
	}

	UE_LOG(LogTemp, Log, TEXT("PlayerMemory: Loaded memory for '%s' (%d encounters, %.0f%% boss win rate)"),
		*PlayerId, MemoryData.TotalEncounters, GetBossWinRate() * 100.0f);
}

void UPlayerMemoryComponent::SaveMemory()
{
	if (MemoryData.PlayerId.IsEmpty())
	{
		UE_LOG(LogTemp, Warning, TEXT("PlayerMemory: Cannot save, no player ID set"));
		return;
	}

	TSharedPtr<FJsonObject> RootObj = MakeShared<FJsonObject>();
	RootObj->SetStringField(TEXT("player_id"), MemoryData.PlayerId);
	RootObj->SetNumberField(TEXT("total_encounters"), MemoryData.TotalEncounters);
	RootObj->SetNumberField(TEXT("boss_wins"), MemoryData.BossWins);

	// Decayed profile as object
	TSharedPtr<FJsonObject> ProfileObj = MakeShared<FJsonObject>();
	ProfileObj->SetNumberField(TEXT("aggression"), MemoryData.DecayedProfile.AggressionScore);
	ProfileObj->SetNumberField(TEXT("dodge"), MemoryData.DecayedProfile.DodgeTendency);
	ProfileObj->SetNumberField(TEXT("block"), MemoryData.DecayedProfile.BlockTendency);
	ProfileObj->SetNumberField(TEXT("opener"), MemoryData.DecayedProfile.OpenerAggression);
	ProfileObj->SetNumberField(TEXT("pressure"), MemoryData.DecayedProfile.PressureResponse);
	ProfileObj->SetNumberField(TEXT("kiting"), MemoryData.DecayedProfile.KitingScore);
	ProfileObj->SetNumberField(TEXT("combo_completion"), MemoryData.DecayedProfile.ComboCompletionRate);
	ProfileObj->SetNumberField(TEXT("positional_variance"), MemoryData.DecayedProfile.PositionalVariance);
	RootObj->SetObjectField(TEXT("decayed_profile"), ProfileObj);

	// Encounters since active
	TArray<TSharedPtr<FJsonValue>> SinceActiveArr;
	for (int32 Val : MemoryData.EncountersSinceActive)
	{
		SinceActiveArr.Add(MakeShared<FJsonValueNumber>(Val));
	}
	RootObj->SetArrayField(TEXT("encounters_since_active"), SinceActiveArr);

	// Recent encounters
	TArray<TSharedPtr<FJsonValue>> EncountersArr;
	for (const FPlayerEncounterRecord& Record : MemoryData.RecentEncounters)
	{
		TSharedPtr<FJsonObject> EncObj = MakeShared<FJsonObject>();
		EncObj->SetNumberField(TEXT("index"), Record.EncounterIndex);
		EncObj->SetBoolField(TEXT("boss_won"), Record.bBossWon);
		EncObj->SetNumberField(TEXT("duration"), Record.FightDurationSeconds);

		TSharedPtr<FJsonObject> RecProfileObj = MakeShared<FJsonObject>();
		RecProfileObj->SetNumberField(TEXT("aggression"), Record.Profile.AggressionScore);
		RecProfileObj->SetNumberField(TEXT("dodge"), Record.Profile.DodgeTendency);
		RecProfileObj->SetNumberField(TEXT("block"), Record.Profile.BlockTendency);
		RecProfileObj->SetNumberField(TEXT("opener"), Record.Profile.OpenerAggression);
		RecProfileObj->SetNumberField(TEXT("pressure"), Record.Profile.PressureResponse);
		RecProfileObj->SetNumberField(TEXT("kiting"), Record.Profile.KitingScore);
		RecProfileObj->SetNumberField(TEXT("combo_completion"), Record.Profile.ComboCompletionRate);
		RecProfileObj->SetNumberField(TEXT("positional_variance"), Record.Profile.PositionalVariance);
		EncObj->SetObjectField(TEXT("profile"), RecProfileObj);

		EncountersArr.Add(MakeShared<FJsonValueObject>(EncObj));
	}
	RootObj->SetArrayField(TEXT("recent_encounters"), EncountersArr);

	// Serialize and write
	FString OutputString;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&OutputString);
	FJsonSerializer::Serialize(RootObj.ToSharedRef(), Writer);

	const FString FilePath = GetSaveFilePath(MemoryData.PlayerId);
	const FString Directory = FPaths::GetPath(FilePath);

	IPlatformFile& PlatformFile = FPlatformFileManager::Get().GetPlatformFile();
	if (!PlatformFile.DirectoryExists(*Directory))
	{
		PlatformFile.CreateDirectoryTree(*Directory);
	}

	if (FFileHelper::SaveStringToFile(OutputString, *FilePath))
	{
		UE_LOG(LogTemp, Log, TEXT("PlayerMemory: Saved memory for '%s' to %s"), *MemoryData.PlayerId, *FilePath);
	}
	else
	{
		UE_LOG(LogTemp, Error, TEXT("PlayerMemory: Failed to save memory for '%s'"), *MemoryData.PlayerId);
	}
}

void UPlayerMemoryComponent::RecordEncounterEnd(const FPlayerProfile& Profile, bool bBossWon, float DurationSeconds)
{
	MemoryData.TotalEncounters++;
	if (bBossWon)
	{
		MemoryData.BossWins++;
	}

	// Create encounter record
	FPlayerEncounterRecord Record;
	Record.Profile = Profile;
	Record.EncounterIndex = MemoryData.TotalEncounters;
	Record.bBossWon = bBossWon;
	Record.FightDurationSeconds = DurationSeconds;

	// Add to recent encounters (ring buffer behavior)
	MemoryData.RecentEncounters.Add(Record);
	while (MemoryData.RecentEncounters.Num() > MaxRecentEncounters)
	{
		MemoryData.RecentEncounters.RemoveAt(0);
	}

	// Apply decay to the aggregate profile
	ApplyDecay(Profile);

	// Update decayed profile with current encounter data (EMA blend)
	const float BlendAlpha = 0.3f; // blend factor for new encounter data
	for (int32 i = 0; i < FPlayerProfile::GetProfileSize(); i++)
	{
		const float Current = MemoryData.DecayedProfile.GetDimension(i);
		const float New = Profile.GetDimension(i);
		MemoryData.DecayedProfile.SetDimension(i, (1.0f - BlendAlpha) * Current + BlendAlpha * New);
	}

	SaveMemory();
}

void UPlayerMemoryComponent::ApplyDecay(const FPlayerProfile& CurrentProfile)
{
	for (int32 i = 0; i < FPlayerProfile::GetProfileSize(); i++)
	{
		const float DimValue = CurrentProfile.GetDimension(i);
		const float DistFromNeutral = FMath::Abs(DimValue - 0.5f);

		// Is this dimension "active" in the current encounter?
		if (DistFromNeutral > ActiveThreshold)
		{
			MemoryData.EncountersSinceActive[i] = 0;
		}
		else
		{
			MemoryData.EncountersSinceActive[i]++;
		}

		// Apply decay if beyond threshold
		const int32 SinceActive = MemoryData.EncountersSinceActive[i];
		if (SinceActive > DecayEncounterThreshold)
		{
			const int32 Excess = SinceActive - DecayEncounterThreshold;
			const float DecayFactor = FMath::Min(1.0f, Excess * DecayRate);
			const float Current = MemoryData.DecayedProfile.GetDimension(i);
			// Lerp toward 0.5 (neutral)
			MemoryData.DecayedProfile.SetDimension(i, FMath::Lerp(Current, 0.5f, DecayFactor));
		}
	}
}

FString UPlayerMemoryComponent::GetDecayedProfileJson() const
{
	const FPlayerProfile& P = MemoryData.DecayedProfile;

	return FString::Printf(
		TEXT("{\"profile\":%s,\"total_encounters\":%d,\"boss_wins\":%d,\"win_rate\":%.3f}"),
		*P.ToJsonString(),
		MemoryData.TotalEncounters,
		MemoryData.BossWins,
		GetBossWinRate()
	);
}

float UPlayerMemoryComponent::GetBossWinRate() const
{
	if (MemoryData.TotalEncounters == 0) return 0.0f;
	return static_cast<float>(MemoryData.BossWins) / MemoryData.TotalEncounters;
}
