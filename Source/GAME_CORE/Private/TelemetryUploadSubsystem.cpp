#include "TelemetryUploadSubsystem.h"

#include "AutoHeroComponent.h"
#include "BossActionComponent.h"
#include "CombatComponent.h"
#include "EmotionEstimationComponent.h"
#include "FirebaseAuthSubsystem.h"
#include "GameFeelSubsystem.h"
#include "PlayerProfileComponent.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "HAL/FileManager.h"
#include "HttpModule.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Guid.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

DEFINE_LOG_CATEGORY_STATIC(LogTelemetry, Log, All);

namespace
{
	constexpr float BindTickInterval = 1.0f;
	constexpr float FlushTickInterval = 30.0f;
	/** Ignore a second round-end delegate within this window (both fighters'
	 *  delegates can observe the same death cascade). */
	constexpr double RoundEndDebounceSeconds = 2.0;

	/** Guest/offline queue cap: keep only the newest N pending round files so an
	 *  unconfigured install can't accumulate telemetry forever. */
	constexpr int32 MaxPendingFiles = 500;

	/** Consecutive non-auth server failures on the SAME pending file before it
	 *  is parked as .stuck (8 x 30s flush cadence = ~4 minutes of refusals). */
	constexpr int32 MaxFlushFailureStreak = 8;

	// --- Firestore REST typed-value builders -------------------------------
	// REST documents don't take raw JSON — every field is a typed wrapper
	// ({"doubleValue": x}, {"stringValue": s}, ...). integerValue is a STRING
	// per the protobuf JSON mapping.

	TSharedPtr<FJsonObject> FsDouble(double Value)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetNumberField(TEXT("doubleValue"), Value);
		return Obj;
	}

	TSharedPtr<FJsonObject> FsString(const FString& Value)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetStringField(TEXT("stringValue"), Value);
		return Obj;
	}

	TSharedPtr<FJsonObject> FsInteger(int64 Value)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetStringField(TEXT("integerValue"), FString::Printf(TEXT("%lld"), Value));
		return Obj;
	}

	TSharedPtr<FJsonObject> FsTimestamp(const FString& Iso8601)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetStringField(TEXT("timestampValue"), Iso8601);
		return Obj;
	}

	TSharedPtr<FJsonObject> FsMap(const TSharedPtr<FJsonObject>& Fields)
	{
		TSharedPtr<FJsonObject> Inner = MakeShared<FJsonObject>();
		Inner->SetObjectField(TEXT("fields"), Fields);
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetObjectField(TEXT("mapValue"), Inner);
		return Obj;
	}

	TSharedPtr<FJsonObject> FsArray(const TArray<TSharedPtr<FJsonValue>>& Values)
	{
		TSharedPtr<FJsonObject> Inner = MakeShared<FJsonObject>();
		Inner->SetArrayField(TEXT("values"), Values);
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetObjectField(TEXT("arrayValue"), Inner);
		return Obj;
	}

	/** {"fieldPath": Path, "increment": Value} for the meta/global commit. */
	TSharedPtr<FJsonValue> FsIncrement(const FString& Path, const TSharedPtr<FJsonObject>& Value)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetStringField(TEXT("fieldPath"), Path);
		Obj->SetObjectField(TEXT("increment"), Value);
		return MakeShared<FJsonValueObject>(Obj);
	}

	FString JsonToString(const TSharedPtr<FJsonObject>& Obj)
	{
		FString Out;
		const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
		FJsonSerializer::Serialize(Obj.ToSharedRef(), Writer);
		return Out;
	}

	const TCHAR* DominantEmotionToString(EPlayerEmotionalState State)
	{
		switch (State)
		{
		case EPlayerEmotionalState::Frustrated: return TEXT("Frustrated");
		case EPlayerEmotionalState::Flow:       return TEXT("Flow");
		case EPlayerEmotionalState::Bored:      return TEXT("Bored");
		default:                                return TEXT("Neutral");
		}
	}

	/** README profile field names, index-aligned with FPlayerProfile dims 0-7. */
	const TCHAR* ProfileFieldNames[8] = {
		TEXT("aggression"), TEXT("dodgeTendency"), TEXT("blockTendency"),
		TEXT("openerAggression"), TEXT("pressureResponse"), TEXT("kitingScore"),
		TEXT("comboCompletionRate"), TEXT("positionalVariance")
	};

}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

void UTelemetryUploadSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);

	// Auth must exist first (flush guards read it every cycle).
	Collection.InitializeDependency<UFirebaseAuthSubsystem>();

	BindTickerHandle = FTSTicker::GetCoreTicker().AddTicker(
		FTickerDelegate::CreateUObject(this, &UTelemetryUploadSubsystem::TickBind), BindTickInterval);
	FlushTickerHandle = FTSTicker::GetCoreTicker().AddTicker(
		FTickerDelegate::CreateUObject(this, &UTelemetryUploadSubsystem::TickFlush), FlushTickInterval);

	UE_LOG(LogTelemetry, Log, TEXT("Telemetry subsystem up — pending dir: %s (%d queued)"),
		*GetPendingDir(), GetPendingFileCount());
}

void UTelemetryUploadSubsystem::Deinitialize()
{
	if (BindTickerHandle.IsValid())
	{
		FTSTicker::GetCoreTicker().RemoveTicker(BindTickerHandle);
	}
	if (FlushTickerHandle.IsValid())
	{
		FTSTicker::GetCoreTicker().RemoveTicker(FlushTickerHandle);
	}
	Super::Deinitialize();
}

FString UTelemetryUploadSubsystem::GetPendingDir()
{
	return FPaths::ProjectSavedDir() / TEXT("Telemetry") / TEXT("pending");
}

FString UTelemetryUploadSubsystem::GetFirstUploadMarkerPath(const FString& Uid)
{
	// Sits NEXT TO pending/, not inside it — the flush loop must never try to
	// upload the marker.
	return FPaths::ProjectSavedDir() / TEXT("Telemetry") / FString::Printf(TEXT("first_upload_%s.marker"), *Uid);
}

int32 UTelemetryUploadSubsystem::GetPendingFileCount() const
{
	TArray<FString> Files;
	IFileManager::Get().FindFiles(Files, *(GetPendingDir() / TEXT("*.json")), /*Files=*/true, /*Directories=*/false);
	return Files.Num();
}

// ---------------------------------------------------------------------------
// Lazy actor binding
// ---------------------------------------------------------------------------

bool UTelemetryUploadSubsystem::TickBind(float /*DeltaTime*/)
{
	const UGameInstance* GameInstance = GetGameInstance();
	UWorld* World = GameInstance ? GameInstance->GetWorld() : nullptr;
	if (!World || !World->IsGameWorld() || !World->HasBegunPlay())
	{
		return true;
	}

	// Level change: drop stale weak bindings and start over.
	if (BoundWorld.Get() != World)
	{
		ClearBindings();
		BoundWorld = World;
	}

	// Hero side (loss detection + the 8-dim profile).
	if (!HeroCombat.IsValid())
	{
		if (const APawn* HeroPawn = UGameplayStatics::GetPlayerPawn(World, 0))
		{
			if (UCombatComponent* Combat = HeroPawn->FindComponentByClass<UCombatComponent>())
			{
				HeroCombat = Combat;
				Combat->OnHealthDepleted.AddUniqueDynamic(this, &UTelemetryUploadSubsystem::HandleHeroHealthDepleted);
			}
			HeroProfile = HeroPawn->FindComponentByClass<UPlayerProfileComponent>();
		}
	}

	// Boss side (win detection, emotion, taunts). Same discovery rule as the
	// feel layer: first Enemy-tagged actor WITH a BossActionComponent — minions
	// carry the tag but never match.
	if (!BossAction.IsValid())
	{
		if (AActor* Boss = UGameFeelSubsystem::FindBossActor(World))
		{
			if (UBossActionComponent* Action = Boss->FindComponentByClass<UBossActionComponent>())
			{
				BossAction = Action;
				Action->OnBossDied.AddUniqueDynamic(this, &UTelemetryUploadSubsystem::HandleBossDied);
			}
			BossCombat = Boss->FindComponentByClass<UCombatComponent>();
			BossEmotion = Boss->FindComponentByClass<UEmotionEstimationComponent>();
			if (UBossExplainabilityComponent* Explain = Boss->FindComponentByClass<UBossExplainabilityComponent>())
			{
				BossExplain = Explain;
				Explain->OnBossInsightGenerated.AddUniqueDynamic(this, &UTelemetryUploadSubsystem::HandleBossInsight);
			}

			// First full bind = the first round's start.
			RoundStartWorldSeconds = World->GetTimeSeconds();
			UE_LOG(LogTelemetry, Log, TEXT("Round-end delegates bound (hero=%s, boss=ok, emotion=%s, explain=%s)"),
				HeroCombat.IsValid() ? TEXT("ok") : TEXT("missing"),
				BossEmotion.IsValid() ? TEXT("ok") : TEXT("missing"),
				BossExplain.IsValid() ? TEXT("ok") : TEXT("missing"));
		}
	}

	return true; // Keep ticking — worlds change, pawns get replaced.
}

