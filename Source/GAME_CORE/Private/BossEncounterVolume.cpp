#include "BossEncounterVolume.h"

#include "BossActionComponent.h"
#include "Engine/World.h"
#include "GameFeelSubsystem.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"

ABossEncounterVolume::ABossEncounterVolume()
{
	PrimaryActorTick.bCanEverTick = false;
}

void ABossEncounterVolume::BeginPlay()
{
	Super::BeginPlay();

	OnActorBeginOverlap.AddDynamic(this, &ABossEncounterVolume::OnPlayerBeginOverlap);
	OnActorEndOverlap.AddDynamic(this, &ABossEncounterVolume::OnPlayerEndOverlap);

	// Phase E: honor the saved defeated-zone bitfield. GameFeelSubsystem loads
	// the save at world begin (before ABossEncounterVolume::BeginPlay via world-
	// subsystem OnWorldBeginPlay), so this check has the latest state.
	if (UWorld* World = GetWorld())
	{
		if (UGameFeelSubsystem* Subsystem = World->GetSubsystem<UGameFeelSubsystem>())
		{
			if (Subsystem->IsEncounterDefeated(EncounterID))
			{
				bAlreadyDefeated = true;
				UE_LOG(LogTemp, Log, TEXT("BossEncounterVolume '%s': loaded from save as already defeated."),
					*EncounterID.ToString());
			}
		}
	}

	if (BossActor.IsNull())
	{
		UE_LOG(LogTemp, Warning, TEXT("BossEncounterVolume '%s': BossActor is null — this volume is inert."),
			*GetName());
	}
	else
	{
		// Pre-place the boss hidden so the player doesn't see it before entering.
		// Sync-load is fine: the boss actor is already in the level; the soft ref
		// is purely to avoid class hard-dependency on the map.
		AActor* Boss = BossActor.Get();
		if (Boss == nullptr)
		{
			Boss = BossActor.LoadSynchronous();
		}
		if (Boss)
		{
			Boss->SetActorHiddenInGame(true);
			Boss->SetActorEnableCollision(false);
		}
	}
}

void ABossEncounterVolume::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	OnActorBeginOverlap.RemoveDynamic(this, &ABossEncounterVolume::OnPlayerBeginOverlap);
	OnActorEndOverlap.RemoveDynamic(this, &ABossEncounterVolume::OnPlayerEndOverlap);

	if (bEncounterActive)
	{
		if (UWorld* World = GetWorld())
		{
			if (UGameFeelSubsystem* Subsystem = World->GetSubsystem<UGameFeelSubsystem>())
			{
				Subsystem->EndEncounter(this);
			}
		}
	}

	Super::EndPlay(EndPlayReason);
}

void ABossEncounterVolume::OnPlayerBeginOverlap(AActor* /*OverlappedActor*/, AActor* OtherActor)
{
	if (bEncounterActive || bAlreadyDefeated) return;

	// Only the player pawn triggers encounters — never minions or the boss itself
	// (bosses tag themselves Enemy; the player pawn does not, so a tag negation is
	// the right filter). The paranoid alternative is a CastChecked<APlayerController>
	// on OtherActor->GetOwner() but that costs a hop; tag check is O(1).
	if (!OtherActor || OtherActor->ActorHasTag(FName(TEXT("Enemy")))) return;

	APawn* Pawn = Cast<APawn>(OtherActor);
	if (!Pawn || !Pawn->IsPlayerControlled()) return;

	UWorld* World = GetWorld();
	if (!World) return;

	UGameFeelSubsystem* Subsystem = World->GetSubsystem<UGameFeelSubsystem>();
	if (!Subsystem) return;

	bEncounterActive = true;
	Subsystem->BeginEncounter(this);
}

void ABossEncounterVolume::OnPlayerEndOverlap(AActor* /*OverlappedActor*/, AActor* OtherActor)
{
	if (!bEncounterActive) return;
	if (!OtherActor || OtherActor->ActorHasTag(FName(TEXT("Enemy")))) return;
	APawn* Pawn = Cast<APawn>(OtherActor);
	if (!Pawn || !Pawn->IsPlayerControlled()) return;

	// Player leaves the encounter volume mid-fight: treated as a retreat (the boss
	// does NOT count as defeated). Ends the encounter cleanly so the exploration
	// camera returns and the boss actor is re-hidden — no half-state on re-entry.
	UWorld* World = GetWorld();
	if (!World) return;
	UGameFeelSubsystem* Subsystem = World->GetSubsystem<UGameFeelSubsystem>();
	if (!Subsystem) return;

	bEncounterActive = false;
	Subsystem->EndEncounter(this);
}

void ABossEncounterVolume::OnBossDefeated()
{
	if (!bEncounterActive) return;

	bAlreadyDefeated = true;
	bEncounterActive = false;

	UWorld* World = GetWorld();
	if (!World) return;
	if (UGameFeelSubsystem* Subsystem = World->GetSubsystem<UGameFeelSubsystem>())
	{
		Subsystem->EndEncounter(this);
	}
}
