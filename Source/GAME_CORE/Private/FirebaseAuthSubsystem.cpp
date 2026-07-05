#include "FirebaseAuthSubsystem.h"

#include "LoginScreen.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "GenericPlatform/GenericPlatformHttp.h"
#include "HAL/FileManager.h"
#include "HttpModule.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

DEFINE_LOG_CATEGORY_STATIC(LogFirebaseAuth, Log, All);

namespace
{
	const TCHAR* IdentityToolkitBase = TEXT("https://identitytoolkit.googleapis.com/v1/accounts:");
	const TCHAR* SecureTokenUrl = TEXT("https://securetoken.googleapis.com/v1/token");

	/** Refresh when less than this long remains on the idToken (~1h lifetime). */
	constexpr int64 TokenFreshMarginSeconds = 120;
}

// ---------------------------------------------------------------------------
// Subsystem lifecycle
// ---------------------------------------------------------------------------

void UFirebaseAuthSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);

	if (!IsConfigured())
	{
		// Deliberately LOUD — this is the one-line diagnosis for "why is nothing
		// uploading". Paste the real values into Config/DefaultGame.ini under
		// [/Script/GAME_CORE.FirebaseAuthSubsystem] (see Website/README.md
		// "Connect Firebase") and the whole account stack switches on.
		UE_LOG(LogFirebaseAuth, Warning,
			TEXT("Firebase not configured — guest mode only. WebApiKey/ProjectId are empty in ")
			TEXT("[/Script/GAME_CORE.FirebaseAuthSubsystem] (Config/DefaultGame.ini). ")
			TEXT("Telemetry will queue to Saved/Telemetry/pending/ and never upload."));
		bGuestMode = true;
		return; // No login UI, no restore — nothing to talk to.
	}

	// Returning player: restore the persisted session and refresh the (almost
	// certainly expired) idToken before the login-screen decision is made.
	if (LoadPersistedAuth() && !RefreshToken.IsEmpty())
	{
		bStartupRestorePending = true;
		RequestTokenRefresh();
	}

	// The subsystem initializes before any viewport/world exists — poll until
	// the game world has begun play, then make the show/skip decision once.
	LoginTickerHandle = FTSTicker::GetCoreTicker().AddTicker(
		FTickerDelegate::CreateUObject(this, &UFirebaseAuthSubsystem::TickLoginScreen), 0.25f);
}

void UFirebaseAuthSubsystem::Deinitialize()
{
	if (LoginTickerHandle.IsValid())
	{
		FTSTicker::GetCoreTicker().RemoveTicker(LoginTickerHandle);
		LoginTickerHandle.Reset();
	}
	CloseLoginScreen();
	Super::Deinitialize();
}

// ---------------------------------------------------------------------------
// Public auth API
// ---------------------------------------------------------------------------

void UFirebaseAuthSubsystem::SignUp(const FString& Email, const FString& Password)
{
	SendCredentialRequest(TEXT("signUp"), Email, Password);
}

void UFirebaseAuthSubsystem::SignIn(const FString& Email, const FString& Password)
{
	SendCredentialRequest(TEXT("signInWithPassword"), Email, Password);
}

void UFirebaseAuthSubsystem::SignOut()
{
	ClearAuth(/*bDeletePersisted=*/true);
	bGuestMode = false;
	bLoginDecisionMade = false; // Re-arm the ticker decision so the screen returns.
	if (!LoginTickerHandle.IsValid())
	{
		LoginTickerHandle = FTSTicker::GetCoreTicker().AddTicker(
			FTickerDelegate::CreateUObject(this, &UFirebaseAuthSubsystem::TickLoginScreen), 0.25f);
	}
	OnAuthStateChanged.Broadcast(false, FString());
}

void UFirebaseAuthSubsystem::ContinueAsGuest()
{
	UE_LOG(LogFirebaseAuth, Log, TEXT("Continuing as guest — telemetry stays local until a sign-in."));
	bGuestMode = true;
	CloseLoginScreen();
	OnAuthStateChanged.Broadcast(false, FString());
}

bool UFirebaseAuthSubsystem::IsTokenFresh() const
{
	return IsAuthenticated()
		&& FDateTime::UtcNow().ToUnixTimestamp() < (TokenExpiresAtUnix - TokenFreshMarginSeconds);
}