void UTelemetryUploadSubsystem::ClearBindings()
{
	// Weak ptrs may already be dead with the old world — just forget them; the
	// dynamic delegates die with their owning components.
	HeroCombat.Reset();
	HeroProfile.Reset();
	BossAction.Reset();
	BossCombat.Reset();
	BossEmotion.Reset();
	BossExplain.Reset();
	RoundInsights.Empty();
}

// ---------------------------------------------------------------------------
// Round-end capture
// ---------------------------------------------------------------------------

void UTelemetryUploadSubsystem::HandleBossDied()
{
	FinishRound(/*bPlayerWon=*/true);
}

void UTelemetryUploadSubsystem::HandleHeroHealthDepleted()
{
	FinishRound(/*bPlayerWon=*/false);
}

void UTelemetryUploadSubsystem::HandleBossInsight(const FBossInsight& Insight)
{
	// Unique per AdaptationTag, latest broadcast wins (confidence evolves).
	RoundInsights.RemoveAll([&Insight](const FBossInsight& Existing)
	{
		return Existing.AdaptationTag == Insight.AdaptationTag;
	});
	RoundInsights.Add(Insight);
}

bool UTelemetryUploadSubsystem::IsTelemetrySuppressed() const
{
	// 1) Explicit launch arg — Tools/run_training.ps1 passes -NoTelemetry so
	//    overnight harness runs deterministically capture nothing.
	static const bool bNoTelemetryArg = FParse::Param(FCommandLine::Get(), TEXT("NoTelemetry"));
	if (bNoTelemetryArg)
	{
		return true;
	}

	// 2) The AutoHero sparring bot is driving the hero — bot rounds must never
	//    reach users/{uid}/fights or the meta/global community aggregates.
	if (const UWorld* World = BoundWorld.Get())
	{
		if (const APawn* HeroPawn = UGameplayStatics::GetPlayerPawn(World, 0))
		{
			if (const UAutoHeroComponent* AutoHero = HeroPawn->FindComponentByClass<UAutoHeroComponent>())
			{
				if (AutoHero->bEnabled)
				{
					return true;
				}
			}
		}
	}

	// 3) Training auto-reset mode on the hero (never set in shipped play).
	if (HeroCombat.IsValid() && HeroCombat->bAutoResetRoundOnDeath)
	{
		return true;
	}

	return false;
}

