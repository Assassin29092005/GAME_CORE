#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Widgets/SLeafWidget.h"
#include "BossStatusHUD.generated.h"

class UBossActionComponent;
class UCombatComponent;
class UHitReactionComponent;

/**
 * Paint-state shared between UBossStatusHUDComponent (game thread, writes every
 * component tick) and SBossStatusWidget (reads in OnPaint). Plain struct, not a
 * USTRUCT — it never crosses into reflection; the TSharedPtr keeps it alive for
 * whichever side outlives the other during teardown.
 */
struct FBossHUDState
{
	FText BossName;

	// Bars (all fractions 0-1).
	float HealthFraction = 1.0f;
	float ChipFraction = 1.0f;      // trailing ghost segment; >= HealthFraction
	float StaggerFraction = 0.0f;   // GetCurrentStagger() / HeavyStaggerThreshold

	// Hit-confirm border flash (0 = off, 1 = just landed).
	float BorderFlashAlpha = 0.0f;

	// Whole-widget opacity: fades to 0 on boss death, back to 1 on round reset.
	float WidgetOpacity = 1.0f;

	// Telegraph indicator (contract #1: OnBossTelegraph).
	bool bTelegraphActive = false;
	bool bTelegraphHeavy = false;   // true = red unblockable ring; false = yellow parry tick
	float TelegraphElapsed = 0.0f;  // seconds since broadcast (drives the pulse)
	float TelegraphRemainingFraction = 1.0f; // 1 → 0 over the telegraph window
	FLinearColor TelegraphColor = FLinearColor::Red;

	// Boss screen position (slate units, DPI-corrected) for the ring; when the
	// projection fails or lands off-screen the widget falls back to a banner.
	bool bBossOnScreen = false;
	FVector2D BossScreenPos = FVector2D::ZeroVector;

	// Monotonic time for paint-side pulses (stagger-full flash etc.).
	float TimeSeconds = 0.0f;
};

/**
 * Code-only boss status HUD (guide.md 7.2, boss-bar research spec). Pure Slate —
 * no UMG assets, no WBP. Fills the viewport (hit-test invisible) and paints:
 *   - top-center name plate + HP bar (backplate → white damage chip → crimson
 *     fill → top highlight), GoW-style stagger/stun meter underneath,
 *   - hit-confirm border flash around the bar,
 *   - the unblockable telegraph: red pulsing ring at the boss's projected screen
 *     position (banner fallback when off-screen), brief yellow tick for
 *     parryable specials.
 * All values are read from the shared FBossHUDState each paint; this widget owns
 * zero game state and holds zero UObject pointers.
 */
class GAME_CORE_API SBossStatusWidget : public SLeafWidget
{
public:
	SLATE_BEGIN_ARGS(SBossStatusWidget) {}
		SLATE_ARGUMENT(TSharedPtr<FBossHUDState>, State)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry,
		const FSlateRect& MyCullingRect, FSlateWindowElementList& OutDrawElements,
		int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const override;

	virtual FVector2D ComputeDesiredSize(float LayoutScaleMultiplier) const override
	{
		return FVector2D::ZeroVector; // painted into the full viewport overlay slot
	}

	virtual bool SupportsKeyboardFocus() const override { return false; }

private:
	int32 PaintBossBars(const FGeometry& AllottedGeometry, FSlateWindowElementList& OutDrawElements, int32 LayerId) const;
	int32 PaintTelegraph(const FGeometry& AllottedGeometry, FSlateWindowElementList& OutDrawElements, int32 LayerId) const;

	/** Axis-aligned filled rect via the CoreStyle white brush + tint. */
	static void DrawRect(const FGeometry& Geometry, FSlateWindowElementList& OutDrawElements,
		int32 LayerId, const FVector2D& Pos, const FVector2D& Size, const FLinearColor& Color);

	/** Circle outline via MakeLines (32 segments). */
	static void DrawRing(const FGeometry& Geometry, FSlateWindowElementList& OutDrawElements,
		int32 LayerId, const FVector2D& Center, float Radius, float Thickness, const FLinearColor& Color);

	TSharedPtr<FBossHUDState> State;
};

/**
 * Installs and drives the boss status HUD. Self-installed on the boss actor by
 * UGameFeelSubsystem (never on minions — the subsystem requires a
 * BossActionComponent). Owns the Slate widget lifetime: adds it to the viewport
 * at BeginPlay, removes it at EndPlay, fades it out on OnBossDied and back in
 * when the round reset revives the boss.
 *
 * Survives round resets by construction: it binds component delegates once
 * (the same component instances persist across ResetForNewRound) and re-resolves
 * the hero's CombatComponent lazily each tick if the player pawn changes.
 */
UCLASS(ClassGroup = (UI), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UBossStatusHUDComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UBossStatusHUDComponent();

	/** Name plate text. Placeholder until bosses get real names. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossHUD")
	FText BossDisplayName;

	/** World-space Z offset above the boss actor location used as the "head"
	 *  anchor for the telegraph ring projection. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "BossHUD", meta = (ClampMin = "0.0"))
	float TelegraphWorldZOffset = 90.0f;

	// --- Delegate handlers (dynamic delegates require UFUNCTION) ---

	/** Contract #1: UBossActionComponent::OnBossTelegraph, broadcast from DoAttack
	 *  right after the montage starts. Heavy → red ring for WindupSeconds;
	 *  non-heavy parryable → brief yellow tick. */
	UFUNCTION()
	void HandleBossTelegraph(bool bIsHeavyUnblockable, float WindupSeconds);

	/** Contract #1b: UBossActionComponent::OnBossTelegraphCancelled — the
	 *  telegraphed attack was interrupted mid-wind-up. Clears the ring/banner
	 *  immediately so the player never dodges a phantom attack. */
	UFUNCTION()
	void HandleBossTelegraphCancelled();

	/** Hero CombatComponent::OnAttackLanded → 0.1s border flash (hit-confirm).
	 *  Fires once per landed swing from ANS_DealDamage, so it can't lie. */
	UFUNCTION()
	void HandleHeroAttackLanded(float DamageAmount, FName DamageType);

	/** BossActionComponent::OnBossDied → fade the HUD out. Tick fades it back in
	 *  when the round reset clears IsDead(). */
	UFUNCTION()
	void HandleBossDied();

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	void AddWidgetToViewport();
	void RemoveWidgetFromViewport();

	/** (Re)binds the hero's OnAttackLanded. Safe to call repeatedly — uses
	 *  AddUniqueDynamic and re-resolves if the player pawn was replaced. */
	void TryBindHero();

	void UpdateBars(float DeltaTime);
	void UpdateTelegraph(float DeltaTime);
	void UpdateOpacity(float DeltaTime);

	TSharedPtr<FBossHUDState> State;
	TSharedPtr<SBossStatusWidget> Widget;
	bool bWidgetOnViewport = false;

	// Boss-side components (siblings on the owner).
	TWeakObjectPtr<UCombatComponent> BossCombat;
	TWeakObjectPtr<UHitReactionComponent> BossHitReaction;
	TWeakObjectPtr<UBossActionComponent> BossAction;

	// Hero side, re-resolved lazily.
	TWeakObjectPtr<UCombatComponent> HeroCombat;

	float LastHealthFraction = 1.0f;
	float ChipHoldRemaining = 0.0f;
	float BorderFlashRemaining = 0.0f;
	float TelegraphRemaining = 0.0f;
	float TelegraphDuration = 0.0f;
};
