#include "GameFeelSubsystem.h"

#include "BossActionComponent.h"
#include "BossEncounterVolume.h"
#include "BossStatusHUD.h"
#include "CombatCameraComponent.h"
#include "CombatComponent.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "FirebaseAuthSubsystem.h"
#include "GameFeelSettings.h"
#include "Kismet/GameplayStatics.h"
#include "LockOnComponent.h"
#include "Misc/CommandLine.h"
#include "Misc/DateTime.h"
#include "Misc/Parse.h"
#include "NNEBossPolicyComponent.h"
#include "OverworldSaveGame.h"
#include "PlayerMemoryComponent.h"
#include "PlayerProfileComponent.h"
#include "RLBridgeComponent.h"
#include "TimerManager.h"

bool UGameFeelSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	if (!Super::ShouldCreateSubsystem(Outer)) return false;

	// Game/PIE worlds only — never editor-preview or inactive worlds.
	const UWorld* World = Cast<UWorld>(Outer);
	if (!World || !World->IsGameWorld()) return false;

	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();
	return Settings->bEnableCombatCamera || Settings->bEnableBossStatusHUD || Settings->bEnableNNEBoss;
}

void UGameFeelSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);

	// Retry until the player pawn / boss exist (spawn order at level start is
	// not guaranteed, and training runs spawn the hero a beat late). First
	// attempt fires immediately; the loop is cheap (two tag scans at worst).
	InWorld.GetTimerManager().SetTimer(
		InstallTimerHandle,
		FTimerDelegate::CreateUObject(this, &UGameFeelSubsystem::TryInstall),
		0.25f, /*bLoop=*/true, /*FirstDelay=*/0.0f);
}

AActor* UGameFeelSubsystem::FindBossActor(UWorld* World)
{
	if (!World) return nullptr;

	TArray<AActor*> Tagged;
	UGameplayStatics::GetAllActorsWithTag(World, FName(TEXT("Enemy")), Tagged);
	for (AActor* Actor : Tagged)
	{
		// BossActionComponent is the boss discriminator: minions share the Enemy
		// tag (lock-on needs it) but are BT-driven ACharacters without one.
		if (Actor && Actor->FindComponentByClass<UBossActionComponent>())
		{
			return Actor;
		}
	}
	return nullptr;
}

void UGameFeelSubsystem::SetCameraMode(ECameraMode NewMode)
{
	UWorld* World = GetWorld();
	if (!World) return;

	APawn* HeroPawn = UGameplayStatics::GetPlayerPawn(World, 0);
	if (!HeroPawn) return;

	if (UCombatCameraComponent* CameraComp = HeroPawn->FindComponentByClass<UCombatCameraComponent>())
	{
		CameraComp->SetCameraMode(NewMode);
	}

	// LockOn is a combat behavior; deactivate while exploring so the yaw doesn't
	// snap toward far-away encounter-volume-adjacent minions the moment they
	// enter LockOnRange. Re-activated on Combat mode.
	if (ULockOnComponent* LockOn = HeroPawn->FindComponentByClass<ULockOnComponent>())
	{
		LockOn->SetActive(NewMode == ECameraMode::Combat);
	}
}