void UTelemetryUploadSubsystem::FinishRound(bool bPlayerWon)
{
	// Sparring-bot / training rounds are not player telemetry — capturing them
	// would inflate the fight log and skew the community difficulty scalar.
	if (IsTelemetrySuppressed())
	{
		return;
	}

	const double NowReal = FPlatformTime::Seconds();
	if (NowReal - LastRoundEndRealSeconds < RoundEndDebounceSeconds)
	{
		return; // Same death cascade seen twice.
	}
	LastRoundEndRealSeconds = NowReal;

	UWorld* World = BoundWorld.Get();
	if (!World)
	{
		return;
	}

	const double DurationSeconds = FMath::Max(0.0, World->GetTimeSeconds() - RoundStartWorldSeconds);
	RoundStartWorldSeconds = World->GetTimeSeconds(); // Next round (includes the reset pause — accepted).

	const FPlayerProfile Profile = HeroProfile.IsValid() ? HeroProfile->GetProfile() : FPlayerProfile();
	const FEmotionEstimate Emotion = BossEmotion.IsValid() ? BossEmotion->EstimateEmotion() : FEmotionEstimate();

	// Taunts: whatever the session broadcast, else generate from the profile now
	// so the fight doc is never empty-handed.
	TArray<FBossInsight> Insights = RoundInsights;
	if (Insights.Num() == 0 && BossExplain.IsValid())
	{
		Insights = BossExplain->GenerateInsights(Profile);
	}
	RoundInsights.Empty();

	// --- Build the plain (non-Firestore-typed) round JSON ---
	// This is the on-disk queue format; the flush pass converts it to Firestore
	// typed values. Field names deliberately mirror Website/README.md.
	const TSharedPtr<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetNumberField(TEXT("schemaVersion"), 1);
	Root->SetStringField(TEXT("startedAt"),
		(FDateTime::UtcNow() - FTimespan::FromSeconds(DurationSeconds)).ToIso8601());
	Root->SetNumberField(TEXT("durationSeconds"), DurationSeconds);
	Root->SetStringField(TEXT("outcome"), bPlayerWon ? TEXT("win") : TEXT("loss"));
	Root->SetStringField(TEXT("encounterType"), TEXT("boss"));
	Root->SetNumberField(TEXT("bossHpAtEnd"), BossCombat.IsValid() ? BossCombat->CurrentHealth : 0.0);
	Root->SetNumberField(TEXT("heroHpAtEnd"), HeroCombat.IsValid() ? HeroCombat->CurrentHealth : 0.0);
	Root->SetBoolField(TEXT("bossWon"), !bPlayerWon);

	const TSharedPtr<FJsonObject> EmotionObj = MakeShared<FJsonObject>();
	EmotionObj->SetNumberField(TEXT("frustration"), Emotion.FrustrationScore);
	EmotionObj->SetNumberField(TEXT("flow"), Emotion.FlowScore);
	EmotionObj->SetNumberField(TEXT("boredom"), Emotion.BoredomScore);
	EmotionObj->SetStringField(TEXT("dominant"), DominantEmotionToString(Emotion.DominantState));
	Root->SetObjectField(TEXT("emotion"), EmotionObj);

	// Contract shape (Website/README.md): `taunts` is a plain string[] of the
	// lines the boss "spoke". The richer FBossInsight fields are kept LOCALLY in
	// `tauntDetails` (never uploaded) so the offline record keeps the full
	// explainability data.
	TArray<TSharedPtr<FJsonValue>> TauntValues;
	TArray<TSharedPtr<FJsonValue>> TauntDetailValues;
	for (const FBossInsight& Insight : Insights)
	{
		TauntValues.Add(MakeShared<FJsonValueString>(Insight.TauntText.ToString()));

		const TSharedPtr<FJsonObject> DetailObj = MakeShared<FJsonObject>();
		DetailObj->SetStringField(TEXT("taunt"), Insight.TauntText.ToString());
		DetailObj->SetStringField(TEXT("description"), Insight.StrategyDescription.ToString());
		DetailObj->SetStringField(TEXT("tag"), Insight.AdaptationTag.ToString());
		DetailObj->SetNumberField(TEXT("confidence"), Insight.Confidence);
		DetailObj->SetNumberField(TEXT("profileDimension"), Insight.ProfileDimensionIndex);
		TauntDetailValues.Add(MakeShared<FJsonValueObject>(DetailObj));
	}
	Root->SetArrayField(TEXT("taunts"), TauntValues);
	Root->SetArrayField(TEXT("tauntDetails"), TauntDetailValues);

	const TSharedPtr<FJsonObject> ProfileObj = MakeShared<FJsonObject>();
	for (int32 Dim = 0; Dim < FPlayerProfile::GetProfileSize(); ++Dim)
	{
		ProfileObj->SetNumberField(ProfileFieldNames[Dim], Profile.GetDimension(Dim));
	}
	Root->SetObjectField(TEXT("profile"), ProfileObj);

	// --- Write to pending/ ALWAYS (offline-first; guest mode queues forever) ---
	const FString FileName = FString::Printf(TEXT("%s_%s.json"),
		*FDateTime::UtcNow().ToString(TEXT("%Y%m%d_%H%M%S")),
		*FGuid::NewGuid().ToString(EGuidFormats::Short).Left(8));
	const FString FilePath = GetPendingDir() / FileName;

	if (FFileHelper::SaveStringToFile(JsonToString(Root), *FilePath))
	{
		UE_LOG(LogTelemetry, Log, TEXT("Round queued: %s (outcome=%s, %.1fs, %d taunts, %d pending)"),
			*FileName, bPlayerWon ? TEXT("win") : TEXT("loss"), DurationSeconds,
			TauntValues.Num(), GetPendingFileCount());

		// Queue cap (guest/unconfigured mode accumulates forever otherwise):
		// timestamped names sort oldest-first — drop everything past the cap.
		TArray<FString> Pending;
		IFileManager::Get().FindFiles(Pending, *(GetPendingDir() / TEXT("*.json")), true, false);
		if (Pending.Num() > MaxPendingFiles)
		{
			Pending.Sort();
			const int32 NumToDrop = Pending.Num() - MaxPendingFiles;
			for (int32 i = 0; i < NumToDrop; ++i)
			{
				IFileManager::Get().Delete(*(GetPendingDir() / Pending[i]), /*RequireExists=*/false);
			}
			UE_LOG(LogTelemetry, Warning, TEXT("Pending queue over cap (%d) — dropped the %d oldest round file(s)."),
				MaxPendingFiles, NumToDrop);
		}
	}
	else
	{
		UE_LOG(LogTelemetry, Error, TEXT("Failed to write round file: %s"), *FilePath);
	}
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------

bool UTelemetryUploadSubsystem::TickFlush(float /*DeltaTime*/)
{
	if (bFlushInFlight)
	{
		return true; // Previous cycle still chaining.
	}

	UFirebaseAuthSubsystem* Auth = GetGameInstance()
		? GetGameInstance()->GetSubsystem<UFirebaseAuthSubsystem>() : nullptr;
	if (!Auth || !Auth->IsConfigured() || Auth->IsGuestMode() || !Auth->IsAuthenticated())
	{
		return true; // Guest/offline: files just accumulate.
	}
	if (!Auth->IsTokenFresh())
	{
		Auth->RequestTokenRefresh(); // Retry next cycle with a fresh token.
		return true;
	}

	TArray<FString> Names;
	IFileManager::Get().FindFiles(Names, *(GetPendingDir() / TEXT("*.json")), true, false);
	if (Names.Num() == 0)
	{
		return true;
	}
	Names.Sort(); // Timestamped names — oldest first.

	FlushQueue.Empty(Names.Num());
	for (const FString& Name : Names)
	{
		FlushQueue.Add(GetPendingDir() / Name);
	}

	UE_LOG(LogTelemetry, Log, TEXT("Flushing %d queued round(s) for uid=%s"), FlushQueue.Num(), *Auth->GetUid());
	bFlushInFlight = true;
	FlushNextFile();
	return true;
}

void UTelemetryUploadSubsystem::FlushNextFile()
{
	while (FlushQueue.Num() > 0)
	{
		CurrentFlushFile = FlushQueue[0];
		FlushQueue.RemoveAt(0);

		FString Content;
		TSharedPtr<FJsonObject> Parsed;
		if (FFileHelper::LoadFileToString(Content, *CurrentFlushFile) &&
			FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Content), Parsed) &&
			Parsed.IsValid())
		{
			CurrentRound = Parsed;
			FlushStep = EFlushStep::Profile;
			SendProfilePatch();
			return;
		}

		// Corrupt file: park it as .bad so it stops blocking the queue but
		// remains inspectable.
		UE_LOG(LogTelemetry, Warning, TEXT("Corrupt pending file parked: %s"), *CurrentFlushFile);
		IFileManager::Get().Move(*(CurrentFlushFile + TEXT(".bad")), *CurrentFlushFile);
	}

	bFlushInFlight = false;
	FlushStep = EFlushStep::Idle;
	CurrentRound.Reset();
	CurrentFlushFile.Empty();
}

