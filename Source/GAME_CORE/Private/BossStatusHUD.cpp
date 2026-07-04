#include "BossStatusHUD.h"

#include "Blueprint/WidgetLayoutLibrary.h"
#include "BossActionComponent.h"
#include "CombatComponent.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Fonts/FontMeasure.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFeelSettings.h"
#include "GameFramework/PlayerController.h"
#include "HitReactionComponent.h"
#include "Kismet/GameplayStatics.h"
#include "Rendering/DrawElements.h"
#include "Styling/CoreStyle.h"

// =====================================================================
// SBossStatusWidget
// =====================================================================

void SBossStatusWidget::Construct(const FArguments& InArgs)
{
	State = InArgs._State;
	// Pure readout — must never eat clicks or focus.
	SetVisibility(EVisibility::HitTestInvisible);
	SetCanTick(false); // all animation state is advanced by the component's tick
}

void SBossStatusWidget::DrawRect(const FGeometry& Geometry, FSlateWindowElementList& OutDrawElements,
	int32 LayerId, const FVector2D& Pos, const FVector2D& Size, const FLinearColor& Color)
{
	if (Color.A <= 0.0f || Size.X <= 0.0f || Size.Y <= 0.0f) return;

	FSlateDrawElement::MakeBox(
		OutDrawElements,
		LayerId,
		Geometry.ToPaintGeometry(FVector2f(Size), FSlateLayoutTransform(FVector2f(Pos))),
		FCoreStyle::Get().GetBrush("WhiteBrush"),
		ESlateDrawEffect::None,
		Color);
}

void SBossStatusWidget::DrawRing(const FGeometry& Geometry, FSlateWindowElementList& OutDrawElements,
	int32 LayerId, const FVector2D& Center, float Radius, float Thickness, const FLinearColor& Color)
{
	if (Color.A <= 0.0f || Radius <= 1.0f) return;

	constexpr int32 NumSegments = 32;
	TArray<FVector2f> Points;
	Points.Reserve(NumSegments + 1);
	for (int32 i = 0; i <= NumSegments; ++i)
	{
		const float Angle = (2.0f * PI * i) / NumSegments;
		Points.Add(FVector2f(
			Center.X + Radius * FMath::Cos(Angle),
			Center.Y + Radius * FMath::Sin(Angle)));
	}

	FSlateDrawElement::MakeLines(
		OutDrawElements,
		LayerId,
		Geometry.ToPaintGeometry(),
		Points,
		ESlateDrawEffect::None,
		Color,
		/*bAntialias=*/true,
		Thickness);
}

int32 SBossStatusWidget::OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry,
	const FSlateRect& MyCullingRect, FSlateWindowElementList& OutDrawElements,
	int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const
{
	if (!State.IsValid() || State->WidgetOpacity <= KINDA_SMALL_NUMBER)
	{
		// Telegraphs still matter while the bar itself is faded (opacity gates the
		// bar only when fully invisible AND no telegraph is live).
		if (!State.IsValid() || !State->bTelegraphActive)
		{
			return LayerId;
		}
	}

	int32 MaxLayer = PaintBossBars(AllottedGeometry, OutDrawElements, LayerId);
	MaxLayer = PaintTelegraph(AllottedGeometry, OutDrawElements, MaxLayer + 1);
	return MaxLayer;
}