void UGameFeelSubsystem::BeginEncounter(ABossEncounterVolume* Volume)
{
	if (!Volume) return;

	UWorld* World = GetWorld();
	if (!World) return;

	// Reject overlap-during-encounter — only one encounter runs at a time. If
	// somehow a second volume fires (level author error, two volumes overlap),
	// the first one owns the fight until it ends.
	if (ActiveEncounter && ActiveEncounter != Volume)
	{
		UE_LOG(LogTemp, Warning, TEXT("GameFeelSubsystem::BeginEncounter: '%s' fired while '%s' is active — ignoring."),
			*Volume->GetName(), *ActiveEncounter->GetName());
		return;
	}
	if (ActiveEncounter == Volume)
	{
		return;  // idempotent
	}
	ActiveEncounter = Volume;

	AActor* Boss = Volume->BossActor.Get();
	if (Boss == nullptr)
	{
		Boss = Volume->BossActor.LoadSynchronous();
	}
	if (!Boss)
	{
		UE_LOG(LogTemp, Warning, TEXT("GameFeelSubsystem::BeginEncounter: volume '%s' has null BossActor."),
			*Volume->GetName());
		ActiveEncounter = nullptr;
		return;
	}

	// Reveal the boss + turn collision on. Level authoring hides these actors on
	// begin-play; this is the mirror.
	Boss->SetActorHiddenInGame(false);
	Boss->SetActorEnableCollision(true);

	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();

	// HUD injection (per-boss, not per-level). Idempotent — FindComponentByClass
	// short-circuits if this boss already carries one from a prior encounter.
	if (Settings->bEnableBossStatusHUD)
	{
		if (!Boss->FindComponentByClass<UBossStatusHUDComponent>())
		{
			UBossStatusHUDComponent* HUDComp =
				NewObject<UBossStatusHUDComponent>(Boss, TEXT("BossStatusHUDComponent"));
			HUDComp->RegisterComponent();
		}
	}

	// Player-memory load (Firebase UID or "guest"). Idempotent within a PlayerId:
	// LoadMemory is a no-op if GetCurrentPlayerId() already matches. Per-encounter
	// call keeps the profile fresh if the previous encounter's RecordEncounterEnd
	// mutated something the archetype resolver reads.
	if (UPlayerMemoryComponent* Memory = Boss->FindComponentByClass<UPlayerMemoryComponent>())
	{
		if (Memory->GetCurrentPlayerId().IsEmpty())
		{
			FString PlayerId = TEXT("guest");
			if (const UGameInstance* GameInstance = World->GetGameInstance())
			{
				if (const UFirebaseAuthSubsystem* Auth = GameInstance->GetSubsystem<UFirebaseAuthSubsystem>())
				{
					if (!Auth->GetUid().IsEmpty())
					{
						PlayerId = Auth->GetUid();
					}
				}
			}
			Memory->LoadMemory(PlayerId);
			UE_LOG(LogTemp, Log, TEXT("GameFeelSubsystem::BeginEncounter: memory loaded for '%s' (%d stored encounters)."),
				*PlayerId, Memory->GetTotalEncounters());
		}
	}

	// NNE policy injection. Per-encounter re-resolution: if the component already
	// exists on the boss from a previous encounter, it re-runs its archetype
	// selection at RegisterComponent's next BeginPlay tick... but that path only
	// fires once. Instead we let the auto-injected fresh component run its resolve
	// on this new install. For a pre-existing NNE component we leave it alone —
	// same brain, same fight. (Post-MVP: add UNNEBossPolicyComponent::Resolve()
	// public reruns when the profile changes materially between encounters.)
	if (Settings->bEnableNNEBoss)
	{
		if (!Boss->FindComponentByClass<UNNEBossPolicyComponent>())
		{
			UNNEBossPolicyComponent* PolicyComp =
				NewObject<UNNEBossPolicyComponent>(Boss, TEXT("NNEBossPolicyComponent"));
			// Volume's fallback persona wins if the archetype cosine match fails
			// (new / guest player). See ResolveModelData precedence in NNE header.
			PolicyComp->SetPreferredPersonaOverride(Volume->PreferredPersonaFallback);
			PolicyComp->RegisterComponent();
		}
	}

	// Bind OnBossDied so the encounter volume knows to end. Multi-bind safe —
	// AddUniqueDynamic short-circuits if already bound.
	if (UBossActionComponent* BossAction = Boss->FindComponentByClass<UBossActionComponent>())
	{
		// Route through the subsystem's HandleBossDied for the RecordRoundEnd
		// side effects (memory save, telemetry). The volume also binds its own
		// listener for the end-encounter flow; both fire.
		BossAction->OnBossDied.AddUniqueDynamic(this, &UGameFeelSubsystem::HandleBossDied);
		BossAction->OnBossDied.AddUniqueDynamic(Volume, &ABossEncounterVolume::OnBossDefeated);
	}

	RoundStartRealSeconds = FPlatformTime::Seconds();
	SetCameraMode(ECameraMode::Combat);

	UE_LOG(LogTemp, Log, TEXT("GameFeelSubsystem::BeginEncounter: '%s' active (persona fallback='%s')."),
		*Volume->EncounterID.ToString(),
		*Volume->PreferredPersonaFallback.ToString());
}