FString UTelemetryUploadSubsystem::FirestoreDocumentsBase() const
{
	const UFirebaseAuthSubsystem* Auth = GetGameInstance()->GetSubsystem<UFirebaseAuthSubsystem>();
	return FString::Printf(TEXT("https://firestore.googleapis.com/v1/projects/%s/databases/(default)/documents"),
		*Auth->ProjectId);
}

void UTelemetryUploadSubsystem::SendFirestoreRequest(const FString& Verb, const FString& Url,
	const TSharedPtr<FJsonObject>& Body)
{
	const UFirebaseAuthSubsystem* Auth = GetGameInstance()->GetSubsystem<UFirebaseAuthSubsystem>();

	const TSharedRef<IHttpRequest, ESPMode::ThreadSafe> Request = FHttpModule::Get().CreateRequest();
	Request->SetURL(Url);
	Request->SetVerb(Verb);
	Request->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
	Request->SetHeader(TEXT("Authorization"), FString::Printf(TEXT("Bearer %s"), *Auth->GetIdToken()));
	Request->SetContentAsString(JsonToString(Body));
	Request->SetTimeout(30.0f);
	Request->OnProcessRequestComplete().BindUObject(this, &UTelemetryUploadSubsystem::OnFlushResponse);
	Request->ProcessRequest();
}

void UTelemetryUploadSubsystem::SendProfilePatch()
{
	// PATCH without an updateMask replaces the whole document (creates it on
	// first write) — exactly the README's "one document, overwritten on update".
	const UFirebaseAuthSubsystem* Auth = GetGameInstance()->GetSubsystem<UFirebaseAuthSubsystem>();
	const TSharedPtr<FJsonObject>* ProfileObj = nullptr;

	const TSharedPtr<FJsonObject> Fields = MakeShared<FJsonObject>();
	if (CurrentRound->TryGetObjectField(TEXT("profile"), ProfileObj) && ProfileObj)
	{
		for (int32 Dim = 0; Dim < 8; ++Dim)
		{
			double Value = 0.5;
			(*ProfileObj)->TryGetNumberField(ProfileFieldNames[Dim], Value);
			Fields->SetObjectField(ProfileFieldNames[Dim], FsDouble(Value));
		}
	}
	Fields->SetObjectField(TEXT("updatedAt"), FsTimestamp(FDateTime::UtcNow().ToIso8601()));

	const TSharedPtr<FJsonObject> Body = MakeShared<FJsonObject>();
	Body->SetObjectField(TEXT("fields"), Fields);

	SendFirestoreRequest(TEXT("PATCH"),
		FString::Printf(TEXT("%s/users/%s/profile/current"), *FirestoreDocumentsBase(), *Auth->GetUid()),
		Body);
}

