#include "BossStatusHUD.h"

#include "Blueprint/WidgetLayoutLibrary.h"
#include "BossActionComponent.h"
#include "BossExplainabilityComponent.h"
#include "CombatComponent.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Fonts/FontMeasure.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFeelSettings.h"
#include "GameFramework/PlayerController.h"
#include "HitReactionComponent.h"
#include "Kismet/GameplayStatics.h"
#include "NNEBossPolicyComponent.h"
#include "PlayerProfileComponent.h"
#include "Rendering/DrawElements.h"
#include "Styling/CoreStyle.h"

namespace
{
	// EBossAction display labels for the mask row.
	static const TCHAR* kActionShortLabels[5] = { TEXT("ATK"), TEXT("BLK"), TEXT("DGE"), TEXT("APP"), TEXT("RET") };
	static const TCHAR* kProfileDimLabels[8] = {
		TEXT("Agg"), TEXT("Dge"), TEXT("Blk"), TEXT("Opn"),
		TEXT("Prs"), TEXT("Kit"), TEXT("Cmb"), TEXT("Pos"),
	};
}

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
	if (State->bShowRL)
	{
		MaxLayer = PaintRLShowcase(AllottedGeometry, OutDrawElements, MaxLayer + 1);
	}
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

// ---------------------------------------------------------------------
// RL-visibility panels (only walked when state->bShowRL). Each panel is
// independent — one draws in a corner and returns; the caller collects the
// max LayerId across them. Every panel reads only from FBossHUDRLState.
// ---------------------------------------------------------------------

int32 SBossStatusWidget::PaintRLShowcase(const FGeometry& AllottedGeometry,
	FSlateWindowElementList& OutDrawElements, int32 LayerId) const
{
	int32 MaxLayer = PaintBrainBadge(AllottedGeometry, OutDrawElements, LayerId);
	MaxLayer = FMath::Max(MaxLayer, PaintActionMask(AllottedGeometry, OutDrawElements, LayerId));
	MaxLayer = FMath::Max(MaxLayer, PaintProfileRadar(AllottedGeometry, OutDrawElements, LayerId));
	MaxLayer = FMath::Max(MaxLayer, PaintTauntFade(AllottedGeometry, OutDrawElements, LayerId));
	return MaxLayer;
}

int32 SBossStatusWidget::PaintBrainBadge(const FGeometry& AllottedGeometry,
	FSlateWindowElementList& OutDrawElements, int32 LayerId) const
{
	const FVector2D Size = AllottedGeometry.GetLocalSize();
	const FVector2D Origin(24.0f, 24.0f);
	const FVector2D BadgeSize(230.0f, 56.0f);
	const float Opacity = State->WidgetOpacity;
	if (Opacity <= KINDA_SMALL_NUMBER) return LayerId;

	DrawRect(AllottedGeometry, OutDrawElements, LayerId,
		Origin, BadgeSize,
		FLinearColor(0.02f, 0.02f, 0.025f, 0.62f * Opacity));

	const FString PersonaStr = State->RL.Persona.IsNone()
		? FString(TEXT("<default>"))
		: State->RL.Persona.ToString().ToUpper();
	const FString HeaderStr = FString::Printf(TEXT("BRAIN  %s"), *PersonaStr);
	const FString ConfStr = FString::Printf(TEXT("match  %.2f"), State->RL.PersonaConfidence);

	const FSlateFontInfo HeaderFont = FCoreStyle::GetDefaultFontStyle("Bold", 14);
	const FSlateFontInfo BodyFont   = FCoreStyle::GetDefaultFontStyle("Regular", 12);

	FSlateDrawElement::MakeText(
		OutDrawElements, LayerId + 1,
		AllottedGeometry.ToPaintGeometry(FVector2f(BadgeSize), FSlateLayoutTransform(FVector2f(Origin + FVector2D(12.0f, 6.0f)))),
		FText::FromString(HeaderStr), HeaderFont, ESlateDrawEffect::None,
		FLinearColor(1.0f, 0.86f, 0.42f, Opacity));   // gold
	FSlateDrawElement::MakeText(
		OutDrawElements, LayerId + 1,
		AllottedGeometry.ToPaintGeometry(FVector2f(BadgeSize), FSlateLayoutTransform(FVector2f(Origin + FVector2D(12.0f, 28.0f)))),
		FText::FromString(ConfStr), BodyFont, ESlateDrawEffect::None,
		FLinearColor(0.85f, 0.85f, 0.90f, Opacity));

	// Confidence bar bottom edge (0..1 in [-1,1]/2+0.5 mapping)
	const float Norm = FMath::Clamp(0.5f + 0.5f * State->RL.PersonaConfidence, 0.0f, 1.0f);
	DrawRect(AllottedGeometry, OutDrawElements, LayerId + 1,
		Origin + FVector2D(0.0f, BadgeSize.Y - 3.0f), FVector2D(BadgeSize.X * Norm, 3.0f),
		FLinearColor(1.0f, 0.72f, 0.20f, Opacity));

	return LayerId + 2;
}