void UGameFeelSubsystem::EndEncounter(ABossEncounterVolume* Volume)
{
	if (!Volume) return;
	if (ActiveEncounter != Volume) return;  // ignore stale end-events

	UWorld* World = GetWorld();
	if (!World)
	{
		ActiveEncounter = nullptr;
		return;
	}

	AActor* Boss = Volume->BossActor.Get();
	const bool bBossDefeated = Boss ? (Boss->FindComponentByClass<UCombatComponent>() ? Boss->FindComponentByClass<UCombatComponent>()->IsDead() : false) : false;

	if (Boss)
	{
		if (UBossActionComponent* BossAction = Boss->FindComponentByClass<UBossActionComponent>())
		{
			BossAction->OnBossDied.RemoveDynamic(Volume, &ABossEncounterVolume::OnBossDefeated);
			// Leave the subsystem's HandleBossDied bound — RecordRoundEnd's
			// debounce handles duplicate fires cleanly.
		}
		// Re-hide the boss if it survived (player retreated) so re-entry gets
		// a clean state. If the boss is dead, its death sequence runs first;
		// respawning is a Phase E save-state decision (defeated stays defeated).
		Boss->SetActorHiddenInGame(true);
		Boss->SetActorEnableCollision(false);
	}

	SetCameraMode(ECameraMode::Exploration);

	// Phase E save-state: on a defeated boss, mark the zone cleared. Player retreat
	// leaves the zone re-enterable (Volume->bAlreadyDefeated stays false).
	if (bBossDefeated && OverworldSave)
	{
		OverworldSave->DefeatedBossZones.Add(Volume->EncounterID);

		FOverworldEncounterRecord Record;
		Record.EncounterID = Volume->EncounterID;
		Record.bBossDefeated = true;
		Record.DurationSeconds = static_cast<float>(FPlatformTime::Seconds() - RoundStartRealSeconds);
		Record.EndUnixSeconds = FDateTime::UtcNow().ToUnixTimestamp();
		if (Boss)
		{
			if (UNNEBossPolicyComponent* Policy = Boss->FindComponentByClass<UNNEBossPolicyComponent>())
			{
				Record.SelectedPersona = Policy->GetSelectedArchetype();
			}
		}
		OverworldSave->EncounterLog.Add(Record);
	}

	// Save on ANY encounter end so the player's last position is captured.
	if (bOverworldMode)
	{
		if (APawn* HeroPawn = UGameplayStatics::GetPlayerPawn(World, 0))
		{
			if (OverworldSave)
			{
				OverworldSave->PlayerLocation = HeroPawn->GetActorLocation();
				if (APlayerController* PC = Cast<APlayerController>(HeroPawn->GetController()))
				{
					OverworldSave->PlayerRotation = PC->GetControlRotation();
				}
			}
		}
		SaveOverworldSave();
	}

	ActiveEncounter = nullptr;

	UE_LOG(LogTemp, Log, TEXT("GameFeelSubsystem::EndEncounter: '%s' released (defeated=%d)."),
		*Volume->EncounterID.ToString(), bBossDefeated ? 1 : 0);
}

void UGameFeelSubsystem::EnsurePlayerIdCached()
{
	if (!CachedPlayerId.IsEmpty()) return;
	CachedPlayerId = TEXT("guest");
	if (UWorld* World = GetWorld())
	{
		if (const UGameInstance* GameInstance = World->GetGameInstance())
		{
			if (const UFirebaseAuthSubsystem* Auth = GameInstance->GetSubsystem<UFirebaseAuthSubsystem>())
			{
				if (!Auth->GetUid().IsEmpty())
				{
					CachedPlayerId = Auth->GetUid();
				}
			}
		}
	}
}

void UGameFeelSubsystem::LoadOverworldSave()
{
	EnsurePlayerIdCached();
	const FString SlotName = UOverworldSaveGame::SlotNameForPlayer(CachedPlayerId);

	if (UGameplayStatics::DoesSaveGameExist(SlotName, UOverworldSaveGame::UserIndex))
	{
		OverworldSave = Cast<UOverworldSaveGame>(
			UGameplayStatics::LoadGameFromSlot(SlotName, UOverworldSaveGame::UserIndex));
	}
	if (!OverworldSave)
	{
		OverworldSave = Cast<UOverworldSaveGame>(
			UGameplayStatics::CreateSaveGameObject(UOverworldSaveGame::StaticClass()));
	}

	if (OverworldSave)
	{
		UE_LOG(LogTemp, Log, TEXT("GameFeelSubsystem: overworld save loaded ('%s', %d defeated zones, %d encounters logged)."),
			*SlotName, OverworldSave->DefeatedBossZones.Num(), OverworldSave->EncounterLog.Num());
	}
}

