#include "CommunityDifficultySubsystem.h"

#include "FirebaseAuthSubsystem.h"
#include "Dom/JsonObject.h"
#include "Engine/GameInstance.h"
#include "HttpModule.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

DEFINE_LOG_CATEGORY_STATIC(LogCommunityDifficulty, Log, All);

void UCommunityDifficultySubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);

	// Auth first — we fetch with the player's own bearer token.
	Collection.InitializeDependency<UFirebaseAuthSubsystem>();

	if (UFirebaseAuthSubsystem* Auth = GetGameInstance()->GetSubsystem<UFirebaseAuthSubsystem>())
	{
		Auth->OnAuthStateChanged.AddUniqueDynamic(this, &UCommunityDifficultySubsystem::HandleAuthStateChanged);
		if (Auth->IsAuthenticated())
		{
			RefreshGlobalStats(); // Restored session — auth event already fired.
		}
	}

	RefetchTickerHandle = FTSTicker::GetCoreTicker().AddTicker(
		FTickerDelegate::CreateUObject(this, &UCommunityDifficultySubsystem::TickRefetch),
		RefetchIntervalSeconds);
}

void UCommunityDifficultySubsystem::Deinitialize()
{
	if (RefetchTickerHandle.IsValid())
	{
		FTSTicker::GetCoreTicker().RemoveTicker(RefetchTickerHandle);
	}
	Super::Deinitialize();
}

void UCommunityDifficultySubsystem::HandleAuthStateChanged(bool bIsAuthenticated, FString /*Uid*/)
{
	if (bIsAuthenticated)
	{
		RefreshGlobalStats();
	}
}

bool UCommunityDifficultySubsystem::TickRefetch(float /*DeltaTime*/)
{
	RefreshGlobalStats(); // Self-guards on auth state.
	return true;
}

void UCommunityDifficultySubsystem::RefreshGlobalStats()
{
	const UFirebaseAuthSubsystem* Auth = GetGameInstance()
		? GetGameInstance()->GetSubsystem<UFirebaseAuthSubsystem>() : nullptr;
	if (bFetchInFlight || !Auth || !Auth->IsConfigured() || !Auth->IsAuthenticated() || !Auth->IsTokenFresh())
	{
		return;
	}
	bFetchInFlight = true;

	const FString Url = FString::Printf(
		TEXT("https://firestore.googleapis.com/v1/projects/%s/databases/(default)/documents/meta/global"),
		*Auth->ProjectId);

	const TSharedRef<IHttpRequest, ESPMode::ThreadSafe> Request = FHttpModule::Get().CreateRequest();
	Request->SetURL(Url);
	Request->SetVerb(TEXT("GET"));
	Request->SetHeader(TEXT("Authorization"), FString::Printf(TEXT("Bearer %s"), *Auth->GetIdToken()));
	Request->SetTimeout(20.0f);
	Request->OnProcessRequestComplete().BindUObject(this, &UCommunityDifficultySubsystem::OnGlobalStatsResponse);
	Request->ProcessRequest();
}

double UCommunityDifficultySubsystem::ReadFirestoreNumber(const TSharedPtr<FJsonObject>& Fields,
	const FString& FieldName, double Default)
{
	const TSharedPtr<FJsonObject>* Value = nullptr;
	if (!Fields.IsValid() || !Fields->TryGetObjectField(FieldName, Value) || !Value)
	{
		return Default;
	}
	double AsDouble = 0.0;
	if ((*Value)->TryGetNumberField(TEXT("doubleValue"), AsDouble))
	{
		return AsDouble;
	}
	FString AsIntString;
	if ((*Value)->TryGetStringField(TEXT("integerValue"), AsIntString))
	{
		return static_cast<double>(FCString::Atoi64(*AsIntString));
	}
	return Default;
}