void UFirebaseAuthSubsystem::RequestTokenRefresh()
{
	if (bRefreshInFlight || RefreshToken.IsEmpty() || !IsConfigured())
	{
		return;
	}
	bRefreshInFlight = true;

	// Secure Token API wants form-encoding, not JSON (unlike Identity Toolkit).
	const FString Body = FString::Printf(TEXT("grant_type=refresh_token&refresh_token=%s"),
		*FGenericPlatformHttp::UrlEncode(RefreshToken));

	const TSharedRef<IHttpRequest, ESPMode::ThreadSafe> Request = FHttpModule::Get().CreateRequest();
	Request->SetURL(FString::Printf(TEXT("%s?key=%s"), SecureTokenUrl, *WebApiKey));
	Request->SetVerb(TEXT("POST"));
	Request->SetHeader(TEXT("Content-Type"), TEXT("application/x-www-form-urlencoded"));
	Request->SetContentAsString(Body);
	Request->SetTimeout(20.0f);
	Request->OnProcessRequestComplete().BindUObject(this, &UFirebaseAuthSubsystem::OnRefreshResponse);
	Request->ProcessRequest();
}

// ---------------------------------------------------------------------------
// REST plumbing
// ---------------------------------------------------------------------------

void UFirebaseAuthSubsystem::SendCredentialRequest(const FString& Endpoint, const FString& Email, const FString& Password)
{
	if (!IsConfigured())
	{
		ReportAuthError(TEXT("Online accounts are not configured in this build."));
		return;
	}
	if (bCredentialRequestInFlight)
	{
		return; // One at a time; the login screen is busy-locked anyway.
	}
	bCredentialRequestInFlight = true;
	if (LoginScreen.IsValid())
	{
		LoginScreen->SetBusy(true);
	}

	const TSharedPtr<FJsonObject> Body = MakeShared<FJsonObject>();
	Body->SetStringField(TEXT("email"), Email);
	Body->SetStringField(TEXT("password"), Password);
	Body->SetBoolField(TEXT("returnSecureToken"), true);

	FString BodyString;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&BodyString);
	FJsonSerializer::Serialize(Body.ToSharedRef(), Writer);

	const TSharedRef<IHttpRequest, ESPMode::ThreadSafe> Request = FHttpModule::Get().CreateRequest();
	Request->SetURL(FString::Printf(TEXT("%s%s?key=%s"), IdentityToolkitBase, *Endpoint, *WebApiKey));
	Request->SetVerb(TEXT("POST"));
	Request->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
	Request->SetContentAsString(BodyString);
	Request->SetTimeout(20.0f);
	Request->OnProcessRequestComplete().BindUObject(this, &UFirebaseAuthSubsystem::OnCredentialResponse);
	Request->ProcessRequest();
}

void UFirebaseAuthSubsystem::OnCredentialResponse(FHttpRequestPtr /*Request*/, FHttpResponsePtr Response, bool bConnectedSuccessfully)
{
	bCredentialRequestInFlight = false;
	if (LoginScreen.IsValid())
	{
		LoginScreen->SetBusy(false);
	}

	if (!bConnectedSuccessfully || !Response.IsValid())
	{
		ReportAuthError(TEXT("Network error — check your connection and try again."));
		return;
	}

	TSharedPtr<FJsonObject> Json;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Response->GetContentAsString());
	if (!FJsonSerializer::Deserialize(Reader, Json) || !Json.IsValid())
	{
		ReportAuthError(TEXT("Unexpected server response."));
		return;
	}

	if (Response->GetResponseCode() >= 400)
	{
		FString Code;
		const TSharedPtr<FJsonObject>* ErrorObj = nullptr;
		if (Json->TryGetObjectField(TEXT("error"), ErrorObj) && ErrorObj)
		{
			(*ErrorObj)->TryGetStringField(TEXT("message"), Code);
		}
		UE_LOG(LogFirebaseAuth, Warning, TEXT("Auth request failed (%d): %s"), Response->GetResponseCode(), *Code);
		ReportAuthError(FriendlyAuthError(Code));
		return;
	}

	FString ExpiresIn = TEXT("3600");
	Json->TryGetStringField(TEXT("expiresIn"), ExpiresIn);
	ApplyAuthPayload(
		Json->GetStringField(TEXT("localId")),
		Json->GetStringField(TEXT("idToken")),
		Json->GetStringField(TEXT("refreshToken")),
		FCString::Atod(*ExpiresIn),
		Json->HasTypedField<EJson::String>(TEXT("email")) ? Json->GetStringField(TEXT("email")) : FString());

	UE_LOG(LogFirebaseAuth, Log, TEXT("Signed in — uid=%s"), *Uid);
	bGuestMode = false;
	CloseLoginScreen();
	OnAuthStateChanged.Broadcast(true, Uid);
}