int32 SBossStatusWidget::PaintActionMask(const FGeometry& AllottedGeometry,
	FSlateWindowElementList& OutDrawElements, int32 LayerId) const
{
	const FVector2D Size = AllottedGeometry.GetLocalSize();
	const float Opacity = State->WidgetOpacity;
	if (Opacity <= KINDA_SMALL_NUMBER) return LayerId;

	constexpr float CellW = 60.0f;
	constexpr float CellH = 30.0f;
	constexpr float Gap   = 6.0f;
	const int32 N = FMath::Min<int32>(State->RL.LegalMask.Num(), 5);

	const float TotalW = N * CellW + FMath::Max(0, N - 1) * Gap;
	const FVector2D Origin(Size.X - TotalW - 24.0f, 24.0f);

	const FSlateFontInfo CellFont = FCoreStyle::GetDefaultFontStyle("Bold", 12);
	const TSharedRef<FSlateFontMeasure> FontMeasure = FSlateApplication::Get().GetRenderer()->GetFontMeasureService();

	for (int32 i = 0; i < N; ++i)
	{
		const bool bLegal = State->RL.LegalMask[i];
		const bool bChosen = (State->RL.ChosenAction == i);
		const FVector2D CellPos(Origin.X + i * (CellW + Gap), Origin.Y);
		const FLinearColor Fill = bLegal
			? (bChosen ? FLinearColor(1.0f, 0.72f, 0.20f, 0.85f * Opacity)      // gold — chosen
			           : FLinearColor(0.08f, 0.09f, 0.12f, 0.75f * Opacity))    // dark — legal
			:               FLinearColor(0.02f, 0.02f, 0.025f, 0.5f * Opacity); // faded — masked
		DrawRect(AllottedGeometry, OutDrawElements, LayerId, CellPos, FVector2D(CellW, CellH), Fill);
		// Top edge highlight when chosen
		if (bChosen)
		{
			DrawRect(AllottedGeometry, OutDrawElements, LayerId + 1,
				CellPos, FVector2D(CellW, 2.0f),
				FLinearColor(1.0f, 0.95f, 0.75f, Opacity));
		}
		const FText Label = FText::FromString(kActionShortLabels[i]);
		const FVector2D LabelSize = FontMeasure->Measure(Label, CellFont);
		const FVector2D LabelPos(CellPos.X + (CellW - LabelSize.X) * 0.5f, CellPos.Y + (CellH - LabelSize.Y) * 0.5f);
		FSlateDrawElement::MakeText(
			OutDrawElements, LayerId + 2,
			AllottedGeometry.ToPaintGeometry(FVector2f(LabelSize), FSlateLayoutTransform(FVector2f(LabelPos))),
			Label, CellFont, ESlateDrawEffect::None,
			bLegal ? FLinearColor(0.95f, 0.95f, 0.95f, Opacity)
			       : FLinearColor(0.45f, 0.45f, 0.48f, Opacity));
	}
	return LayerId + 2;
}

