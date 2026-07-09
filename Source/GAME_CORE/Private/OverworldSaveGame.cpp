#include "OverworldSaveGame.h"

FString UOverworldSaveGame::SlotNameForPlayer(const FString& PlayerId)
{
	// One slot per identity: guest, or per-Firebase-UID for signed-in players.
	// The subsystem always calls with a non-empty string; the empty fallback is
	// a defense against a mis-wired call site.
	return PlayerId.IsEmpty()
		? FString(TEXT("OverworldSaveGame_guest"))
		: FString::Printf(TEXT("OverworldSaveGame_%s"), *PlayerId);
}
