#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "ArenaEditorTools.generated.h"

/**
 * Editor-only arena authoring helpers, callable from editor utility Blueprints /
 * the Python editor bridge. The UFUNCTION declarations compile in every target
 * (UHT requires it); the IMPLEMENTATIONS are gated behind WITH_EDITOR in the
 * .cpp and return false in non-editor builds. Editor-only module dependencies
 * (UnrealEd) are added in GAME_CORE.Build.cs only when Target.bBuildEditor.
 */
UCLASS()
class GAME_CORE_API UArenaEditorTools : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Spawns a real, working ANavMeshBoundsVolume in the current editor world,
	 * with actual cube brush geometry (the part scripting can't do: a bare
	 * SpawnActor'd volume has an EMPTY brush and generates no navmesh).
	 *
	 * Follows the engine's own volume-factory sequence
	 * (UActorFactoryBoxVolume::PostSpawnActor → UActorFactory::
	 * CreateBrushForVolumeActor: fresh UModel/UPolys, UCubeBuilder::Build,
	 * FBSPOps::csgPrepMovingBrush, null poly materials, PostEditChange), then
	 * labels the actor, dirties the level and pokes
	 * UNavigationSystemV1::OnNavigationBoundsUpdated so navmesh generation
	 * kicks off immediately.
	 *
	 * @param Center  World-space center of the volume.
	 * @param Extent  Half-size (cm) per axis; the cube brush is 2*Extent on each
	 *                axis. Components are clamped to >= 1cm.
	 * @param Label   Editor actor label; empty keeps the auto-generated name.
	 * @return        true if the volume was spawned and its brush built.
	 *                Always false outside the editor (packaged/-game builds).
	 */
	UFUNCTION(BlueprintCallable, Category = "ArenaEditorTools")
	static bool SpawnNavBoundsVolume(FVector Center, FVector Extent, FString Label);
};