void UGameFeelSubsystem::SaveOverworldSave()
{
	if (!OverworldSave || CachedPlayerId.IsEmpty()) return;
	OverworldSave->LastSavedUnixSeconds = FDateTime::UtcNow().ToUnixTimestamp();
	const FString SlotName = UOverworldSaveGame::SlotNameForPlayer(CachedPlayerId);
	const bool bOk = UGameplayStatics::SaveGameToSlot(OverworldSave, SlotName, UOverworldSaveGame::UserIndex);
	if (!bOk)
	{
		UE_LOG(LogTemp, Warning, TEXT("GameFeelSubsystem: SaveGameToSlot failed for '%s'."), *SlotName);
	}
}

bool UGameFeelSubsystem::IsEncounterDefeated(FName EncounterID) const
{
	return OverworldSave && OverworldSave->DefeatedBossZones.Contains(EncounterID);
}

void UGameFeelSubsystem::ClearOverworldState()
{
	OverworldSave = nullptr;
	CachedPlayerId.Reset();
}

void UGameFeelSubsystem::TryInstall()
{
	UWorld* World = GetWorld();
	if (!World) return;

	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();

	// Tier 4: if this level uses encounter volumes, disable this subsystem's
	// auto-injection of HUD/NNE/memory-load onto whichever boss it finds first.
	// Those flows are owned per-encounter by ABossEncounterVolume so multiple
	// biome bosses in the same level each get their own installation pass.
	// Detected exactly once — checking every tick would iterate the world.
	if (!bLevelInspected)
	{
		for (TActorIterator<ABossEncounterVolume> It(World); It; ++It)
		{
			bOverworldMode = true;
			break;
		}
		bLevelInspected = true;
		if (bOverworldMode)
		{
			UE_LOG(LogTemp, Log, TEXT("GameFeelSubsystem: overworld mode — encounter volumes own the boss-side install."));
			LoadOverworldSave();
		}
	}

	if (Settings->bEnableCombatCamera && !bCameraInstalled)
	{
		if (APawn* HeroPawn = UGameplayStatics::GetPlayerPawn(World, 0))
		{
			if (!HeroPawn->FindComponentByClass<UCombatCameraComponent>())
			{
				UCombatCameraComponent* CameraComp =
					NewObject<UCombatCameraComponent>(HeroPawn, TEXT("CombatCameraComponent"));
				CameraComp->RegisterComponent();
			}
			// In overworld mode, default the hero to Exploration until an
			// encounter volume promotes to Combat. In arena mode, leave the
			// default Combat (no behavior change vs today).
			if (bOverworldMode)
			{
				if (UCombatCameraComponent* CamComp = HeroPawn->FindComponentByClass<UCombatCameraComponent>())
				{
					CamComp->SetCameraMode(ECameraMode::Exploration);
				}
				if (ULockOnComponent* LockOn = HeroPawn->FindComponentByClass<ULockOnComponent>())
				{
					LockOn->SetActive(false);
				}

				// Restore saved player pos/rot if a save was loaded. Only teleport
				// once per world (bCameraInstalled becomes true on the same tick
				// so this block is one-shot on the first successful install).
				if (OverworldSave)
				{
					HeroPawn->SetActorLocation(OverworldSave->PlayerLocation, /*bSweep=*/false, /*OutSweepHitResult=*/nullptr, ETeleportType::TeleportPhysics);
					if (APlayerController* PC = Cast<APlayerController>(HeroPawn->GetController()))
					{
						PC->SetControlRotation(OverworldSave->PlayerRotation);
					}
					UE_LOG(LogTemp, Log, TEXT("GameFeelSubsystem: restored player pos %s from save."),
						*OverworldSave->PlayerLocation.ToString());
				}
			}
			bCameraInstalled = true;
		}
	}

	// Overworld mode owns the boss-side install; the rest of this function is
	// arena-only. Everything below runs against the FIRST boss found in the
	// world, which is exactly wrong when there are five biome bosses.
	if (bOverworldMode)
	{
		if (bCameraInstalled)
		{
			// Nothing left to poll for; the timer can stop.
			World->GetTimerManager().ClearTimer(InstallTimerHandle);
		}
		return;
	}

	if (Settings->bEnableBossStatusHUD && !bHUDInstalled)
	{
		if (AActor* Boss = FindBossActor(World))
		{
			if (!Boss->FindComponentByClass<UBossStatusHUDComponent>())
			{
				UBossStatusHUDComponent* HUDComp =
					NewObject<UBossStatusHUDComponent>(Boss, TEXT("BossStatusHUDComponent"));
				HUDComp->RegisterComponent();
			}
			bHUDInstalled = true;
		}
	}

	// M5 memory lifecycle, step 1: load the stored player profile onto the boss's
	// PlayerMemoryComponent BEFORE the NNE component exists — its BeginPlay
	// (fired synchronously inside RegisterComponent below) runs the archetype
	// cosine match against exactly this data. Identity: Firebase UID when signed
	// in, "guest" otherwise (guest memory stays local, same as guest telemetry).
	// A bridge-set player id (training) arrives later via set_player_id and
	// simply re-loads over this — bridge outranks NNE there anyway.
	if (!bMemoryLoaded)
	{
		if (AActor* Boss = FindBossActor(World))
		{
			if (UPlayerMemoryComponent* Memory = Boss->FindComponentByClass<UPlayerMemoryComponent>())
			{
				if (Memory->GetCurrentPlayerId().IsEmpty())
				{
					FString PlayerId = TEXT("guest");
					if (const UGameInstance* GameInstance = World->GetGameInstance())
					{
						if (const UFirebaseAuthSubsystem* Auth = GameInstance->GetSubsystem<UFirebaseAuthSubsystem>())
						{
							if (!Auth->GetUid().IsEmpty())
							{
								PlayerId = Auth->GetUid();
							}
						}
					}
					Memory->LoadMemory(PlayerId);
					UE_LOG(LogTemp, Log, TEXT("GameFeelSubsystem: player memory loaded for '%s' (%d stored encounters)."),
						*PlayerId, Memory->GetTotalEncounters());
				}
				if (UBossActionComponent* BossAction = Boss->FindComponentByClass<UBossActionComponent>())
				{
					BossAction->OnBossDied.AddUniqueDynamic(this, &UGameFeelSubsystem::HandleBossDied);
				}
			}
			// Boss without a memory component: nothing to manage — done either way.
			RoundStartRealSeconds = FPlatformTime::Seconds();
			bMemoryLoaded = true;
		}
	}

	// M5 memory lifecycle, step 2: the hero side of the round-end signal (the
	// hero can spawn a beat later than the boss, hence the separate flag).
	if (!bHeroDeathBound)
	{
		if (APawn* HeroPawn = UGameplayStatics::GetPlayerPawn(World, 0))
		{
			if (UCombatComponent* HeroCombat = HeroPawn->FindComponentByClass<UCombatComponent>())
			{
				HeroCombat->OnHealthDepleted.AddUniqueDynamic(this, &UGameFeelSubsystem::HandleHeroHealthDepleted);
			}
			bHeroDeathBound = true;
		}
	}

	// M5: inject the NNE boss policy alongside the HUD (same boss-discovery rule).
	// Stateless guard on purpose — presence-of-component IS the installed flag, so
	// this block lives entirely in the .cpp (no new header member). The component
	// self-disables under -rlbridge / while the Python client is connected, so
	// injecting it unconditionally is training-safe. Gated on bMemoryLoaded so the
	// archetype match never resolves against an unloaded memory (step 1 runs
	// earlier in this same call once the boss exists, so this costs no extra tick).
	bool bNNEDone = !Settings->bEnableNNEBoss;
	if (Settings->bEnableNNEBoss && bMemoryLoaded)
	{
		if (AActor* Boss = FindBossActor(World))
		{
			if (!Boss->FindComponentByClass<UNNEBossPolicyComponent>())
			{
				UNNEBossPolicyComponent* PolicyComp =
					NewObject<UNNEBossPolicyComponent>(Boss, TEXT("NNEBossPolicyComponent"));
				PolicyComp->RegisterComponent();
			}
			bNNEDone = true;
		}
	}

	const bool bCameraDone = bCameraInstalled || !Settings->bEnableCombatCamera;
	const bool bHUDDone = bHUDInstalled || !Settings->bEnableBossStatusHUD;
	if (bCameraDone && bHUDDone && bNNEDone && bMemoryLoaded && bHeroDeathBound)
	{
		World->GetTimerManager().ClearTimer(InstallTimerHandle);
	}
}

