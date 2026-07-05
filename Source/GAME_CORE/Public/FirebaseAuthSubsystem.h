#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "Containers/Ticker.h"
#include "HttpFwd.h"
#include "FirebaseAuthSubsystem.generated.h"

class SLoginScreen;

/** Broadcast whenever the signed-in state changes: successful sign-in/up or
 *  token restore (true, uid), sign-out / guest choice / failed restore (false, ""). */
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnAuthStateChanged, bool, bIsAuthenticated, FString, Uid);

/** Human-readable auth failure ("Wrong email or password.") — the login screen's
 *  error line and any BP toast bind this. */
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnAuthErrorMessage, FString, Message);

/**
 * M6 accounts — Firebase email/password auth over plain REST (no SDK, no plugin;
 * the HTTP + Json modules the project already ships are enough).
 *
 * Endpoints (Identity Toolkit / Secure Token — both free tier):
 *   POST https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=<WebApiKey>
 *   POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=<WebApiKey>
 *   POST https://securetoken.googleapis.com/v1/token?key=<WebApiKey>       (refresh)
 *
 * Config: WebApiKey / ProjectId live in Config/DefaultGame.ini under
 * [/Script/GAME_CORE.FirebaseAuthSubsystem]. They SHIP EMPTY — until the real
 * Firebase project's values are pasted in, the subsystem logs one loud warning
 * and forces guest mode (everything queues locally, nothing uploads, no login
 * UI ever appears). No secret ships in the build: the Web API key is a public
 * client identifier by design; per-user data is protected by firestore.rules.
 *
 * Persistence: Saved/Auth/auth.json (uid + idToken + refreshToken + expiry).
 * idTokens live ~1h; RequestTokenRefresh() exchanges the long-lived refreshToken,
 * and NotifyUnauthorized() (called by the uploader on any 401) funnels into the
 * same path. A restore-refresh also runs at startup so a returning player never
 * sees the login screen.
 *
 * Login UI: a core ticker waits for the game viewport + a begun-play game world
 * (the subsystem initializes long before either exists), then decides ONCE:
 * unconfigured -> skip, restored/authed -> skip, otherwise show SLoginScreen.
 * Guest mode closes it and stays local-only until a later sign-in.
 */
UCLASS(Config = Game)
class GAME_CORE_API UFirebaseAuthSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	// --- Config (Config/DefaultGame.ini [/Script/GAME_CORE.FirebaseAuthSubsystem]) ---

	/** Firebase console -> Project settings -> General -> Web API Key. Empty = guest-only build. */
	UPROPERTY(Config)
	FString WebApiKey;

	/** Firebase project id (e.g. "game-core-boss") — used for Firestore REST URLs. */
	UPROPERTY(Config)
	FString ProjectId;

	// --- USubsystem ---
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	// --- Auth API ---

	UFUNCTION(BlueprintCallable, Category = "Firebase|Auth")
	void SignUp(const FString& Email, const FString& Password);

	UFUNCTION(BlueprintCallable, Category = "Firebase|Auth")
	void SignIn(const FString& Email, const FString& Password);

	/** Clears the persisted session and re-shows the login screen (if configured). */
	UFUNCTION(BlueprintCallable, Category = "Firebase|Auth")
	void SignOut();

	/** Play without an account: closes the login screen, telemetry queues locally
	 *  under Saved/Telemetry/pending/ and is never flushed until a real sign-in. */
	UFUNCTION(BlueprintCallable, Category = "Firebase|Auth")
	void ContinueAsGuest();

	/** True once WebApiKey AND ProjectId are non-empty (real Firebase project pasted in). */
	UFUNCTION(BlueprintPure, Category = "Firebase|Auth")
	bool IsConfigured() const { return !WebApiKey.IsEmpty() && !ProjectId.IsEmpty(); }

	UFUNCTION(BlueprintPure, Category = "Firebase|Auth")
	bool IsAuthenticated() const { return !IdToken.IsEmpty() && !Uid.IsEmpty(); }

	UFUNCTION(BlueprintPure, Category = "Firebase|Auth")
	bool IsGuestMode() const { return bGuestMode; }

	UFUNCTION(BlueprintPure, Category = "Firebase|Auth")
	FString GetUid() const { return Uid; }

	/** Raw bearer token for Firestore REST calls. Check IsTokenFresh() first. */
	const FString& GetIdToken() const { return IdToken; }

	/** True while the idToken has comfortably (>2 min) before expiry. Uploaders
	 *  should skip a flush cycle and RequestTokenRefresh() when this goes false. */
	bool IsTokenFresh() const;

	/** Exchange the refreshToken for a new idToken. No-op if already refreshing
	 *  or no refreshToken is stored. */
	void RequestTokenRefresh();

	/** Call on any 401/403 from Firestore — kicks a token refresh; the caller
	 *  leaves its work queued and retries on its next cycle. */
	void NotifyUnauthorized() { RequestTokenRefresh(); }

	// --- Delegates ---

	UPROPERTY(BlueprintAssignable, Category = "Firebase|Auth")
	FOnAuthStateChanged OnAuthStateChanged;

	UPROPERTY(BlueprintAssignable, Category = "Firebase|Auth")
	FOnAuthErrorMessage OnAuthError;

private:
	// --- REST plumbing ---
	void SendCredentialRequest(const FString& Endpoint, const FString& Email, const FString& Password);
	void OnCredentialResponse(FHttpRequestPtr Request, FHttpResponsePtr Response, bool bConnectedSuccessfully);
	void OnRefreshResponse(FHttpRequestPtr Request, FHttpResponsePtr Response, bool bConnectedSuccessfully);

	/** Map Identity Toolkit error codes (EMAIL_EXISTS, INVALID_LOGIN_CREDENTIALS, ...)
	 *  to a sentence the login screen can show verbatim. */
	static FString FriendlyAuthError(const FString& ServerCode);

	void ApplyAuthPayload(const FString& InUid, const FString& InIdToken, const FString& InRefreshToken, double ExpiresInSeconds, const FString& InEmail);
	void ClearAuth(bool bDeletePersisted);
	void ReportAuthError(const FString& Message);

	// --- Persistence (Saved/Auth/auth.json) ---
	static FString GetAuthFilePath();
	void SavePersistedAuth() const;
	bool LoadPersistedAuth();

	// --- Login screen lifecycle ---
	bool TickLoginScreen(float DeltaTime);
	void ShowLoginScreen();
	void CloseLoginScreen();

	// --- State ---
	FString Uid;
	FString IdToken;
	FString RefreshToken;
	FString CachedEmail;
	int64 TokenExpiresAtUnix = 0;

	bool bGuestMode = false;
	bool bRefreshInFlight = false;
	bool bCredentialRequestInFlight = false;
	/** True while the startup restore-refresh is pending — the login-screen ticker
	 *  waits for its verdict instead of flashing the screen at a returning player. */
	bool bStartupRestorePending = false;
	/** The show/skip decision is made exactly once per app run (SignOut re-arms it). */
	bool bLoginDecisionMade = false;

	FTSTicker::FDelegateHandle LoginTickerHandle;
	TSharedPtr<SLoginScreen> LoginScreen;
	bool bLoginScreenOnViewport = false;
};
