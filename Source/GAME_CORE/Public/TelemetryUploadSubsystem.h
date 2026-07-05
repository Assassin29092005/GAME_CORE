#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "Containers/Ticker.h"
#include "HttpFwd.h"
#include "BossExplainabilityComponent.h"
#include "TelemetryUploadSubsystem.generated.h"

class UCombatComponent;
class UBossActionComponent;
class UPlayerProfileComponent;
class UEmotionEstimationComponent;

/**
 * M6 local-first telemetry — one JSON file per completed round, ALWAYS written
 * to Saved/Telemetry/pending/<utc-timestamp>.json (offline/guest included),
 * then flushed to Firestore over REST when (and only when) a real sign-in
 * exists. Failures leave files queued; success deletes them. Nothing here ever
 * blocks or affects gameplay — fire-and-forget HTTP on the game thread.
 *
 * Round-end sources (bound lazily via a 1s ticker, since this subsystem
 * initializes long before the arena actors exist — the GameFeelSubsystem
 * install pattern):
 *   - boss  UBossActionComponent::OnBossDied            -> outcome "win"  (player's perspective)
 *   - hero  UCombatComponent::OnHealthDepleted          -> outcome "loss"
 * Actors persist across round resets (teleported, never destroyed), so binding
 * is one-shot per world; a world change clears and rebinds.
 *
 * Payload contract: Website/README.md "Firestore schema" — the README is the
 * source of truth both the game and the site build against. Per round:
 *   PATCH users/{uid}/profile/current      (8-dim profile + updatedAt)
 *   PATCH users/{uid}/fights/{fileStem}    (fight doc incl. emotion + taunts[] —
 *                                           doc id derives from the pending file
 *                                           name, so a retried flush OVERWRITES
 *                                           the same doc instead of minting an
 *                                           auto-ID duplicate per cycle; the
 *                                           website reads fights by query, never
 *                                           by id shape)
 *   POST  documents:commit                 (updateTransforms INCREMENTS on
 *                                           meta/global — the free-tier
 *                                           aggregation: no Cloud Functions,
 *                                           every client increments the world
 *                                           totals itself)
 * All three must succeed before the pending file is deleted; the profile and
 * fight writes are idempotent, the meta commit stays at-least-once (a double
 * increment after a crash between step 3 succeeding and the file delete is the
 * accepted free-tier worst case). A file that keeps failing server-side
 * (non-auth 4xx/5xx) is parked as .stuck after a failure streak so one
 * poisoned round can never spam requests or block the queue forever.
 *
 * Bot rounds are NOT captured: FinishRound self-suppresses under -NoTelemetry
 * (passed by Tools/run_training.ps1), when the hero pawn's AutoHeroComponent
 * is enabled, or when the hero CombatComponent runs bAutoResetRoundOnDeath —
 * overnight sparring data would otherwise inflate users/{uid}/fights and skew
 * the meta/global community-difficulty aggregates. Guest mode additionally
 * caps pending/ at the newest MaxPendingFiles rounds.
 *
 * Taunts: FBossInsight broadcasts from UBossExplainabilityComponent are
 * accumulated during the round (unique per AdaptationTag, latest wins); if the
 * round ends with none broadcast, GenerateInsights(profile) is called directly
 * so every fight doc carries what the boss "learned".
 */
UCLASS()
class GAME_CORE_API UTelemetryUploadSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/** Where round files wait for upload. Exposed for tests/tools. */
	static FString GetPendingDir();

	/** Marker proving this uid already counted toward meta/global `fighters`. */
	static FString GetFirstUploadMarkerPath(const FString& Uid);

	/** Number of queued (not yet uploaded) round files. */
	UFUNCTION(BlueprintPure, Category = "Telemetry")
	int32 GetPendingFileCount() const;

private:
	// --- Round-end capture ---

	UFUNCTION()
	void HandleBossDied();

	UFUNCTION()
	void HandleHeroHealthDepleted();

	UFUNCTION()
	void HandleBossInsight(const FBossInsight& Insight);

	/** Build the round JSON (README schema, plain values) and write it to pending/. */
	void FinishRound(bool bPlayerWon);

	/** True when this round must NOT be captured: -NoTelemetry launch arg,
	 *  AutoHero sparring bot driving the hero, or training auto-reset mode. */
	bool IsTelemetrySuppressed() const;

	// --- Lazy actor binding (1s ticker) ---
	bool TickBind(float DeltaTime);
	void ClearBindings();

	// --- Upload (30s ticker, authed only) ---
	bool TickFlush(float DeltaTime);
	void FlushNextFile();
	void SendProfilePatch();
	void SendFightPost();
	void SendMetaCommit();
	void OnFlushResponse(FHttpRequestPtr Request, FHttpResponsePtr Response, bool bConnectedSuccessfully);
	void AbortFlushCycle();

	/** Common request setup: Firestore URL + Bearer idToken + JSON body. */
	void SendFirestoreRequest(const FString& Verb, const FString& Url, const TSharedPtr<FJsonObject>& Body);

	FString FirestoreDocumentsBase() const;

	// --- State ---

	FTSTicker::FDelegateHandle BindTickerHandle;
	FTSTicker::FDelegateHandle FlushTickerHandle;

	TWeakObjectPtr<UWorld> BoundWorld;
	TWeakObjectPtr<UCombatComponent> HeroCombat;
	TWeakObjectPtr<UPlayerProfileComponent> HeroProfile;
	TWeakObjectPtr<UBossActionComponent> BossAction;
	TWeakObjectPtr<UCombatComponent> BossCombat;
	TWeakObjectPtr<UEmotionEstimationComponent> BossEmotion;
	TWeakObjectPtr<UBossExplainabilityComponent> BossExplain;

	/** World seconds when the current round began (set at bind + each round end).
	 *  Later rounds include the ~2.5s inter-round pause — accepted imprecision. */
	double RoundStartWorldSeconds = 0.0;

	/** Both delegates can observe the same death cascade — ignore a second
	 *  round-end within this window (realtime seconds). */
	double LastRoundEndRealSeconds = -10.0;

	/** Insights broadcast during the current round, unique per AdaptationTag. */
	TArray<FBossInsight> RoundInsights;

	// Flush cycle: one file at a time, three sequential requests per file.
	enum class EFlushStep : uint8 { Idle, Profile, Fight, MetaCommit };
	EFlushStep FlushStep = EFlushStep::Idle;
	bool bFlushInFlight = false;
	TArray<FString> FlushQueue;               // Full paths, oldest first.
	FString CurrentFlushFile;
	TSharedPtr<FJsonObject> CurrentRound;     // Parsed pending file being uploaded.
	/** True while the in-flight meta commit carries the one-time fighters+1;
	 *  the success handler persists the marker so it is never sent twice. */
	bool bPendingFirstUploadMarker = false;

	/** Poisoned-file guard: consecutive NON-auth server failures for the same
	 *  pending file. At MaxFlushFailureStreak the file is parked as .stuck. */
	FString LastFailedFlushFile;
	int32 CurrentFileFailureStreak = 0;
};