void UFirebaseAuthSubsystem::OnRefreshResponse(FHttpRequestPtr /*Request*/, FHttpResponsePtr Response, bool bConnectedSuccessfully)
{
	bRefreshInFlight = false;
	const bool bWasStartupRestore = bStartupRestorePending;
	bStartupRestorePending = false;

	if (!bConnectedSuccessfully || !Response.IsValid())
	{
		// Offline is NOT a sign-out: keep the stored session (IsAuthenticated()
		// stays true, so a returning player skips the login screen); the token
		// just isn't fresh, so the uploader keeps queueing until connectivity
		// returns and a later refresh succeeds.
		UE_LOG(LogFirebaseAuth, Warning, TEXT("Token refresh failed: no connection. Staying queued."));
		return;
	}

	TSharedPtr<FJsonObject> Json;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Response->GetContentAsString());
	const bool bParsed = FJsonSerializer::Deserialize(Reader, Json) && Json.IsValid();

	if (Response->GetResponseCode() >= 400 || !bParsed)
	{
		// A REJECTED refresh token (revoked/expired/user deleted) invalidates the
		// whole session — clear it so the login screen returns.
		UE_LOG(LogFirebaseAuth, Warning, TEXT("Token refresh rejected (%d) — clearing stored session."),
			Response->GetResponseCode());
		ClearAuth(/*bDeletePersisted=*/true);
		if (!bWasStartupRestore)
		{
			OnAuthStateChanged.Broadcast(false, FString());
		}
		return;
	}

	// Secure Token API uses snake_case, unlike Identity Toolkit.
	FString ExpiresIn = TEXT("3600");
	Json->TryGetStringField(TEXT("expires_in"), ExpiresIn);
	ApplyAuthPayload(
		Json->GetStringField(TEXT("user_id")),
		Json->GetStringField(TEXT("id_token")),
		Json->GetStringField(TEXT("refresh_token")),
		FCString::Atod(*ExpiresIn),
		CachedEmail);

	UE_LOG(LogFirebaseAuth, Log, TEXT("Token refreshed — uid=%s (restore=%s)"),
		*Uid, bWasStartupRestore ? TEXT("startup") : TEXT("runtime"));
	OnAuthStateChanged.Broadcast(true, Uid);
}

FString UFirebaseAuthSubsystem::FriendlyAuthError(const FString& ServerCode)
{
	// Identity Toolkit sometimes suffixes codes (e.g. "WEAK_PASSWORD : ..."), so
	// match by prefix/contains rather than equality.
	if (ServerCode.Contains(TEXT("INVALID_LOGIN_CREDENTIALS")) ||
		ServerCode.Contains(TEXT("EMAIL_NOT_FOUND")) ||
		ServerCode.Contains(TEXT("INVALID_PASSWORD")))
	{
		return TEXT("Wrong email or password.");
	}
	if (ServerCode.Contains(TEXT("EMAIL_EXISTS")))
	{
		return TEXT("That email already has an account — use Sign In.");
	}
	if (ServerCode.Contains(TEXT("WEAK_PASSWORD")))
	{
		return TEXT("Password must be at least 6 characters.");
	}
	if (ServerCode.Contains(TEXT("INVALID_EMAIL")))
	{
		return TEXT("That email address is not valid.");
	}
	if (ServerCode.Contains(TEXT("TOO_MANY_ATTEMPTS")))
	{
		return TEXT("Too many attempts — wait a moment and try again.");
	}
	if (ServerCode.Contains(TEXT("USER_DISABLED")))
	{
		return TEXT("This account has been disabled.");
	}
	return TEXT("Sign-in failed — try again.");
}

void UFirebaseAuthSubsystem::ApplyAuthPayload(const FString& InUid, const FString& InIdToken,
	const FString& InRefreshToken, double ExpiresInSeconds, const FString& InEmail)
{
	Uid = InUid;
	IdToken = InIdToken;
	RefreshToken = InRefreshToken;
	if (!InEmail.IsEmpty())
	{
		CachedEmail = InEmail;
	}
	TokenExpiresAtUnix = FDateTime::UtcNow().ToUnixTimestamp() + static_cast<int64>(ExpiresInSeconds);
	SavePersistedAuth();
}

void UFirebaseAuthSubsystem::ClearAuth(bool bDeletePersisted)
{
	Uid.Empty();
	IdToken.Empty();
	RefreshToken.Empty();
	CachedEmail.Empty();
	TokenExpiresAtUnix = 0;
	if (bDeletePersisted)
	{
		IFileManager::Get().Delete(*GetAuthFilePath(), /*RequireExists=*/false);
	}
}

void UFirebaseAuthSubsystem::ReportAuthError(const FString& Message)
{
	if (LoginScreen.IsValid())
	{
		LoginScreen->SetErrorText(FText::FromString(Message));
	}
	OnAuthError.Broadcast(Message);
}

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