int32 SBossStatusWidget::PaintBossBars(const FGeometry& AllottedGeometry,
	FSlateWindowElementList& OutDrawElements, int32 LayerId) const
{
	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();
	const float Opacity = State->WidgetOpacity;
	if (Opacity <= KINDA_SMALL_NUMBER) return LayerId;

	const FVector2D Size = AllottedGeometry.GetLocalSize();
	const float BarW = Size.X * Settings->BossBarWidthFraction;
	const float BarH = FMath::Max(10.0f, Size.Y * 0.012f); // research: ~1% of screen height
	const float BarX = (Size.X - BarW) * 0.5f;

	// --- Name plate (centered above the bar, soft shadow, no box) ---
	const FSlateFontInfo NameFont = FCoreStyle::GetDefaultFontStyle("Bold", 22);
	const TSharedRef<FSlateFontMeasure> FontMeasure = FSlateApplication::Get().GetRenderer()->GetFontMeasureService();
	const FVector2D NameSize = FontMeasure->Measure(State->BossName, NameFont);
	const FVector2D NamePos((Size.X - NameSize.X) * 0.5f, Settings->BossBarTopPadding);

	FSlateDrawElement::MakeText(
		OutDrawElements, LayerId,
		AllottedGeometry.ToPaintGeometry(FVector2f(NameSize), FSlateLayoutTransform(FVector2f(NamePos + FVector2D(1.0, 2.0)))),
		State->BossName, NameFont, ESlateDrawEffect::None,
		FLinearColor(0.0f, 0.0f, 0.0f, 0.6f * Opacity)); // shadow pass
	FSlateDrawElement::MakeText(
		OutDrawElements, LayerId + 1,
		AllottedGeometry.ToPaintGeometry(FVector2f(NameSize), FSlateLayoutTransform(FVector2f(NamePos))),
		State->BossName, NameFont, ESlateDrawEffect::None,
		FLinearColor(0.93f, 0.91f, 0.86f, Opacity)); // ivory

	const float BarY = Settings->BossBarTopPadding + NameSize.Y + 6.0f;

	// --- Hit-confirm border flash (behind everything, expanded 3px) ---
	if (State->BorderFlashAlpha > 0.0f)
	{
		FLinearColor Flash = Settings->HitConfirmFlashColor;
		Flash.A *= State->BorderFlashAlpha * Opacity;
		DrawRect(AllottedGeometry, OutDrawElements, LayerId + 2,
			FVector2D(BarX - 3.0f, BarY - 3.0f), FVector2D(BarW + 6.0f, BarH + 6.0f), Flash);
	}

	// --- Backplate (near-black, 1px border feel via 2px expansion) ---
	DrawRect(AllottedGeometry, OutDrawElements, LayerId + 3,
		FVector2D(BarX - 2.0f, BarY - 2.0f), FVector2D(BarW + 4.0f, BarH + 4.0f),
		FLinearColor(0.01f, 0.01f, 0.012f, 0.75f * Opacity));

	// --- Damage chip (ghost bar at the pre-hit value, drains after the hold) ---
	{
		FLinearColor Chip = Settings->BossBarChipColor;
		Chip.A *= Opacity;
		DrawRect(AllottedGeometry, OutDrawElements, LayerId + 4,
			FVector2D(BarX, BarY), FVector2D(BarW * FMath::Clamp(State->ChipFraction, 0.0f, 1.0f), BarH), Chip);
	}

	// --- Main HP fill (snaps instantly to the new value) ---
	{
		FLinearColor Fill = Settings->BossBarHealthColor;
		Fill.A *= Opacity;
		const float FillW = BarW * FMath::Clamp(State->HealthFraction, 0.0f, 1.0f);
		DrawRect(AllottedGeometry, OutDrawElements, LayerId + 5,
			FVector2D(BarX, BarY), FVector2D(FillW, BarH), Fill);

		// Thin highlight line along the top edge of the fill.
		DrawRect(AllottedGeometry, OutDrawElements, LayerId + 6,
			FVector2D(BarX, BarY), FVector2D(FillW, 1.0f),
			FLinearColor(1.0f, 1.0f, 1.0f, 0.15f * Opacity));
	}

	// --- Stagger/poise meter (GoW white stun bar under the HP bar) ---
	{
		const float StaggerH = BarH * 0.5f;
		const float StaggerY = BarY + BarH + 4.0f;

		DrawRect(AllottedGeometry, OutDrawElements, LayerId + 3,
			FVector2D(BarX - 2.0f, StaggerY - 2.0f), FVector2D(BarW + 4.0f, StaggerH + 4.0f),
			FLinearColor(0.01f, 0.01f, 0.012f, 0.6f * Opacity));

		FLinearColor Stagger = Settings->StaggerBarColor;
		const float StaggerFrac = FMath::Clamp(State->StaggerFraction, 0.0f, 1.0f);
		if (StaggerFrac >= 1.0f - KINDA_SMALL_NUMBER)
		{
			// Full = stagger imminent: pulse toward white so it reads as a prompt.
			const float Pulse = 0.5f + 0.5f * FMath::Abs(FMath::Sin(State->TimeSeconds * 12.0f));
			Stagger = FMath::Lerp(Stagger, FLinearColor::White, Pulse);
		}
		Stagger.A *= Opacity;
		DrawRect(AllottedGeometry, OutDrawElements, LayerId + 4,
			FVector2D(BarX, StaggerY), FVector2D(BarW * StaggerFrac, StaggerH), Stagger);
	}

	return LayerId + 6;
}