void UTelemetryUploadSubsystem::SendFightPost()
{
	const UFirebaseAuthSubsystem* Auth = GetGameInstance()->GetSubsystem<UFirebaseAuthSubsystem>();
	const TSharedPtr<FJsonObject> Fields = MakeShared<FJsonObject>();

	FString StartedAt;
	CurrentRound->TryGetStringField(TEXT("startedAt"), StartedAt);
	Fields->SetObjectField(TEXT("startedAt"), FsTimestamp(StartedAt));

	double Duration = 0.0, BossHp = 0.0, HeroHp = 0.0;
	CurrentRound->TryGetNumberField(TEXT("durationSeconds"), Duration);
	CurrentRound->TryGetNumberField(TEXT("bossHpAtEnd"), BossHp);
	CurrentRound->TryGetNumberField(TEXT("heroHpAtEnd"), HeroHp);
	Fields->SetObjectField(TEXT("durationSeconds"), FsDouble(Duration));
	Fields->SetObjectField(TEXT("bossHpAtEnd"), FsDouble(BossHp));
	Fields->SetObjectField(TEXT("heroHpAtEnd"), FsDouble(HeroHp));

	FString Outcome = TEXT("loss"), EncounterType = TEXT("boss");
	CurrentRound->TryGetStringField(TEXT("outcome"), Outcome);
	CurrentRound->TryGetStringField(TEXT("encounterType"), EncounterType);
	Fields->SetObjectField(TEXT("outcome"), FsString(Outcome));
	Fields->SetObjectField(TEXT("encounterType"), FsString(EncounterType));

	const TSharedPtr<FJsonObject>* EmotionObj = nullptr;
	const TSharedPtr<FJsonObject> EmotionFields = MakeShared<FJsonObject>();
	if (CurrentRound->TryGetObjectField(TEXT("emotion"), EmotionObj) && EmotionObj)
	{
		double Frustration = 0.0, Flow = 0.0, Boredom = 0.0;
		FString Dominant = TEXT("Neutral");
		(*EmotionObj)->TryGetNumberField(TEXT("frustration"), Frustration);
		(*EmotionObj)->TryGetNumberField(TEXT("flow"), Flow);
		(*EmotionObj)->TryGetNumberField(TEXT("boredom"), Boredom);
		(*EmotionObj)->TryGetStringField(TEXT("dominant"), Dominant);
		EmotionFields->SetObjectField(TEXT("frustration"), FsDouble(Frustration));
		EmotionFields->SetObjectField(TEXT("flow"), FsDouble(Flow));
		EmotionFields->SetObjectField(TEXT("boredom"), FsDouble(Boredom));
		EmotionFields->SetObjectField(TEXT("dominant"), FsString(Dominant));
	}
	Fields->SetObjectField(TEXT("emotion"), FsMap(EmotionFields));

	// Contract: `taunts` is string[] and is OMITTED when empty (the dashboard
	// tolerates its absence — Website/README.md). Only the "taunt" line uploads;
	// tauntDetails stays local.
	TArray<TSharedPtr<FJsonValue>> TauntValues;
	const TArray<TSharedPtr<FJsonValue>>* Taunts = nullptr;
	if (CurrentRound->TryGetArrayField(TEXT("taunts"), Taunts) && Taunts)
	{
		for (const TSharedPtr<FJsonValue>& TauntValue : *Taunts)
		{
			FString Taunt;
			if (TauntValue->TryGetString(Taunt) && !Taunt.IsEmpty())
			{
				TauntValues.Add(MakeShared<FJsonValueObject>(FsString(Taunt)));
			}
		}
	}
	if (TauntValues.Num() > 0)
	{
		Fields->SetObjectField(TEXT("taunts"), FsArray(TauntValues));
	}

	const TSharedPtr<FJsonObject> Body = MakeShared<FJsonObject>();
	Body->SetObjectField(TEXT("fields"), Fields);

	// PATCH to a STABLE doc id derived from the pending file stem
	// (<utc-timestamp>_<guid8>) — idempotent: a flush retry after a later-step
	// failure overwrites the SAME doc instead of POSTing a fresh auto-ID
	// duplicate every 30s cycle. The website reads fights by query, never by
	// id shape, and the /users/{uid}/** rule allows any doc id.
	FString DocId = FPaths::GetBaseFilename(CurrentFlushFile);
	for (TCHAR& Ch : DocId)
	{
		const bool bSafe = (Ch >= '0' && Ch <= '9') || (Ch >= 'a' && Ch <= 'z')
			|| (Ch >= 'A' && Ch <= 'Z') || Ch == '_' || Ch == '-';
		if (!bSafe)
		{
			Ch = TEXT('_');
		}
	}

	SendFirestoreRequest(TEXT("PATCH"),
		FString::Printf(TEXT("%s/users/%s/fights/%s"), *FirestoreDocumentsBase(), *Auth->GetUid(), *DocId),
		Body);
}

