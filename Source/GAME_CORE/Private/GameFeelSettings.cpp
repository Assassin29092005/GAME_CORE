#include "GameFeelSettings.h"

UGameFeelSettings::UGameFeelSettings()
{
	// Shows up under Project Settings → Game → Game Feel.
	CategoryName = TEXT("Game");

	// GoW Ragnarok telegraph canon (research spec). FColor → FLinearColor does the
	// sRGB→linear conversion so the on-screen color matches the hex.
	TelegraphUnblockableColor = FLinearColor(FColor(0xFF, 0x2A, 0x1A)); // red: dodge only
	TelegraphParryColor       = FLinearColor(FColor(0xFF, 0xC4, 0x00)); // yellow: parry/dodge

	// Boss bar palette: dark crimson fill, pale ghost chip, GoW-white stun meter.
	BossBarHealthColor   = FLinearColor(FColor(0x9E, 0x1B, 0x14));
	BossBarChipColor     = FLinearColor(FColor(0xF2, 0xE9, 0xDC));
	StaggerBarColor      = FLinearColor(FColor(0xF5, 0xD7, 0x6E));
	HitConfirmFlashColor = FLinearColor::White;
}
