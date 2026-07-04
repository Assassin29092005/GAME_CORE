#pragma once

#include "CoreMinimal.h"
#include "Shakes/DefaultCameraShakeBase.h"
#include "CameraShakes.generated.h"

// Code-only hit camera shakes (guide.md 3.4). UHitFeedbackComponent uses these
// as fallback defaults whenever its HitCameraShake property is left unset, so
// camera punch works with zero content setup. Assigning a BP shake asset on the
// component still overrides both. Both configure the UDefaultCameraShakeBase
// Perlin-noise root pattern in the constructor — rotation-led (a camera that
// translates through walls reads as a bug; rotation reads as impact).

/** Light hit: short, small rotation punch. */
UCLASS()
class GAME_CORE_API UCS_HitLight : public UDefaultCameraShakeBase
{
	GENERATED_BODY()

public:
	UCS_HitLight(const FObjectInitializer& ObjectInitializer);
};

/** Heavy hit / finisher / parry freeze: longer, bigger rotation, plus a small
 *  FOV oscillation — the "FOV kick" fraction of perceived weight. */
UCLASS()
class GAME_CORE_API UCS_HitHeavy : public UDefaultCameraShakeBase
{
	GENERATED_BODY()

public:
	UCS_HitHeavy(const FObjectInitializer& ObjectInitializer);
};