int32 SBossStatusWidget::PaintProfileRadar(const FGeometry& AllottedGeometry,
	FSlateWindowElementList& OutDrawElements, int32 LayerId) const
{
	const FVector2D Size = AllottedGeometry.GetLocalSize();
	const float Opacity = State->WidgetOpacity;
	if (Opacity <= KINDA_SMALL_NUMBER) return LayerId;

	const int32 N = FMath::Min<int32>(State->RL.PlayerProfile.Num(), 8);
	if (N <= 2) return LayerId;

	constexpr float Radius = 76.0f;
	const FVector2D Center(24.0f + Radius, Size.Y - 24.0f - Radius);

	// Background disk + gridlines (3 concentric rings at 0.33 / 0.66 / 1.0).
	for (float Frac : { 1.0f, 0.66f, 0.33f })
	{
		DrawRing(AllottedGeometry, OutDrawElements, LayerId,
			Center, Radius * Frac, 1.0f,
			FLinearColor(0.4f, 0.4f, 0.45f, 0.35f * Opacity));
	}

	// Spoke lines
	for (int32 i = 0; i < N; ++i)
	{
		const float Angle = 2.0f * PI * i / N - PI * 0.5f;
		TArray<FVector2f> Spoke;
		Spoke.Reserve(2);
		Spoke.Add(FVector2f(Center.X, Center.Y));
		Spoke.Add(FVector2f(Center.X + Radius * FMath::Cos(Angle),
		                    Center.Y + Radius * FMath::Sin(Angle)));
		FSlateDrawElement::MakeLines(
			OutDrawElements, LayerId,
			AllottedGeometry.ToPaintGeometry(),
			Spoke, ESlateDrawEffect::None,
			FLinearColor(0.4f, 0.4f, 0.45f, 0.3f * Opacity),
			true, 1.0f);
	}

	// Filled profile polygon (values live in [0,1]; 0.5 = neutral).
	TArray<FVector2f> Poly;
	Poly.Reserve(N + 1);
	for (int32 i = 0; i < N; ++i)
	{
		const float V = FMath::Clamp(State->RL.PlayerProfile[i], 0.0f, 1.0f);
		const float Angle = 2.0f * PI * i / N - PI * 0.5f;
		Poly.Add(FVector2f(Center.X + Radius * V * FMath::Cos(Angle),
		                   Center.Y + Radius * V * FMath::Sin(Angle)));
	}
	Poly.Add(Poly[0]);
	FSlateDrawElement::MakeLines(
		OutDrawElements, LayerId + 1,
		AllottedGeometry.ToPaintGeometry(),
		Poly, ESlateDrawEffect::None,
		FLinearColor(1.0f, 0.72f, 0.20f, 0.95f * Opacity), true, 2.0f);

	// Dim labels around the rim
	const FSlateFontInfo LabelFont = FCoreStyle::GetDefaultFontStyle("Regular", 10);
	const TSharedRef<FSlateFontMeasure> FontMeasure = FSlateApplication::Get().GetRenderer()->GetFontMeasureService();
	for (int32 i = 0; i < N; ++i)
	{
		const FText Label = FText::FromString(kProfileDimLabels[i]);
		const FVector2D LabelSize = FontMeasure->Measure(Label, LabelFont);
		const float Angle = 2.0f * PI * i / N - PI * 0.5f;
		const FVector2D LabelPos(
			Center.X + (Radius + 10.0f) * FMath::Cos(Angle) - LabelSize.X * 0.5f,
			Center.Y + (Radius + 10.0f) * FMath::Sin(Angle) - LabelSize.Y * 0.5f);
		FSlateDrawElement::MakeText(
			OutDrawElements, LayerId + 2,
			AllottedGeometry.ToPaintGeometry(FVector2f(LabelSize), FSlateLayoutTransform(FVector2f(LabelPos))),
			Label, LabelFont, ESlateDrawEffect::None,
			FLinearColor(0.75f, 0.75f, 0.80f, 0.9f * Opacity));
	}

	// Header text above the radar
	const FSlateFontInfo HeaderFont = FCoreStyle::GetDefaultFontStyle("Bold", 12);
	const FText Header = FText::FromString(TEXT("PLAYER PROFILE"));
	FSlateDrawElement::MakeText(
		OutDrawElements, LayerId + 2,
		AllottedGeometry.ToPaintGeometry(FVector2f(120.0f, 16.0f), FSlateLayoutTransform(FVector2f(FVector2D(Center.X - 60.0f, Center.Y - Radius - 26.0f)))),
		Header, HeaderFont, ESlateDrawEffect::None,
		FLinearColor(1.0f, 0.86f, 0.42f, Opacity));

	return LayerId + 2;
}