int32 SBossStatusWidget::PaintTelegraph(const FGeometry& AllottedGeometry,
	FSlateWindowElementList& OutDrawElements, int32 LayerId) const
{
	if (!State->bTelegraphActive) return LayerId;

	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();
	const FVector2D Size = AllottedGeometry.GetLocalSize();

	// Pulse once at appearance, keep breathing through the wind-up (research:
	// ring pulses at anticipation start; steady but alive afterwards).
	const float Pulse = State->bTelegraphHeavy
		? 0.55f + 0.45f * FMath::Abs(FMath::Sin(State->TelegraphElapsed * 8.0f))
		: 1.0f;

	FLinearColor RingColor = State->TelegraphColor;
	RingColor.A *= Pulse;

	if (State->bBossOnScreen)
	{
		// Ring anchored to the boss's body (research: body-centered, ~1-1.5x
		// character width — never the weapon). Shrinks slightly as impact nears.
		const float BaseRadius = State->bTelegraphHeavy ? 70.0f : 45.0f;
		const float Radius = BaseRadius * (0.75f + 0.25f * FMath::Clamp(State->TelegraphRemainingFraction, 0.0f, 1.0f));

		DrawRing(AllottedGeometry, OutDrawElements, LayerId, State->BossScreenPos, Radius, 5.0f, RingColor);

		if (State->bTelegraphHeavy)
		{
			// Outer bloom ring (GoW spec bloom #FF7A5C for red).
			FLinearColor Bloom(FColor(0xFF, 0x7A, 0x5C));
			Bloom.A = 0.45f * Pulse;
			DrawRing(AllottedGeometry, OutDrawElements, LayerId, State->BossScreenPos, Radius + 9.0f, 3.0f, Bloom);
		}
		return LayerId + 1;
	}

	// Off-screen fallback: top-center banner under the boss bar (off-screen
	// threats must still telegraph — guide 5.3's courtesy rule, HUD flavor).
	const FVector2D BannerSize(300.0f, 30.0f);
	const FVector2D BannerPos((Size.X - BannerSize.X) * 0.5f, Settings->BossBarTopPadding + 90.0f);

	FLinearColor BannerFill = State->TelegraphColor;
	BannerFill.A *= 0.85f * Pulse;
	DrawRect(AllottedGeometry, OutDrawElements, LayerId, BannerPos, BannerSize, BannerFill);

	const FText BannerText = State->bTelegraphHeavy
		? NSLOCTEXT("BossHUD", "UnblockableBanner", "UNBLOCKABLE")
		: NSLOCTEXT("BossHUD", "ParryBanner", "PARRY");
	const FSlateFontInfo BannerFont = FCoreStyle::GetDefaultFontStyle("Bold", 16);
	const TSharedRef<FSlateFontMeasure> FontMeasure = FSlateApplication::Get().GetRenderer()->GetFontMeasureService();
	const FVector2D TextSize = FontMeasure->Measure(BannerText, BannerFont);
	const FVector2D TextPos(BannerPos.X + (BannerSize.X - TextSize.X) * 0.5f,
		BannerPos.Y + (BannerSize.Y - TextSize.Y) * 0.5f);

	FSlateDrawElement::MakeText(
		OutDrawElements, LayerId + 1,
		AllottedGeometry.ToPaintGeometry(FVector2f(TextSize), FSlateLayoutTransform(FVector2f(TextPos))),
		BannerText, BannerFont, ESlateDrawEffect::None,
		FLinearColor(1.0f, 1.0f, 1.0f, Pulse));

	return LayerId + 1;
}

// =====================================================================
// UBossStatusHUDComponent
// =====================================================================