void UTelemetryUploadSubsystem::SendMetaCommit()
{
	// The free-tier world aggregate: every client INCREMENTS meta/global itself
	// via commit updateTransforms — no Cloud Functions (Blaze-only) involved.
	// The write is the documented create-capable form (update + empty updateMask
	// + updateTransforms — "equivalent to performing update and transform
	// atomically", the same wire shape every Google SDK emits for
	// set-with-merge increments), so the very first commit CREATES meta/global
	// with no bootstrap write. Shape and semantics are the Website/README.md
	// "meta/global" contract:
	//   totalFights    += 1
	//   bossWins       += 1 when the boss won, += 0 otherwise (ALWAYS sent:
	//                    the created doc must carry every key or the rules'
	//                    shape check on the create path errors out on the
	//                    missing property and denies the write — the
	//                    win-first-round deadlock)
	//   fighters       += 1 on this uid's first-ever upload (local marker),
	//                    += 0 otherwise (always sent, same reason)
	//   profileSamples += 1
	//   profileSum.<dim> += that round's 0-1 profile value
	// firestore.rules enforces monotonic growth, so never send absolute values.
	// Increment-by-zero is valid per the REST FieldTransform spec.
	const UFirebaseAuthSubsystem* Auth = GetGameInstance()->GetSubsystem<UFirebaseAuthSubsystem>();

	bool bBossWon = false;
	CurrentRound->TryGetBoolField(TEXT("bossWon"), bBossWon);

	TArray<TSharedPtr<FJsonValue>> Transforms;
	Transforms.Add(FsIncrement(TEXT("totalFights"), FsInteger(1)));
	Transforms.Add(FsIncrement(TEXT("bossWins"), FsInteger(bBossWon ? 1 : 0)));

	// First-ever upload for this uid -> fighters += 1. Best-effort local marker
	// (a reinstall re-counts the player — accepted free-tier imprecision).
	bPendingFirstUploadMarker = !IFileManager::Get().FileExists(*GetFirstUploadMarkerPath(Auth->GetUid()));
	Transforms.Add(FsIncrement(TEXT("fighters"), FsInteger(bPendingFirstUploadMarker ? 1 : 0)));

	Transforms.Add(FsIncrement(TEXT("profileSamples"), FsInteger(1)));
	const TSharedPtr<FJsonObject>* ProfileObj = nullptr;
	if (CurrentRound->TryGetObjectField(TEXT("profile"), ProfileObj) && ProfileObj)
	{
		for (int32 Dim = 0; Dim < 8; ++Dim)
		{
			double Value = 0.5;
			(*ProfileObj)->TryGetNumberField(ProfileFieldNames[Dim], Value);
			Transforms.Add(FsIncrement(
				FString::Printf(TEXT("profileSum.%s"), ProfileFieldNames[Dim]), FsDouble(Value)));
		}
	}

	// update + empty updateMask + updateTransforms: the ONLY documented
	// create-capable transform write (write.proto: "equivalent to performing
	// update and transform atomically"). A bare standalone `transform` write
	// against a MISSING document is undocumented and may NOT_FOUND in
	// production — never rely on it. Rules evaluation is unchanged (still a
	// create/update with post-transform request.resource.data).
	const TSharedPtr<FJsonObject> Update = MakeShared<FJsonObject>();
	Update->SetStringField(TEXT("name"),
		FString::Printf(TEXT("projects/%s/databases/(default)/documents/meta/global"), *Auth->ProjectId));
	Update->SetObjectField(TEXT("fields"), MakeShared<FJsonObject>());

	const TSharedPtr<FJsonObject> UpdateMask = MakeShared<FJsonObject>();
	UpdateMask->SetArrayField(TEXT("fieldPaths"), TArray<TSharedPtr<FJsonValue>>());

	const TSharedPtr<FJsonObject> Write = MakeShared<FJsonObject>();
	Write->SetObjectField(TEXT("update"), Update);
	Write->SetObjectField(TEXT("updateMask"), UpdateMask);
	Write->SetArrayField(TEXT("updateTransforms"), Transforms);

	TArray<TSharedPtr<FJsonValue>> Writes;
	Writes.Add(MakeShared<FJsonValueObject>(Write));
	const TSharedPtr<FJsonObject> Body = MakeShared<FJsonObject>();
	Body->SetArrayField(TEXT("writes"), Writes);

	SendFirestoreRequest(TEXT("POST"),
		FString::Printf(TEXT("%s:commit"), *FirestoreDocumentsBase()),
		Body);
}