int32 SBossStatusWidget::PaintTauntFade(const FGeometry& AllottedGeometry,
	FSlateWindowElementList& OutDrawElements, int32 LayerId) const
{
	if (State->RL.TauntText.IsEmpty()) return LayerId;
	if (State->RL.TauntDurationSeconds <= 0.0f) return LayerId;
	const float t = FMath::Clamp(State->RL.TauntAgeSeconds / State->RL.TauntDurationSeconds, 0.0f, 1.0f);
	if (t >= 1.0f) return LayerId;

	// Ease: fade-in over first 0.15, hold, fade-out over last 0.35.
	float Alpha = 1.0f;
	if (t < 0.15f) Alpha = t / 0.15f;
	else if (t > 0.65f) Alpha = 1.0f - (t - 0.65f) / 0.35f;
	Alpha = FMath::Clamp(Alpha, 0.0f, 1.0f) * State->WidgetOpacity;
	if (Alpha <= KINDA_SMALL_NUMBER) return LayerId;

	const FVector2D Size = AllottedGeometry.GetLocalSize();
	const FSlateFontInfo Font = FCoreStyle::GetDefaultFontStyle("Italic", 20);
	const TSharedRef<FSlateFontMeasure> FontMeasure = FSlateApplication::Get().GetRenderer()->GetFontMeasureService();
	const FVector2D TextSize = FontMeasure->Measure(State->RL.TauntText, Font);
	const FVector2D Pos(Size.X - TextSize.X - 32.0f, Size.Y * 0.5f - TextSize.Y * 0.5f);

	// Shadow pass
	FSlateDrawElement::MakeText(
		OutDrawElements, LayerId,
		AllottedGeometry.ToPaintGeometry(FVector2f(TextSize), FSlateLayoutTransform(FVector2f(Pos + FVector2D(1.5f, 2.0f)))),
		State->RL.TauntText, Font, ESlateDrawEffect::None,
		FLinearColor(0.0f, 0.0f, 0.0f, 0.6f * Alpha));
	FSlateDrawElement::MakeText(
		OutDrawElements, LayerId + 1,
		AllottedGeometry.ToPaintGeometry(FVector2f(TextSize), FSlateLayoutTransform(FVector2f(Pos))),
		State->RL.TauntText, Font, ESlateDrawEffect::None,
		FLinearColor(1.0f, 0.86f, 0.42f, Alpha));
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

	// RL-visibility peers — resolved even when showcase is off so a runtime
	// arena.Showcase toggle works without having to unregister/reregister.
	BossNNE = Owner->FindComponentByClass<UNNEBossPolicyComponent>();
	BossExplain = Owner->FindComponentByClass<UBossExplainabilityComponent>();

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
	if (bInsightBound && BossExplain.IsValid())
	{
		BossExplain->OnBossInsightGenerated.RemoveDynamic(this, &UBossStatusHUDComponent::HandleBossInsight);
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
	UpdateRLState(RealDeltaTime);
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

void UBossStatusHUDComponent::UpdateRLState(float DeltaTime)
{
	// Cheap read-only mirror — no combat state mutated. Toggle-live: reading the
	// Config bool each tick lets `arena.Showcase 1/0` take effect immediately
	// without unregistering the component.
	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();
	State->bShowRL = Settings && Settings->bEnableRLShowcase;
	if (!State->bShowRL)
	{
		// Age the taunt out on toggle-off so it doesn't reappear at half-fade.
		State->RL.TauntAgeSeconds = 999.0f;
		return;
	}

	// Lazy-bind the insight delegate: we don't want to consume a slot on the
	// explainability component's delegate list in shipping builds where the
	// showcase is off. Bind on first tick where showcase is on.
	if (!bInsightBound && BossExplain.IsValid())
	{
		BossExplain->OnBossInsightGenerated.AddUniqueDynamic(this, &UBossStatusHUDComponent::HandleBossInsight);
		bInsightBound = true;
	}

	// Brain badge — persona + confidence come from the NNE component. When the
	// bridge is driving the boss (training), the NNE component is dormant; the
	// badge falls back to the sensible defaults (persona=None, confidence=0).
	if (BossNNE.IsValid())
	{
		State->RL.Persona = BossNNE->GetSelectedArchetype();
		State->RL.PersonaConfidence = BossNNE->GetSelectionConfidence();
		State->RL.ChosenAction = BossNNE->GetLastChosenAction();
	}
	else
	{
		State->RL.Persona = NAME_None;
		State->RL.PersonaConfidence = 0.0f;
		State->RL.ChosenAction = -1;
	}

	// Action-mask row — always via GetLegalActionMask() so it stays honest
	// during range/facing changes. The mask arriving from BossActionComponent is
	// what the NNE argmax was gated against, so ChosenAction always sits on a
	// legal cell (nothing to reconcile).
	if (BossAction.IsValid())
	{
		State->RL.LegalMask = BossAction->GetLegalActionMask();
		if (State->RL.ChosenAction < 0)
		{
			// NNE hasn't fired yet (bridge mode / model not ready) — read the
			// committed action off BossActionComponent for a live indicator.
			const int32 Committed = static_cast<int32>(BossAction->GetCurrentAction());
			// EBossAction::Count means idle; only surface real actions.
			State->RL.ChosenAction = (Committed >= 0 && Committed < State->RL.LegalMask.Num()) ? Committed : -1;
		}
	}
	else
	{
		State->RL.LegalMask.Reset();
		State->RL.ChosenAction = -1;
	}

	// Player profile radar — resolve the hero-side component lazily; the hero
	// pawn can spawn a beat after the boss.
	if (!HeroProfile.IsValid())
	{
		if (APawn* HeroPawn = UGameplayStatics::GetPlayerPawn(this, 0))
		{
			HeroProfile = HeroPawn->FindComponentByClass<UPlayerProfileComponent>();
		}
	}
	if (HeroProfile.IsValid())
	{
		State->RL.PlayerProfile = HeroProfile->GetProfile().ToFloatArray();
	}
	else
	{
		State->RL.PlayerProfile.Reset();
	}

	// Age the taunt fade counter — the paint side turns age into an ease curve.
	State->RL.TauntAgeSeconds += DeltaTime;
}

void UBossStatusHUDComponent::HandleBossInsight(const FBossInsight& Insight)
{
	if (!State.IsValid()) return;
	State->RL.TauntText = Insight.TauntText;
	State->RL.TauntAgeSeconds = 0.0f;
	// TauntDurationSeconds keeps the 4s default; explainability can be extended
	// later to author a per-insight duration if we need it.
}
