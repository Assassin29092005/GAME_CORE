#include "GameFeelSubsystem.h"

#include "BossActionComponent.h"
#include "BossStatusHUD.h"
#include "CombatCameraComponent.h"
#include "CombatComponent.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "FirebaseAuthSubsystem.h"
#include "GameFeelSettings.h"
#include "Kismet/GameplayStatics.h"
#include "LockOnComponent.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "NNEBossPolicyComponent.h"
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

void UGameFeelSubsystem::TryInstall()
{
	UWorld* World = GetWorld();
	if (!World) return;

	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();

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
			bCameraInstalled = true;
		}
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

	AActor* Boss = FindBossActor(World);
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
