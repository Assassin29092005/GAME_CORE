#include "GameFeelSubsystem.h"

#include "BossActionComponent.h"
#include "BossStatusHUD.h"
#include "CombatCameraComponent.h"
#include "Engine/World.h"
#include "GameFeelSettings.h"
#include "Kismet/GameplayStatics.h"
#include "TimerManager.h"

bool UGameFeelSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	if (!Super::ShouldCreateSubsystem(Outer)) return false;

	// Game/PIE worlds only — never editor-preview or inactive worlds.
	const UWorld* World = Cast<UWorld>(Outer);
	if (!World || !World->IsGameWorld()) return false;

	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();
	return Settings->bEnableCombatCamera || Settings->bEnableBossStatusHUD;
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

	const bool bCameraDone = bCameraInstalled || !Settings->bEnableCombatCamera;
	const bool bHUDDone = bHUDInstalled || !Settings->bEnableBossStatusHUD;
	if (bCameraDone && bHUDDone)
	{
		World->GetTimerManager().ClearTimer(InstallTimerHandle);
	}
}
