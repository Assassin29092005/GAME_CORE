#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Engine/DataAsset.h"
// NNE public surface (Runtime/NNE, verified against the 5.8 engine source):
// UE::NNE::IModelCPU / IModelInstanceCPU (NNERuntimeCPU.h) and the RunSync
// binding types (NNERuntimeRunSync.h, pulled in transitively).
#include "NNERuntimeCPU.h"
#include "NNEBossPolicyComponent.generated.h"

class UNNEModelData;
class UBossActionComponent;
class UStateObservationComponent;
class URLBridgeComponent;

/**
 * One named archetype: a persona label and its 8-dim reference profile.
 * Profile order MUST match FPlayerProfile::ToFloatArray():
 *   [Aggression, DodgeTendency, BlockTendency, OpenerAggression,
 *    PressureResponse, KitingScore, ComboCompletionRate, PositionalVariance]
 */
USTRUCT(BlueprintType)
struct FArchetypeProfileEntry
{
	GENERATED_BODY()

	/** Persona name — must match a key in UNNEBossPolicyComponent::ArchetypeBank
	 *  (and, by convention, an M1 AutoHero persona: rusher/turtle/kiter/counter/chaotic). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Archetype")
	FName Persona;

	/** 8-dim reference profile in [0,1], FPlayerProfile::ToFloatArray() order.
	 *  Entries whose Num() != 8 are skipped with a warning at selection time. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Archetype")
	TArray<float> Profile;
};

/**
 * M5 archetype table: maps the player's stored 8-dim behavior profile to the
 * nearest persona by cosine similarity. Authored once in the editor as a
 * DataAsset; UNNEBossPolicyComponent consults it at BeginPlay to pick which
 * ArchetypeBank model to load, so a returning rushdown player meets the
 * anti-rusher boss from the first swing.
 */
UCLASS(BlueprintType)
class GAME_CORE_API UArchetypeProfilesAsset : public UDataAsset
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Archetype")
	TArray<FArchetypeProfileEntry> Archetypes;

	/** Nearest archetype to PlayerProfile8 (cosine similarity over the 8 dims).
	 *  Returns NAME_None when the table is empty, the input is not 8-dim, or
	 *  every candidate is degenerate (zero-norm). Profiles live in [0,1] so a
	 *  zero norm only happens on authoring mistakes — logged, not crashed. */
	UFUNCTION(BlueprintCallable, Category = "Archetype")
	FName SelectArchetype(const TArray<float>& PlayerProfile8) const;
};

/**
 * M5 — the shipped boss brain: in-engine ONNX inference via NNE, no Python.
 *
 * On a DecisionHz timer this component builds the EXACT 17-dim observation the
 * TCP bridge sends (by calling UStateObservationComponent::CollectObservation()
 * — zero duplicated normalization), runs the exported SB3 actor on the ORT CPU
 * runtime, applies UBossActionComponent::GetLegalActionMask() as a masked
 * argmax over the 5 logits (illegal = -FLT_MAX, mirroring MaskablePPO), and
 * dispatches through UBossActionComponent::ExecuteAction(). The whole Phase 4
 * execution layer (commitment / hysteresis / mask / recovery / fallback brain)
 * sits downstream untouched — the game cannot tell NNE from Python.
 *
 * Source-switch rules (the bridge always outranks NNE):
 *   - `-rlbridge` on the command line  -> self-disable for the session (dev TCP path).
 *   - RLBridgeComponent::IsClientConnected() -> skip decisions while true (cheap
 *     per-decision poll; NNE resumes automatically when Python disconnects).
 * Side effect worth knowing: every NNE ExecuteAction() refreshes the Phase 4.6
 * bridge watchdog, so the scripted fallback brain stays parked while NNE is
 * healthy and still takes over if NNE has no model — layered degradation.
 *
 * Install: auto-injected onto the boss by UGameFeelSubsystem when
 * UGameFeelSettings::bEnableNNEBoss is set (no BP wiring), or add it in BP.
 * Model wiring: ModelData directly, a per-persona ArchetypeBank +
 * ArchetypeProfiles table, or UGameFeelSettings::NNEBossModelData as the
 * settings-driven default for the injected path.
 *
 * Headless verification: console `boss.NNESelfTest [/Game/Path/To/ModelData]`
 * (see the FAutoConsoleCommand in the .cpp) — runs one zeros-obs inference and
 * logs the 5 logits + chosen action.
 */
UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class GAME_CORE_API UNNEBossPolicyComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UNNEBossPolicyComponent();

	/** Fallback / single-policy model (exported by Python/export_onnx.py, imported
	 *  as a UNNEModelData asset). Used when the archetype bank is empty or no
	 *  archetype matches. If left null, UGameFeelSettings::NNEBossModelData is tried. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "NNEBoss")
	TObjectPtr<UNNEModelData> ModelData;

	/** Decision cadence — matches the RL bridge's ~15 Hz so the trained policy sees
	 *  the action-repeat pattern it was trained with. Read once at BeginPlay. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "NNEBoss", meta = (ClampMin = "1.0", ClampMax = "60.0"))
	float DecisionHz = 15.0f;

	/** Master switch. Forced false for the whole session by `-rlbridge`. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "NNEBoss")
	bool bEnabled = true;

	/** Per-persona exported policies (boss_rusher.onnx, ...). Keys must match
	 *  ArchetypeProfiles persona names. Empty bank -> ModelData fallback. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "NNEBoss|Archetypes")
	TMap<FName, TObjectPtr<UNNEModelData>> ArchetypeBank;

	/** Cosine-similarity table used at BeginPlay to pick from ArchetypeBank based
	 *  on PlayerMemoryComponent's stored (decayed) profile. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "NNEBoss|Archetypes")
	TObjectPtr<UArchetypeProfilesAsset> ArchetypeProfiles;

	/** True once the CPU model instance is created and shaped for [1,17]. */
	UFUNCTION(BlueprintPure, Category = "NNEBoss")
	bool IsPolicyReady() const { return ModelInstance.IsValid(); }

	/** Which bank entry BeginPlay selected (NAME_None = ModelData fallback). */
	UFUNCTION(BlueprintPure, Category = "NNEBoss")
	FName GetSelectedArchetype() const { return SelectedArchetype; }

	/** One zeros-obs inference; logs the 5 logits + argmax (+ masked argmax when the
	 *  BossActionComponent is reachable). Returns false if no model could run.
	 *  Reuses the live instance when ready, else builds a throwaway one from
	 *  ResolveModelData() — so it also works pre-wiring in a bare level. */
	bool RunSelfTest(FString& OutSummary);

	/** Shared init path (also used by boss.NNESelfTest for standalone asset tests):
	 *  resolve INNERuntimeCPU("NNERuntimeORTCpu"), CreateModelCPU + instance,
	 *  validate the [*,17] -> [*,5] tensor surface, SetInputTensorShapes([1,17]).
	 *  Public+static on purpose: no component state, and the console command must
	 *  reach it without an instance. */
	static bool CreateCpuInstanceForModel(UNNEModelData* InModelData,
		TSharedPtr<UE::NNE::IModelCPU>& OutModel,
		TSharedPtr<UE::NNE::IModelInstanceCPU>& OutInstance,
		FString& OutError);

	/** 17 — must equal UStateObservationComponent::GetObservationSize(). The NNE
	 *  path ships the BASE observation only: the Python-side augmentations (IRL /
	 *  emotion / hierarchy extra dims) are training-stack features; shipped
	 *  checkpoints for M5 are trained on the 17-dim base vector. */
	static constexpr int32 ObsDim = 17;

	/** 5 — EBossAction::Count. */
	static constexpr int32 NumActions = 5;

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

private:
	/** Archetype bank (via PlayerMemoryComponent profile + ArchetypeProfiles) ->
	 *  ModelData -> GameFeelSettings default -> first bank entry -> nullptr.
	 *  Sets SelectedArchetype as a side effect. */
	UNNEModelData* ResolveModelData();

	/** Timer body: obs -> RunSync -> masked argmax -> ExecuteAction. */
	void DecisionTick();

	/** RunSync wrapper over the member buffers. False on inference failure. */
	bool RunInference();

	// Model lifetime: ModelData assets are kept alive by the UPROPERTYs above;
	// the compiled model + instance are plain shared ptrs (engine contract:
	// caller-owned, ModelData only needs to outlive CreateModelCPU).
	TSharedPtr<UE::NNE::IModelCPU> Model;
	TSharedPtr<UE::NNE::IModelInstanceCPU> ModelInstance;

	FTimerHandle DecisionTimerHandle;
	FName SelectedArchetype = NAME_None;

	// Peer components, cached in BeginPlay (FindComponentByClass — no hard refs,
	// project convention).
	TWeakObjectPtr<UBossActionComponent> BossAction;
	TWeakObjectPtr<UStateObservationComponent> ObsComp;
	TWeakObjectPtr<URLBridgeComponent> Bridge;

	// Reused per-decision tensor buffers (no per-tick allocation at 15 Hz).
	TArray<float> InputBuffer;
	TArray<float> OutputBuffer;

	// Log-once guards so a mis-wired level warns once instead of spamming at 15 Hz.
	bool bWarnedNoObsComp = false;
	bool bWarnedBadObsSize = false;
	bool bWarnedInferenceFailed = false;
};