UBossStatusHUDComponent::UBossStatusHUDComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	BossDisplayName = NSLOCTEXT("BossHUD", "DefaultBossName", "BOSS");
}

void UBossStatusHUDComponent::BeginPlay()
{
	Super::BeginPlay();

	AActor* Owner = GetOwner();
	if (!Owner) return;

	// Sibling lookups — the project-wide FindComponentByClass convention.
	BossCombat = Owner->FindComponentByClass<UCombatComponent>();
	BossHitReaction = Owner->FindComponentByClass<UHitReactionComponent>();
	BossAction = Owner->FindComponentByClass<UBossActionComponent>();

	State = MakeShared<FBossHUDState>();
	State->BossName = BossDisplayName;
	if (BossCombat.IsValid() && BossCombat->MaxHealth > 0.0f)
	{
		LastHealthFraction = FMath::Clamp(BossCombat->CurrentHealth / BossCombat->MaxHealth, 0.0f, 1.0f);
		State->HealthFraction = LastHealthFraction;
		State->ChipFraction = LastHealthFraction;
	}

	if (BossAction.IsValid())
	{
		// Contract #1 — Track A broadcasts this from DoAttack right after the
		// montage starts. Delegates live on component instances that survive
		// round resets, so a single bind here covers every round.
		BossAction->OnBossTelegraph.AddUniqueDynamic(this, &UBossStatusHUDComponent::HandleBossTelegraph);
		BossAction->OnBossTelegraphCancelled.AddUniqueDynamic(this, &UBossStatusHUDComponent::HandleBossTelegraphCancelled);
		BossAction->OnBossDied.AddUniqueDynamic(this, &UBossStatusHUDComponent::HandleBossDied);
	}

	TryBindHero();
	AddWidgetToViewport();
}

void UBossStatusHUDComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (BossAction.IsValid())
	{
		BossAction->OnBossTelegraph.RemoveDynamic(this, &UBossStatusHUDComponent::HandleBossTelegraph);
		BossAction->OnBossTelegraphCancelled.RemoveDynamic(this, &UBossStatusHUDComponent::HandleBossTelegraphCancelled);
		BossAction->OnBossDied.RemoveDynamic(this, &UBossStatusHUDComponent::HandleBossDied);
	}
	if (HeroCombat.IsValid())
	{
		HeroCombat->OnAttackLanded.RemoveDynamic(this, &UBossStatusHUDComponent::HandleHeroAttackLanded);
	}
	RemoveWidgetFromViewport();

	Super::EndPlay(EndPlayReason);
}

void UBossStatusHUDComponent::AddWidgetToViewport()
{
	if (bWidgetOnViewport || !State.IsValid()) return;
	if (!GEngine || !GEngine->GameViewport) return; // no viewport yet (or headless) — tick retries

	Widget = SNew(SBossStatusWidget).State(State);
	GEngine->GameViewport->AddViewportWidgetContent(Widget.ToSharedRef(), /*ZOrder=*/10);
	bWidgetOnViewport = true;
}

void UBossStatusHUDComponent::RemoveWidgetFromViewport()
{
	if (bWidgetOnViewport && Widget.IsValid() && GEngine && GEngine->GameViewport)
	{
		GEngine->GameViewport->RemoveViewportWidgetContent(Widget.ToSharedRef());
	}
	bWidgetOnViewport = false;
	Widget.Reset();
}

void UBossStatusHUDComponent::TryBindHero()
{
	APawn* HeroPawn = UGameplayStatics::GetPlayerPawn(this, 0);
	UCombatComponent* Combat = HeroPawn ? HeroPawn->FindComponentByClass<UCombatComponent>() : nullptr;
	if (!Combat) return;

	if (HeroCombat.Get() != Combat)
	{
		// Player pawn changed (respawn/possession swap): drop the stale bind first.
		if (HeroCombat.IsValid())
		{
			HeroCombat->OnAttackLanded.RemoveDynamic(this, &UBossStatusHUDComponent::HandleHeroAttackLanded);
		}
		HeroCombat = Combat;
	}
	// AddUniqueDynamic makes repeated calls harmless.
	Combat->OnAttackLanded.AddUniqueDynamic(this, &UBossStatusHUDComponent::HandleHeroAttackLanded);
}

