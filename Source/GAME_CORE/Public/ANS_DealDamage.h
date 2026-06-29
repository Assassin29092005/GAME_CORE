#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimNotifies/AnimNotifyState.h"
#include "ANS_DealDamage.generated.h"

/**
 * Anim Notify State that performs a sphere trace during the damage window
 * and applies damage + hit reaction to the first actor hit.
 * Place on attack montages to define when the attack can deal damage.
 */
UCLASS(meta = (DisplayName = "Deal Damage Window"))
class GAME_CORE_API UANS_DealDamage : public UAnimNotifyState
{
	GENERATED_BODY()

public:
	UANS_DealDamage();

	virtual void NotifyBegin(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, float TotalDuration, const FAnimNotifyEventReference& EventReference) override;
	virtual void NotifyTick(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, float FrameDeltaTime, const FAnimNotifyEventReference& EventReference) override;
	virtual void NotifyEnd(USkeletalMeshComponent* MeshComp, UAnimSequenceBase* Animation, const FAnimNotifyEventReference& EventReference) override;

	virtual FString GetNotifyName_Implementation() const override { return TEXT("DealDamage"); }

	/** Bone/socket on the attacker's mesh to trace from. Leave None to fall back
	 *  to the actor's center + TraceForwardOffset (legacy behavior). Use the hand
	 *  bone (e.g. "hand_r", "weapon_r", or whatever the rig calls the punching/
	 *  weapon hand) so damage only registers when the fist actually reaches the
	 *  target — not when the actor is generically close. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Damage")
	FName HandSocketName;

	/** Sphere trace radius around the socket/forward point. ~25-40 = realistic
	 *  fist/weapon reach; ~80 = forgiving but lets damage land before contact. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Damage")
	float TraceRadius = 30.0f;

	/** Used only when HandSocketName is None — distance forward of actor center
	 *  to trace toward. Ignored when tracing from a socket (the socket already
	 *  IS the contact point). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Damage")
	float TraceForwardOffset = 120.0f;

	/** Draws the trace shape in the viewport for one frame per tick — turn ON to
	 *  tune radius/socket visually, OFF for play. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Damage|Debug")
	bool bDrawDebugTrace = false;

private:
	// Prevents hitting the same target multiple times per swing
	bool bHasHitThisSwing = false;
};