void UGameFeelSubsystem::HandleHeroHealthDepleted()
{
	RecordRoundEnd(/*bBossWon=*/true);
}

void UGameFeelSubsystem::HandleBossDied()
{
	RecordRoundEnd(/*bBossWon=*/false);
}

void UGameFeelSubsystem::RecordRoundEnd(bool bBossWon)
{
	UWorld* World = GetWorld();
	if (!World) return;

	// Debounce: the round-ending swing can re-fire death paths (in-flight combo
	// hits, redundant HandleDeath insurance) — same guard telemetry uses.
	const double NowReal = FPlatformTime::Seconds();
	if (NowReal - LastRoundEndRealSeconds < 2.0) return;
	LastRoundEndRealSeconds = NowReal;

	// Tier 4: with multiple biome bosses in one level, FindBossActor's
	// "first Enemy-tagged actor" rule would record the wrong boss's dossier when
	// a non-active encounter's boss actor is discovered before the active one.
	// Prefer the active encounter's boss; fall back to the arena-mode discovery.
	AActor* Boss = nullptr;
	if (ActiveEncounter)
	{
		Boss = ActiveEncounter->BossActor.Get();
	}
	if (!Boss)
	{
		Boss = FindBossActor(World);
	}
	if (!Boss) return;

	// Training sessions never write local player memory: the bridge owns
	// identity there (set_player_id), and bot rounds would pollute the human
	// dossier — the -NoTelemetry philosophy applied to memory.
	if (FParse::Param(FCommandLine::Get(), TEXT("rlbridge"))) return;
	if (URLBridgeComponent* Bridge = Boss->FindComponentByClass<URLBridgeComponent>())
	{
		if (Bridge->IsClientConnected()) return;
	}

	UPlayerMemoryComponent* Memory = Boss->FindComponentByClass<UPlayerMemoryComponent>();
	if (!Memory) return;

	// No profile component = no behavior signal — recording a default-neutral
	// profile would only dilute the stored one. NOTE: hero deaths to MINIONS also
	// land here as bBossWon=true; encounters-vs-anyone is by design (the dossier
	// accumulates from patrol fights, M3), the win-rate skew is accepted.
	APawn* HeroPawn = UGameplayStatics::GetPlayerPawn(World, 0);
	UPlayerProfileComponent* ProfileComp = HeroPawn ? HeroPawn->FindComponentByClass<UPlayerProfileComponent>() : nullptr;
	if (!ProfileComp) return;

	const float Duration = static_cast<float>(NowReal - RoundStartRealSeconds);
	RoundStartRealSeconds = NowReal;

	Memory->RecordEncounterEnd(ProfileComp->GetProfile(), bBossWon, Duration);
	Memory->SaveMemory();
	UE_LOG(LogTemp, Log, TEXT("GameFeelSubsystem: encounter recorded (bossWon=%d, %.0f s) — '%s' now at %d encounters."),
		bBossWon ? 1 : 0, Duration, *Memory->GetCurrentPlayerId(), Memory->GetTotalEncounters());
}