FString UFirebaseAuthSubsystem::GetAuthFilePath()
{
	return FPaths::ProjectSavedDir() / TEXT("Auth") / TEXT("auth.json");
}

void UFirebaseAuthSubsystem::SavePersistedAuth() const
{
	const TSharedPtr<FJsonObject> Json = MakeShared<FJsonObject>();
	Json->SetStringField(TEXT("uid"), Uid);
	Json->SetStringField(TEXT("email"), CachedEmail);
	Json->SetStringField(TEXT("idToken"), IdToken);
	Json->SetStringField(TEXT("refreshToken"), RefreshToken);
	Json->SetStringField(TEXT("expiresAtUnix"), FString::Printf(TEXT("%lld"), TokenExpiresAtUnix));

	FString Out;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
	FJsonSerializer::Serialize(Json.ToSharedRef(), Writer);
	FFileHelper::SaveStringToFile(Out, *GetAuthFilePath());
}

bool UFirebaseAuthSubsystem::LoadPersistedAuth()
{
	FString In;
	if (!FFileHelper::LoadFileToString(In, *GetAuthFilePath()))
	{
		return false;
	}
	TSharedPtr<FJsonObject> Json;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(In);
	if (!FJsonSerializer::Deserialize(Reader, Json) || !Json.IsValid())
	{
		return false;
	}
	Json->TryGetStringField(TEXT("uid"), Uid);
	Json->TryGetStringField(TEXT("email"), CachedEmail);
	Json->TryGetStringField(TEXT("idToken"), IdToken);
	Json->TryGetStringField(TEXT("refreshToken"), RefreshToken);
	FString Expires;
	Json->TryGetStringField(TEXT("expiresAtUnix"), Expires);
	TokenExpiresAtUnix = FCString::Atoi64(*Expires);
	return !RefreshToken.IsEmpty();
}

// ---------------------------------------------------------------------------
// Login screen lifecycle
// ---------------------------------------------------------------------------

bool UFirebaseAuthSubsystem::TickLoginScreen(float /*DeltaTime*/)
{
	if (bLoginDecisionMade)
	{
		LoginTickerHandle.Reset(); // Decision made — drop the ticker (SignOut re-arms).
		return false;
	}

	// Wait for a real, begun-play game world AND a viewport to attach to.
	const UGameInstance* GameInstance = GetGameInstance();
	UWorld* World = GameInstance ? GameInstance->GetWorld() : nullptr;
	if (!World || !World->IsGameWorld() || !World->HasBegunPlay() ||
		!GEngine || !GEngine->GameViewport)
	{
		return true; // Keep polling.
	}

	// Startup restore still in flight — wait for its verdict before deciding,
	// so a returning player never sees the screen flash.
	if (bStartupRestorePending || bRefreshInFlight)
	{
		return true;
	}

	bLoginDecisionMade = true;
	LoginTickerHandle.Reset(); // Ticker self-removes below; SignOut re-arms a fresh one.
	if (!IsConfigured() || IsAuthenticated() || bGuestMode)
	{
		return false; // Skip entirely.
	}
	ShowLoginScreen();
	return false;
}

void UFirebaseAuthSubsystem::ShowLoginScreen()
{
	if (bLoginScreenOnViewport || !GEngine || !GEngine->GameViewport)
	{
		return;
	}

	LoginScreen = SNew(SLoginScreen).AuthSubsystem(this);
	GEngine->GameViewport->AddViewportWidgetContent(LoginScreen.ToSharedRef(), /*ZOrder=*/100);
	bLoginScreenOnViewport = true;

	// UI-only input + cursor while the screen is up; restored on close.
	const UGameInstance* GameInstance = GetGameInstance();
	UWorld* World = GameInstance ? GameInstance->GetWorld() : nullptr;
	if (APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr)
	{
		FInputModeUIOnly InputMode;
		InputMode.SetWidgetToFocus(LoginScreen->GetInitialFocusWidget());
		InputMode.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);
		PC->SetInputMode(InputMode);
		PC->bShowMouseCursor = true;
	}
}

void UFirebaseAuthSubsystem::CloseLoginScreen()
{
	if (bLoginScreenOnViewport && LoginScreen.IsValid() && GEngine && GEngine->GameViewport)
	{
		GEngine->GameViewport->RemoveViewportWidgetContent(LoginScreen.ToSharedRef());
	}
	bLoginScreenOnViewport = false;

	if (LoginScreen.IsValid())
	{
		const UGameInstance* GameInstance = GetGameInstance();
		UWorld* World = GameInstance ? GameInstance->GetWorld() : nullptr;
		if (APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr)
		{
			PC->SetInputMode(FInputModeGameOnly());
			PC->bShowMouseCursor = false;
		}
	}
	LoginScreen.Reset();
}