void UTelemetryUploadSubsystem::OnFlushResponse(FHttpRequestPtr /*Request*/, FHttpResponsePtr Response,
	bool bConnectedSuccessfully)
{
	const int32 Code = (bConnectedSuccessfully && Response.IsValid()) ? Response->GetResponseCode() : 0;
	const bool bOk = Code >= 200 && Code < 300;

	if (!bOk)
	{
		UE_LOG(LogTelemetry, Warning, TEXT("Flush step %d failed (HTTP %d) for %s — file stays queued. %s"),
			static_cast<int32>(FlushStep), Code, *FPaths::GetCleanFilename(CurrentFlushFile),
			Response.IsValid() ? *Response->GetContentAsString().Left(256) : TEXT("(no response)"));

		if (Code == 401 || Code == 403)
		{
			if (UFirebaseAuthSubsystem* Auth = GetGameInstance()->GetSubsystem<UFirebaseAuthSubsystem>())
			{
				Auth->NotifyUnauthorized(); // Refresh kicks off; retry next 30s cycle.
			}
		}

		// Poisoned-file guard: a file the SERVER keeps refusing (schema/rules
		// drift) must not spam requests forever. Network blips (Code 0) and
		// plain auth expiry (401) are transient and never count; persistent 403
		// with per-cycle token refreshes = a rules denial, which does. After
		// MaxFlushFailureStreak consecutive refusals the file parks as .stuck
		// (inspectable, rename back to .json to retry after a fix).
		const bool bCountsTowardStreak = Code >= 400 && Code != 401;
		if (bCountsTowardStreak && CurrentFlushFile == LastFailedFlushFile)
		{
			++CurrentFileFailureStreak;
		}
		else if (bCountsTowardStreak)
		{
			LastFailedFlushFile = CurrentFlushFile;
			CurrentFileFailureStreak = 1;
		}
		if (bCountsTowardStreak && CurrentFileFailureStreak >= MaxFlushFailureStreak)
		{
			UE_LOG(LogTelemetry, Error, TEXT("Pending file refused %d times — parking as .stuck: %s"),
				CurrentFileFailureStreak, *CurrentFlushFile);
			IFileManager::Get().Move(*(CurrentFlushFile + TEXT(".stuck")), *CurrentFlushFile);
			LastFailedFlushFile.Empty();
			CurrentFileFailureStreak = 0;
		}

		AbortFlushCycle();
		return;
	}

	switch (FlushStep)
	{
	case EFlushStep::Profile:
		FlushStep = EFlushStep::Fight;
		SendFightPost();
		break;

	case EFlushStep::Fight:
		FlushStep = EFlushStep::MetaCommit;
		SendMetaCommit();
		break;

	case EFlushStep::MetaCommit:
		// All three landed — this round is fully synced.
		if (bPendingFirstUploadMarker)
		{
			// The fighters+1 increment went through — never send it again for this uid.
			if (const UFirebaseAuthSubsystem* Auth = GetGameInstance()->GetSubsystem<UFirebaseAuthSubsystem>())
			{
				FFileHelper::SaveStringToFile(TEXT("uploaded"), *GetFirstUploadMarkerPath(Auth->GetUid()));
			}
			bPendingFirstUploadMarker = false;
		}
		IFileManager::Get().Delete(*CurrentFlushFile, /*RequireExists=*/false);
		if (CurrentFlushFile == LastFailedFlushFile)
		{
			LastFailedFlushFile.Empty(); // Recovered — forget the failure streak.
			CurrentFileFailureStreak = 0;
		}
		UE_LOG(LogTelemetry, Log, TEXT("Uploaded round %s (%d still queued)"),
			*FPaths::GetCleanFilename(CurrentFlushFile), FlushQueue.Num());
		FlushNextFile();
		break;

	default:
		AbortFlushCycle();
		break;
	}
}

void UTelemetryUploadSubsystem::AbortFlushCycle()
{
	FlushQueue.Empty();
	CurrentRound.Reset();
	CurrentFlushFile.Empty();
	FlushStep = EFlushStep::Idle;
	bFlushInFlight = false;
}