void UCommunityDifficultySubsystem::OnGlobalStatsResponse(FHttpRequestPtr /*Request*/,
	FHttpResponsePtr Response, bool bConnectedSuccessfully)
{
	bFetchInFlight = false;

	if (!bConnectedSuccessfully || !Response.IsValid())
	{
		UE_LOG(LogCommunityDifficulty, Warning, TEXT("meta/global fetch failed: no connection."));
		return;
	}

	// 404 = the very first player in the world: no one has committed an
	// increment yet. Not an error — the scalar just stays at the 0.5 default.
	if (Response->GetResponseCode() == 404)
	{
		UE_LOG(LogCommunityDifficulty, Log,
			TEXT("meta/global does not exist yet (first player ever?) — difficulty scalar stays %.2f."),
			GlobalDifficultyScalar);
		return;
	}
	if (Response->GetResponseCode() >= 400)
	{
		UE_LOG(LogCommunityDifficulty, Warning, TEXT("meta/global fetch failed (HTTP %d): %s"),
			Response->GetResponseCode(), *Response->GetContentAsString().Left(256));
		if (Response->GetResponseCode() == 401 || Response->GetResponseCode() == 403)
		{
			if (UFirebaseAuthSubsystem* Auth = GetGameInstance()->GetSubsystem<UFirebaseAuthSubsystem>())
			{
				Auth->NotifyUnauthorized();
			}
		}
		return;
	}

	TSharedPtr<FJsonObject> Json;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Response->GetContentAsString());
	if (!FJsonSerializer::Deserialize(Reader, Json) || !Json.IsValid())
	{
		UE_LOG(LogCommunityDifficulty, Warning, TEXT("meta/global response did not parse."));
		return;
	}

	const TSharedPtr<FJsonObject>* Fields = nullptr;
	if (!Json->TryGetObjectField(TEXT("fields"), Fields) || !Fields)
	{
		UE_LOG(LogCommunityDifficulty, Warning, TEXT("meta/global document has no fields."));
		return;
	}

	const double TotalFights = ReadFirestoreNumber(*Fields, TEXT("totalFights"), 0.0);
	const double ProfileSamples = ReadFirestoreNumber(*Fields, TEXT("profileSamples"), 0.0);
	if (TotalFights < 1.0 || ProfileSamples < 1.0)
	{
		UE_LOG(LogCommunityDifficulty, Log, TEXT("meta/global has no fights yet — scalar stays %.2f."),
			GlobalDifficultyScalar);
		return;
	}

	// profileSum is a MAP field (Website/README.md): unwrap
	// fields.profileSum.mapValue.fields.<dim>.doubleValue.
	double SumDodge = 0.0, SumCombo = 0.0;
	const TSharedPtr<FJsonObject>* ProfileSumValue = nullptr;
	if ((*Fields)->TryGetObjectField(TEXT("profileSum"), ProfileSumValue) && ProfileSumValue)
	{
		const TSharedPtr<FJsonObject>* MapValue = nullptr;
		const TSharedPtr<FJsonObject>* SumFields = nullptr;
		if ((*ProfileSumValue)->TryGetObjectField(TEXT("mapValue"), MapValue) && MapValue &&
			(*MapValue)->TryGetObjectField(TEXT("fields"), SumFields) && SumFields)
		{
			SumDodge = ReadFirestoreNumber(*SumFields, TEXT("dodgeTendency"), 0.0);
			SumCombo = ReadFirestoreNumber(*SumFields, TEXT("comboCompletionRate"), 0.0);
		}
	}
	const double BossWins = ReadFirestoreNumber(*Fields, TEXT("bossWins"), 0.0);

	// Community mean dim = profileSum[dim] / profileSamples (README contract —
	// samples, not fights, in case the two ever diverge).
	const double MeanDodge = SumDodge / ProfileSamples;
	const double MeanCombo = SumCombo / ProfileSamples;

	// THE spec (NEXTSTEP Part 7): global player skill = mean dodge-tendency +
	// combo-completion, mapped to a 0..1 scalar.
	GlobalDifficultyScalar = FMath::Clamp(static_cast<float>((MeanDodge + MeanCombo) * 0.5), 0.0f, 1.0f);
	GlobalTotalFights = static_cast<int64>(TotalFights);
	GlobalBossWinRate = FMath::Clamp(static_cast<float>(BossWins / TotalFights), 0.0f, 1.0f);
	bHasGlobalStats = true;

	UE_LOG(LogCommunityDifficulty, Log,
		TEXT("Community difficulty: fights=%lld meanDodge=%.3f meanCombo=%.3f bossWinRate=%.3f -> scalar=%.3f"),
		GlobalTotalFights, MeanDodge, MeanCombo, GlobalBossWinRate, GlobalDifficultyScalar);

	OnGlobalDifficultyUpdated.Broadcast(GlobalDifficultyScalar);
}
