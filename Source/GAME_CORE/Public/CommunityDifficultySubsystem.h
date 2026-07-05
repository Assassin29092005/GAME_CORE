#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "Containers/Ticker.h"
#include "HttpFwd.h"
#include "CommunityDifficultySubsystem.generated.h"

/** Fired when fresh meta/global stats arrive and the scalar has been recomputed. */
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FOnGlobalDifficultyUpdated, float, DifficultyScalar);

/**
 * M6 "the community is evolving" feature (NEXTSTEP Part 7 item 4): at login this
 * GETs the world-wide aggregate document `meta/global` (written by every
 * client's TelemetryUploadSubsystem via fieldTransforms increments — no server
 * code) and folds it into ONE number:
 *
 *   meanDodgeTendency       = profileSum.dodgeTendency       / profileSamples
 *   meanComboCompletionRate = profileSum.comboCompletionRate / profileSamples
 *   DifficultyScalar        = clamp01((meanDodgeTendency + meanComboCompletionRate) / 2)
 *
 * Interpretation: 0.5 = the profile-EMA neutral point (a world of brand-new
 * players); above 0.5 the player base as a whole dodges more and finishes more
 * combos — i.e. the average opponent got BETTER — so new players face a boss
 * whose baseline was raised by everyone before them.
 *
 * CONSUMERS (read GetGlobalDifficultyScalar(), do not recompute):
 *   - M5 archetype prior: bias the starting-archetype pick toward the harder
 *     checkpoints as the scalar rises (e.g. lerp the profile-similarity prior
 *     toward the "counter"/"rusher" bank entries).
 *   - Constrained-learning win-rate cap: raise config.yaml
 *     constraints.max_boss_win_rate proportionally (Python reads it via the
 *     obs JSON or a launch arg — wiring is a consumer-side task).
 * Nothing here modifies gameplay directly — this subsystem only fetches,
 * computes, exposes, and logs.
 *
 * Freshness: fetched on every auth-state change to signed-in, then re-fetched
 * every RefetchIntervalSeconds while authed. Guest/offline: scalar stays at the
 * 0.5 default and HasGlobalStats() stays false.
 */
UCLASS()
class GAME_CORE_API UCommunityDifficultySubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/** The community difficulty scalar in [0,1]. 0.5 until real data arrives. */
	UFUNCTION(BlueprintPure, Category = "Community")
	float GetGlobalDifficultyScalar() const { return GlobalDifficultyScalar; }

	/** True once a meta/global fetch has succeeded this session. */
	UFUNCTION(BlueprintPure, Category = "Community")
	bool HasGlobalStats() const { return bHasGlobalStats; }

	/** Total fights ever recorded world-wide (0 until fetched). */
	UFUNCTION(BlueprintPure, Category = "Community")
	int64 GetGlobalTotalFights() const { return GlobalTotalFights; }

	/** World-wide boss win rate in [0,1] (0 until fetched). */
	UFUNCTION(BlueprintPure, Category = "Community")
	float GetGlobalBossWinRate() const { return GlobalBossWinRate; }

	/** Manual re-fetch (e.g. from a menu refresh button). No-op unless authed. */
	UFUNCTION(BlueprintCallable, Category = "Community")
	void RefreshGlobalStats();

	UPROPERTY(BlueprintAssignable, Category = "Community")
	FOnGlobalDifficultyUpdated OnGlobalDifficultyUpdated;

private:
	UFUNCTION()
	void HandleAuthStateChanged(bool bIsAuthenticated, FString Uid);

	void OnGlobalStatsResponse(FHttpRequestPtr Request, FHttpResponsePtr Response, bool bConnectedSuccessfully);

	/** Pull a numeric leaf out of a Firestore typed-value field
	 *  ({"doubleValue": x} or {"integerValue": "n"}). Returns Default when absent. */
	static double ReadFirestoreNumber(const TSharedPtr<FJsonObject>& Fields, const FString& FieldName, double Default);

	bool TickRefetch(float DeltaTime);

	float GlobalDifficultyScalar = 0.5f;
	bool bHasGlobalStats = false;
	int64 GlobalTotalFights = 0;
	float GlobalBossWinRate = 0.0f;
	bool bFetchInFlight = false;

	/** Re-fetch cadence while authed (seconds). Long — the aggregate moves slowly. */
	static constexpr float RefetchIntervalSeconds = 600.0f;
	FTSTicker::FDelegateHandle RefetchTickerHandle;
};