void UBossStatusHUDComponent::HandleBossTelegraph(bool bIsHeavyUnblockable, float WindupSeconds)
{
	if (!State.IsValid()) return;

	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();

	// GoW color language: red = you must move (dodge only); yellow = parryable.
	// The yellow tick is deliberately brief — it is a rhythm cue, not a countdown.
	TelegraphDuration = bIsHeavyUnblockable
		? FMath::Max(WindupSeconds, 0.05f)
		: Settings->TelegraphParryTickSeconds;
	TelegraphRemaining = TelegraphDuration;

	State->bTelegraphHeavy = bIsHeavyUnblockable;
	State->TelegraphColor = bIsHeavyUnblockable ? Settings->TelegraphUnblockableColor : Settings->TelegraphParryColor;
	State->TelegraphElapsed = 0.0f;
	State->bTelegraphActive = true;
	State->TelegraphRemainingFraction = 1.0f;
}

void UBossStatusHUDComponent::HandleBossTelegraphCancelled()
{
	// Contract #1b: the wind-up was interrupted — the attack is dead. Kill the
	// indicator NOW; letting the ring keep shrinking toward a phantom impact
	// teaches the player to ignore telegraphs (anti-GoW-honesty).
	TelegraphRemaining = 0.0f;
	if (State.IsValid())
	{
		State->bTelegraphActive = false;
	}
}

void UBossStatusHUDComponent::HandleHeroAttackLanded(float DamageAmount, FName DamageType)
{
	BorderFlashRemaining = GetDefault<UGameFeelSettings>()->HitConfirmFlashSeconds;
}

void UBossStatusHUDComponent::HandleBossDied()
{
	// Opacity target flips to 0 in UpdateOpacity via IsDead(); the explicit
	// handler exists so the fade also starts if death routes only through
	// BossActionComponent::HandleDeath. Cancel any live telegraph immediately.
	TelegraphRemaining = 0.0f;
	if (State.IsValid())
	{
		State->bTelegraphActive = false;
	}
}

void UBossStatusHUDComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	if (!State.IsValid()) return;

	AddWidgetToViewport(); // no-op once added; covers a late-created viewport
	TryBindHero();         // no-op once bound; covers pawn swaps and late spawn

	State->TimeSeconds = GetWorld() ? GetWorld()->GetTimeSeconds() : 0.0f;
	State->BossName = BossDisplayName;

	// This component lives ON the boss actor, and component tick DeltaTime is
	// scaled by the owner's CustomTimeDilation — which HitFeedbackComponent drops
	// to ~0.01 for the hit-stop on EVERY landed hero hit, i.e. exactly when the
	// flash/chip timers are armed. Undo the dilation for HUD timers so the
	// hit-confirm flash and chip-hold run on real time (they were stretching ~2x
	// per hit and desyncing from the undilated on-paint pulses). The telegraph
	// deliberately KEEPS the dilated delta: the boss's attack montage freezes
	// through the same hit-stop, so a dilated countdown stays honest to impact.
	const AActor* Owner = GetOwner();
	const float OwnerDilation = Owner ? FMath::Max(Owner->CustomTimeDilation, 0.01f) : 1.0f;
	const float RealDeltaTime = DeltaTime / OwnerDilation;

	UpdateBars(RealDeltaTime);
	UpdateTelegraph(DeltaTime);
	UpdateOpacity(RealDeltaTime);
}