// ---------------------------------------------------------------------------
// Dev console commands (Phase G playtest helpers)
// ---------------------------------------------------------------------------

// Wipe the current player's OverworldSaveGame slot so save/load stress tests
// have a clean starting state. In-memory state is cleared and the on-disk slot
// is deleted for both 'guest' and any signed-in UID currently active.
static FAutoConsoleCommandWithWorld GOverworldResetSaveCmd(
	TEXT("overworld.ResetSave"),
	TEXT("Delete the overworld save slot for the current player (guest or UID) "
	     "and reset in-memory state. Use between save/load stress runs."),
	FConsoleCommandWithWorldDelegate::CreateLambda([](UWorld* World)
	{
		if (!World) return;
		UGameFeelSubsystem* Subsystem = World->GetSubsystem<UGameFeelSubsystem>();
		if (!Subsystem)
		{
			UE_LOG(LogTemp, Warning, TEXT("overworld.ResetSave: no GameFeelSubsystem in this world."));
			return;
		}
		// Delete both slots defensively — the guest slot may exist from a
		// pre-login run even if a UID is active.
		for (const FString& Id : { FString(TEXT("guest")), Subsystem->GetOverworldPlayerId() })
		{
			if (Id.IsEmpty()) continue;
			const FString SlotName = UOverworldSaveGame::SlotNameForPlayer(Id);
			if (UGameplayStatics::DoesSaveGameExist(SlotName, UOverworldSaveGame::UserIndex))
			{
				UGameplayStatics::DeleteGameInSlot(SlotName, UOverworldSaveGame::UserIndex);
				UE_LOG(LogTemp, Display, TEXT("overworld.ResetSave: deleted slot '%s'."), *SlotName);
			}
		}
		Subsystem->ClearOverworldState();
		UE_LOG(LogTemp, Display, TEXT("overworld.ResetSave: in-memory state cleared."));
	}));
