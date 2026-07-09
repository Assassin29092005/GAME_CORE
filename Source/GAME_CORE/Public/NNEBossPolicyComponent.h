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

	/** Table-less core of SelectArchetype, shared with the GameFeelSettings-fed
	 *  centroid path (UNNEBossPolicyComponent builds FArchetypeProfileEntry rows
	 *  from FNNEArchetypeBankEntry — no asset needed). OutBestSimilarity receives
	 *  the winning cosine in [-1,1] (untouched when the return is NAME_None).
	 *  Plain static, not a UFUNCTION — BP callers go through SelectArchetype. */
	static FName SelectFromEntries(const TArray<FArchetypeProfileEntry>& Entries,
		const TArray<float>& PlayerProfile8, float& OutBestSimilarity);
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
 * Model wiring (precedence): a per-persona ArchetypeBank + centroid table
 * (BP-authored, or auto-populated from UGameFeelSettings::NNEArchetypeBank rows
 * when the component's own bank is empty — the normal injected path) matched by
 * cosine similarity against PlayerMemoryComponent's stored profile; then
 * ModelData directly; then UGameFeelSettings::NNEBossModelData as the
 * settings-driven default; then the first valid bank entry.
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
	 *  ArchetypeProfiles persona names. If left EMPTY (always true for the
	 *  GameFeelSubsystem-injected component — NewObject gets no BP property
	 *  pass), it is populated at init from UGameFeelSettings::NNEArchetypeBank
	 *  rows (soft-path loads; broken rows warn and are skipped). A BP-authored
	 *  bank suppresses the settings rows entirely. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "NNEBoss|Archetypes")
	TMap<FName, TObjectPtr<UNNEModelData>> ArchetypeBank;

	/** Cosine-similarity table used at BeginPlay to pick from ArchetypeBank based
	 *  on PlayerMemoryComponent's stored (decayed) profile. Optional: when null,
	 *  the centroids carried by the UGameFeelSettings::NNEArchetypeBank rows are
	 *  used instead (the normal path for the auto-injected component). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "NNEBoss|Archetypes")
	TObjectPtr<UArchetypeProfilesAsset> ArchetypeProfiles;

	/** Tier 4 overworld: per-encounter biome-preferred persona set by
	 *  ABossEncounterVolume via SetPreferredPersonaOverride *before* the component
	 *  is registered. Consulted by ResolveModelData when the cosine match against
	 *  PlayerMemoryComponent's stored profile fails (new / guest player, no
	 *  encounter history) — biome intent wins over the "first bank entry" default,
	 *  but the player's profile still outranks it when there IS a match. Empty =
	 *  no override; behaves as pre-Tier-4. */
	UFUNCTION(BlueprintCallable, Category = "NNEBoss|Archetypes")
	void SetPreferredPersonaOverride(FName Persona) { PreferredPersonaOverride = Persona; }

	/** True once the CPU model instance is created and shaped for [1,17]. */
	UFUNCTION(BlueprintPure, Category = "NNEBoss")
	bool IsPolicyReady() const { return ModelInstance.IsValid(); }

	/** Which bank entry BeginPlay selected (NAME_None = ModelData fallback). */
	UFUNCTION(BlueprintPure, Category = "NNEBoss")
	FName GetSelectedArchetype() const { return SelectedArchetype; }

	/** Cosine similarity in [-1,1] of the winning archetype match against the
	 *  player's stored PlayerMemoryComponent profile. Filled during BeginPlay by
	 *  ResolveModelData; stays 0 when no cosine match ran (bank empty / no
	 *  profile). Read-only surface for the RL-visibility showcase HUD. */
	UFUNCTION(BlueprintPure, Category = "NNEBoss")
	float GetSelectionConfidence() const { return SelectionConfidence; }

	/** Last inference's 5 raw logits, in EBossAction order [Attack,Block,Dodge,
	 *  Approach,Retreat]. Illegal actions carry -FLT_MAX (matches MaskablePPO).
	 *  Empty until the first DecisionTick after IsPolicyReady() turns true.
	 *  Read-only reflection — never modify from outside. */
	const TArray<float>& GetLastLogits() const { return OutputBuffer; }

	/** Last chosen action from argmax over the masked logits. EBossAction::Count
	 *  until the first decision. */
	UFUNCTION(BlueprintPure, Category = "NNEBoss")
	int32 GetLastChosenAction() const { return LastChosenAction; }

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
	/** Archetype bank (via PlayerMemoryComponent profile + ArchetypeProfiles or
	 *  the settings-fed centroids) -> ModelData -> GameFeelSettings default ->
	 *  first bank entry -> nullptr. Sets SelectedArchetype + SelectionSummary
	 *  as side effects and logs the archetype decision loudly. */
	UNNEModelData* ResolveModelData();

	/** When ArchetypeBank is empty, fill it (and SettingsCentroids) from
	 *  UGameFeelSettings::NNEArchetypeBank: TryLoad each soft path, warn+skip
	 *  broken rows / non-8-dim centroids. Idempotent — a non-empty bank
	 *  (BP-authored or already populated) is left untouched. */
	void PopulateBankFromSettings();

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

	// Centroid rows lifted from UGameFeelSettings::NNEArchetypeBank by
	// PopulateBankFromSettings (only rows whose Centroid.Num() == 8). Used when
	// no ArchetypeProfiles asset is wired. Plain member — the FNames/floats need
	// no GC; the loaded models are rooted by the ArchetypeBank UPROPERTY.
	TArray<FArchetypeProfileEntry> SettingsCentroids;

	// Human-readable record of the ResolveModelData decision, e.g.
	// "archetype: turtle (cos=0.87)" — surfaced in the ready log.
	FString SelectionSummary;

	// Cosine confidence of the winning match, saved for the showcase HUD.
	// Filled by ResolveModelData when a cosine match runs; stays 0 otherwise.
	float SelectionConfidence = 0.0f;

	// Argmax over the last masked logits — kept for showcase HUD; DecisionTick
	// writes it right before ExecuteAction. int32 not EBossAction to avoid a
	// forward-decl chain in the header.
	int32 LastChosenAction = -1;

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

	/** Tier 4 encounter-set persona used by ResolveModelData when the profile
	 *  cosine match fails. NAME_None = no override. */
	FName PreferredPersonaOverride = NAME_None;
};