void UBossStatusHUDComponent::UpdateBars(float DeltaTime)
{
	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();

	// --- HP + damage chip ---
	if (BossCombat.IsValid() && BossCombat->MaxHealth > 0.0f)
	{
		const float Fraction = FMath::Clamp(BossCombat->CurrentHealth / BossCombat->MaxHealth, 0.0f, 1.0f);

		if (Fraction < LastHealthFraction - KINDA_SMALL_NUMBER)
		{
			// Damage: main fill snaps down, chip stays at the pre-combo value and
			// the hold timer RESETS on each hit so a combo accumulates one big
			// chip segment (the payoff visual).
			State->ChipFraction = FMath::Max(State->ChipFraction, LastHealthFraction);
			ChipHoldRemaining = Settings->BossBarChipDelay;
		}
		else if (Fraction > LastHealthFraction + KINDA_SMALL_NUMBER)
		{
			// Heal / round reset: snap everything, no chip theatrics.
			State->ChipFraction = Fraction;
			ChipHoldRemaining = 0.0f;
		}

		State->HealthFraction = Fraction;
		LastHealthFraction = Fraction;

		if (ChipHoldRemaining > 0.0f)
		{
			ChipHoldRemaining -= DeltaTime;
		}
		else if (State->ChipFraction > State->HealthFraction)
		{
			State->ChipFraction = FMath::Max(State->HealthFraction,
				State->ChipFraction - Settings->BossBarChipDrainPerSecond * DeltaTime);
		}
	}

	// --- Stagger/poise (decays inside HitReactionComponent; honest per-tick read) ---
	if (BossHitReaction.IsValid() && BossHitReaction->HeavyStaggerThreshold > 0.0f)
	{
		State->StaggerFraction = FMath::Clamp(
			BossHitReaction->GetCurrentStagger() / BossHitReaction->HeavyStaggerThreshold, 0.0f, 1.0f);
	}

	// --- Hit-confirm border flash ---
	if (BorderFlashRemaining > 0.0f)
	{
		BorderFlashRemaining -= DeltaTime;
	}
	State->BorderFlashAlpha = Settings->HitConfirmFlashSeconds > 0.0f
		? FMath::Clamp(BorderFlashRemaining / Settings->HitConfirmFlashSeconds, 0.0f, 1.0f)
		: 0.0f;
}

void UBossStatusHUDComponent::UpdateTelegraph(float DeltaTime)
{
	if (TelegraphRemaining <= 0.0f)
	{
		State->bTelegraphActive = false;
		return;
	}

	TelegraphRemaining -= DeltaTime;
	State->TelegraphElapsed += DeltaTime;
	State->TelegraphRemainingFraction = TelegraphDuration > 0.0f
		? FMath::Clamp(TelegraphRemaining / TelegraphDuration, 0.0f, 1.0f)
		: 0.0f;
	State->bTelegraphActive = TelegraphRemaining > 0.0f;

	// Project the boss's head to screen for the ring anchor. Fallback: banner.
	State->bBossOnScreen = false;
	APlayerController* PC = UGameplayStatics::GetPlayerController(this, 0);
	AActor* Owner = GetOwner();
	if (PC && Owner && GEngine && GEngine->GameViewport)
	{
		const FVector HeadPos = Owner->GetActorLocation() + FVector(0.0f, 0.0f, TelegraphWorldZOffset);
		FVector2D ScreenPos;
		if (PC->ProjectWorldLocationToScreen(HeadPos, ScreenPos, /*bPlayerViewportRelative=*/true))
		{
			FVector2D ViewportSize;
			GEngine->GameViewport->GetViewportSize(ViewportSize);
			if (ScreenPos.X >= 0.0f && ScreenPos.Y >= 0.0f &&
				ScreenPos.X <= ViewportSize.X && ScreenPos.Y <= ViewportSize.Y)
			{
				// Projection is in viewport pixels; OnPaint works in DPI-scaled
				// slate units — divide by the viewport scale to line them up.
				const float Scale = FMath::Max(UWidgetLayoutLibrary::GetViewportScale(this), KINDA_SMALL_NUMBER);
				State->BossScreenPos = ScreenPos / Scale;
				State->bBossOnScreen = true;
			}
		}
	}
}

void UBossStatusHUDComponent::UpdateOpacity(float DeltaTime)
{
	// Fade out while the boss is dead, back in when the round reset revives it.
	// Polling IsDead() (rather than trusting the death delegate alone) is what
	// makes the HUD survive round resets with zero rebinding.
	const bool bBossDead = BossCombat.IsValid() ? BossCombat->IsDead() : false;
	const float Target = bBossDead ? 0.0f : 1.0f;
	State->WidgetOpacity = FMath::FInterpTo(State->WidgetOpacity, Target, DeltaTime, 3.0f);
}
