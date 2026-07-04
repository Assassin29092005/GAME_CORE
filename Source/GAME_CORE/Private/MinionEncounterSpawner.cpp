#include "MinionEncounterSpawner.h"
#include "NPCMinionCharacter.h"
#include "NavigationSystem.h"
#include "Components/CapsuleComponent.h"

AMinionEncounterSpawner::AMinionEncounterSpawner()
{
	PrimaryActorTick.bCanEverTick = false;
	RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
}

void AMinionEncounterSpawner::BeginPlay()
{
	Super::BeginPlay();

	if (bSpawnOnBeginPlay)
	{
		SpawnMinions();
	}
}

void AMinionEncounterSpawner::SpawnMinions()
{
	if (!MinionClass || SpawnCount <= 0) return;

	UWorld* World = GetWorld();
	if (!World) return;

	// Re-trigger guard: prune dead entries, then refuse to stack a second ring
	// on top of a batch that still exists (e.g. an overlap volume firing twice).
	SpawnedMinions.RemoveAll([](const TWeakObjectPtr<ANPCMinionCharacter>& Minion)
	{
		return !Minion.IsValid();
	});
	if (SpawnedMinions.Num() > 0)
	{
		UE_LOG(LogTemp, Log, TEXT("MinionEncounterSpawner[%s]: SpawnMinions skipped — %d tracked minion(s) still exist. Use RespawnAll to force a fresh batch."),
			*GetName(), SpawnedMinions.Num());
		return;
	}

	UNavigationSystemV1* NavSys = FNavigationSystem::GetCurrent<UNavigationSystemV1>(World);

	// NavMesh projection returns a point ON the floor; lift by the capsule half
	// height so the character doesn't spawn embedded in the ground.
	const ANPCMinionCharacter* MinionCDO = MinionClass->GetDefaultObject<ANPCMinionCharacter>();
	const float CapsuleHalfHeight = (MinionCDO && MinionCDO->GetCapsuleComponent())
		? MinionCDO->GetCapsuleComponent()->GetScaledCapsuleHalfHeight()
		: 90.0f;

	const FVector Center = GetActorLocation();
	int32 Spawned = 0;

	for (int32 i = 0; i < SpawnCount; i++)
	{
		const float Angle = (2.0f * PI * i) / SpawnCount;
		FVector Point = Center + FVector(FMath::Cos(Angle), FMath::Sin(Angle), 0.0f) * SpawnRadius;

		// Snap the ring point onto the navmesh so pathing works from frame one.
		// Generous vertical extent covers spawners placed on ledges/slopes.
		FNavLocation NavLoc;
		if (NavSys && NavSys->ProjectPointToNavigation(Point, NavLoc, FVector(500.0f, 500.0f, 1000.0f)))
		{
			Point = NavLoc.Location;
		}
		else
		{
			// Projection failed (navmesh hole / not built yet / point off-mesh).
			// The raw ring point carries the SPAWNER's Z, which on sculpted
			// terrain can sit meters above (mid-air spawn → fall/KillZ) or below
			// (embedded in the hillside) the actual ground. Ground the point with
			// a downward line trace, and WARN so a half-broken encounter is
			// visible in Saved/Logs/GAME_CORE.log instead of silently "3/3".
			FHitResult GroundHit;
			FCollisionQueryParams GroundParams(SCENE_QUERY_STAT(MinionSpawnGroundTrace), false, this);
			if (World->LineTraceSingleByChannel(
					GroundHit,
					Point + FVector(0.0f, 0.0f, 2000.0f),
					Point - FVector(0.0f, 0.0f, 4000.0f),
					ECC_WorldStatic,
					GroundParams))
			{
				Point.Z = GroundHit.ImpactPoint.Z;
			}
			UE_LOG(LogTemp, Warning, TEXT("MinionEncounterSpawner[%s]: nav projection FAILED for ring point %d at %s — %s."),
				*GetName(), i, *Point.ToCompactString(),
				GroundHit.bBlockingHit ? TEXT("grounded via line trace") : TEXT("no ground found, using raw ring point"));
		}
		Point.Z += CapsuleHalfHeight;

		FActorSpawnParameters Params;
		Params.Owner = this;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AdjustIfPossibleButAlwaysSpawn;

		const FRotator FaceCenter = (Center - Point).GetSafeNormal2D().Rotation();
		ANPCMinionCharacter* Minion = World->SpawnActor<ANPCMinionCharacter>(MinionClass, Point, FaceCenter, Params);
		if (!Minion) continue;

		// Hand the patrol route through — the BT service reads it off the pawn.
		Minion->PatrolPoints = PatrolPoints;

		SpawnedMinions.Add(Minion);

#if WITH_EDITOR
		Minion->SetActorLabel(FString::Printf(TEXT("%s_Minion_%d"), *GetName(), i));
#endif
		Spawned++;
	}

	UE_LOG(LogTemp, Log, TEXT("MinionEncounterSpawner[%s]: spawned %d/%d minions on r=%.0fcm ring."),
		*GetName(), Spawned, SpawnCount, SpawnRadius);
}

void AMinionEncounterSpawner::RespawnAll()
{
	// Clear out any survivors from the previous batch, then spawn fresh.
	// Corpses mid-CorpseLifetime are also destroyed here (harmless — the
	// lifespan would have gotten them anyway).
	for (const TWeakObjectPtr<ANPCMinionCharacter>& Minion : SpawnedMinions)
	{
		if (ANPCMinionCharacter* LiveMinion = Minion.Get())
		{
			LiveMinion->Destroy();
		}
	}
	SpawnedMinions.Reset();

	SpawnMinions();
}
