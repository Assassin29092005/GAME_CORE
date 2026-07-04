#include "CameraShakes.h"
#include "Shakes/PerlinNoiseCameraShakePattern.h"

// UDefaultCameraShakeBase's constructor installs a UPerlinNoiseCameraShakePattern
// as the root pattern, so both subclasses just tune it. Location axes are zeroed
// on purpose: translational shake clips the camera into geometry; rotation (and,
// on the heavy tier, FOV) carries the impact.

UCS_HitLight::UCS_HitLight(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
	bSingleInstance = true; // rapid combo hits retrigger the shake instead of stacking

	if (UPerlinNoiseCameraShakePattern* Pattern = Cast<UPerlinNoiseCameraShakePattern>(GetRootShakePattern()))
	{
		Pattern->Duration = 0.18f;
		Pattern->BlendInTime = 0.02f;
		Pattern->BlendOutTime = 0.10f;

		// No translation — rotation-only punch.
		Pattern->X.Amplitude = 0.0f;
		Pattern->Y.Amplitude = 0.0f;
		Pattern->Z.Amplitude = 0.0f;

		Pattern->Pitch.Amplitude = 0.4f;
		Pattern->Pitch.Frequency = 30.0f;
		Pattern->Yaw.Amplitude = 0.4f;
		Pattern->Yaw.Frequency = 25.0f;
		Pattern->Roll.Amplitude = 0.2f;
		Pattern->Roll.Frequency = 20.0f;

		Pattern->FOV.Amplitude = 0.0f;
	}
}

UCS_HitHeavy::UCS_HitHeavy(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
	bSingleInstance = true;

	if (UPerlinNoiseCameraShakePattern* Pattern = Cast<UPerlinNoiseCameraShakePattern>(GetRootShakePattern()))
	{
		Pattern->Duration = 0.30f;
		Pattern->BlendInTime = 0.02f;
		Pattern->BlendOutTime = 0.15f;

		Pattern->X.Amplitude = 0.0f;
		Pattern->Y.Amplitude = 0.0f;
		Pattern->Z.Amplitude = 0.0f;

		Pattern->Pitch.Amplitude = 0.8f;
		Pattern->Pitch.Frequency = 25.0f;
		Pattern->Yaw.Amplitude = 0.8f;
		Pattern->Yaw.Frequency = 20.0f;
		Pattern->Roll.Amplitude = 0.4f;
		Pattern->Roll.Frequency = 18.0f;

		// The FOV kick — a large fraction of perceived weight on heavies.
		Pattern->FOV.Amplitude = 1.5f;
		Pattern->FOV.Frequency = 10.0f;
	}
}
