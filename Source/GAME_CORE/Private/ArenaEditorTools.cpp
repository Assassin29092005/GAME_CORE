#include "ArenaEditorTools.h"

#if WITH_EDITOR
#include "Editor.h"                              // GEditor
#include "ActorFactories/ActorFactory.h"         // UActorFactory::CreateBrushForVolumeActor (UNREALED_API)
#include "Builders/CubeBuilder.h"                // UCubeBuilder
#include "Engine/Brush.h"                        // EBrushType / Brush_Add
#include "Engine/World.h"
#include "NavMesh/NavMeshBoundsVolume.h"
#include "NavigationSystem.h"
#endif

bool UArenaEditorTools::SpawnNavBoundsVolume(FVector Center, FVector Extent, FString Label)
{
#if WITH_EDITOR
	if (!GEditor)
	{
		UE_LOG(LogTemp, Warning, TEXT("ArenaEditorTools::SpawnNavBoundsVolume: GEditor is null (running -game?) — refusing."));
		return false;
	}

	UWorld* World = GEditor->GetEditorWorldContext().World();
	if (!World)
	{
		UE_LOG(LogTemp, Warning, TEXT("ArenaEditorTools::SpawnNavBoundsVolume: no editor world."));
		return false;
	}

	// Degenerate extents produce a degenerate BSP brush — clamp instead of failing.
	Extent.X = FMath::Max(Extent.X, 1.0);
	Extent.Y = FMath::Max(Extent.Y, 1.0);
	Extent.Z = FMath::Max(Extent.Z, 1.0);

	FActorSpawnParameters SpawnParams;
	SpawnParams.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	SpawnParams.ObjectFlags |= RF_Transactional;

	ANavMeshBoundsVolume* Volume =
		World->SpawnActor<ANavMeshBoundsVolume>(Center, FRotator::ZeroRotator, SpawnParams);
	if (!Volume)
	{
		UE_LOG(LogTemp, Warning, TEXT("ArenaEditorTools::SpawnNavBoundsVolume: SpawnActor failed."));
		return false;
	}

	// Additive CSG — what every hand-placed volume gets (ABrush::PostRegister
	// promotes Brush_Default to Brush_Add for non-builder brushes anyway; be explicit).
	Volume->BrushType = Brush_Add;

	// The known-hard part: a script-spawned volume has NO brush geometry. Build a
	// cube brush exactly the way the editor's own volume placement does —
	// UActorFactoryBoxVolume::PostSpawnActor feeds a UCubeBuilder into
	// UActorFactory::CreateBrushForVolumeActor (Engine\Source\Editor\UnrealEd\
	// Private\Factories\ActorFactory.cpp), which allocates UModel + UPolys on the
	// actor, runs the builder, preps the brush via FBSPOps::csgPrepMovingBrush,
	// clears poly materials, and finalizes with PreEditChange/PostEditChange
	// (PostEditChange re-registers the brush component with the new geometry).
	UCubeBuilder* CubeBuilder = NewObject<UCubeBuilder>();
	CubeBuilder->X = static_cast<float>(Extent.X * 2.0);  // builder takes FULL sizes
	CubeBuilder->Y = static_cast<float>(Extent.Y * 2.0);
	CubeBuilder->Z = static_cast<float>(Extent.Z * 2.0);
	UActorFactory::CreateBrushForVolumeActor(Volume, CubeBuilder);

	if (!Label.IsEmpty())
	{
		Volume->SetActorLabel(Label);
	}

	// Persist + rebuild: dirty the level package and tell the nav system the
	// bounds changed so tile generation starts now (cheap incremental path —
	// the same call ANavMeshBoundsVolume::PostEditChangeProperty makes when a
	// volume is moved/scaled by hand).
	Volume->MarkPackageDirty();
	if (UNavigationSystemV1* NavSys = FNavigationSystem::GetCurrent<UNavigationSystemV1>(World))
	{
		NavSys->OnNavigationBoundsUpdated(Volume);
	}

	UE_LOG(LogTemp, Log, TEXT("ArenaEditorTools: spawned NavMeshBoundsVolume '%s' at %s, extent %s."),
		*Volume->GetActorLabel(), *Center.ToCompactString(), *Extent.ToCompactString());
	return true;
#else
	// Non-editor targets: UFUNCTION must exist, but there is nothing to do.
	return false;
#endif
}
