#include "NNEBossPolicyComponent.h"

#include "BossActionComponent.h"
#include "Engine/World.h"
#include "GameFeelSettings.h"
#include "HAL/IConsoleManager.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "NNE.h"
#include "NNEModelData.h"
#include "PlayerMemoryComponent.h"
#include "RLBridgeComponent.h"
#include "StateObservationComponent.h"
#include "TimerManager.h"
#include "UObject/UObjectIterator.h"

// The ORT CPU runtime's registered name. Verified against engine source:
// Engine/Plugins/NNE/NNERuntimeORT/Source/NNERuntimeORT/Private/NNERuntimeORT.cpp:153
// (UNNERuntimeORTCpu::GetRuntimeName() returns TEXT("NNERuntimeORTCpu")).
static const TCHAR* GNNEBossRuntimeName = TEXT("NNERuntimeORTCpu");

// Default asset path used by boss.NNESelfTest when no component instance exists
// yet (bare level / early -ExecCmds). Matches Tools/import_onnx_model.py.
static const TCHAR* GNNEBossSelfTestDefaultAsset = TEXT("/Game/Arena/Models/NNM_BossUntrained.NNM_BossUntrained");

// ---------------------------------------------------------------------------
// UArchetypeProfilesAsset
// ---------------------------------------------------------------------------

FName UArchetypeProfilesAsset::SelectArchetype(const TArray<float>& PlayerProfile8) const
{
	float UnusedSimilarity = -2.0f;
	return SelectFromEntries(Archetypes, PlayerProfile8, UnusedSimilarity);
}

FName UArchetypeProfilesAsset::SelectFromEntries(const TArray<FArchetypeProfileEntry>& Entries,
	const TArray<float>& PlayerProfile8, float& OutBestSimilarity)
{
	// Mean-centered cosine over the 8 profile dims: both vectors are centered at
	// the 0.5 neutral profile before the dot product. Raw cosine on [0,1]
	// profiles saturates near 1 (every vector shares a large positive offset)
	// and barely discriminates; after centering, similarity measures the
	// DIRECTION of deviation from neutral — which is the archetype signal.
	// Zero-norm after centering = exactly-neutral profile = no signal.
	// Python/measure_centroids.py mirrors this math (keep them in sync).
	constexpr float Neutral = 0.5f;

	if (PlayerProfile8.Num() != 8)
	{
		UE_LOG(LogTemp, Warning, TEXT("ArchetypeProfiles: SelectArchetype expects 8 dims, got %d"), PlayerProfile8.Num());
		return NAME_None;
	}

	float PlayerNormSq = 0.0f;
	for (const float V : PlayerProfile8) { PlayerNormSq += (V - Neutral) * (V - Neutral); }
	if (PlayerNormSq <= UE_KINDA_SMALL_NUMBER)
	{
		return NAME_None; // all-neutral player profile carries no signal
	}
	const float PlayerNorm = FMath::Sqrt(PlayerNormSq);

	FName BestName = NAME_None;
	float BestSimilarity = -2.0f; // cosine is in [-1,1]

	for (const FArchetypeProfileEntry& Entry : Entries)
	{
		if (Entry.Profile.Num() != 8)
		{
			UE_LOG(LogTemp, Warning, TEXT("ArchetypeProfiles: entry '%s' has %d dims (want 8) — skipped."),
				*Entry.Persona.ToString(), Entry.Profile.Num());
			continue;
		}

		float Dot = 0.0f;
		float EntryNormSq = 0.0f;
		for (int32 i = 0; i < 8; ++i)
		{
			const float EntryCentered = Entry.Profile[i] - Neutral;
			Dot += EntryCentered * (PlayerProfile8[i] - Neutral);
			EntryNormSq += EntryCentered * EntryCentered;
		}
		if (EntryNormSq <= UE_KINDA_SMALL_NUMBER)
		{
			UE_LOG(LogTemp, Warning, TEXT("ArchetypeProfiles: entry '%s' is all-neutral (zero norm after centering) — skipped."),
				*Entry.Persona.ToString());
			continue;
		}

		const float Similarity = Dot / (PlayerNorm * FMath::Sqrt(EntryNormSq));
		if (Similarity > BestSimilarity)
		{
			BestSimilarity = Similarity;
			BestName = Entry.Persona;
		}
	}

	if (!BestName.IsNone())
	{
		OutBestSimilarity = BestSimilarity;
	}
	return BestName;
}

// ---------------------------------------------------------------------------
// UNNEBossPolicyComponent
// ---------------------------------------------------------------------------

UNNEBossPolicyComponent::UNNEBossPolicyComponent()
{
	// Timer-driven at DecisionHz — no per-frame tick needed.
	PrimaryComponentTick.bCanEverTick = false;
}

bool UNNEBossPolicyComponent::CreateCpuInstanceForModel(UNNEModelData* InModelData,
	TSharedPtr<UE::NNE::IModelCPU>& OutModel,
	TSharedPtr<UE::NNE::IModelInstanceCPU>& OutInstance,
	FString& OutError)
{
	using namespace UE::NNE;

	if (!InModelData)
	{
		OutError = TEXT("no UNNEModelData provided");
		return false;
	}

	// Runtime resolve — NNE.h:62 template GetRuntime<T>(Name) casts the registered
	// INNERuntime to INNERuntimeCPU. The ORT CPU runtime registers as
	// "NNERuntimeORTCpu" (NNERuntimeORT plugin, enabled in the .uproject).
	TWeakInterfacePtr<INNERuntimeCPU> Runtime = GetRuntime<INNERuntimeCPU>(GNNEBossRuntimeName);
	if (!Runtime.IsValid())
	{
		FString Names;
		for (const FString& Name : GetAllRuntimeNames()) { Names += Name + TEXT(" "); }
		OutError = FString::Printf(TEXT("runtime '%s' not registered (available: %s) — is the NNERuntimeORT plugin enabled?"),
			GNNEBossRuntimeName, Names.IsEmpty() ? TEXT("<none>") : *Names);
		return false;
	}

	// INNERuntimeCPU::CanCreateModelCPU / CreateModelCPU — NNERuntimeCPU.h:75/87.
	if (Runtime->CanCreateModelCPU(InModelData) != EResultStatus::Ok)
	{
		OutError = FString::Printf(TEXT("runtime refuses model data '%s' (wrong format / not cooked for %s?)"),
			*InModelData->GetName(), GNNEBossRuntimeName);
		return false;
	}

	// ModelData only needs to remain valid THROUGH CreateModelCPU (engine
	// contract, NNERuntimeCPU.h:80-82); the UPROPERTY refs on the component /
	// the asset registry keep it alive anyway.
	OutModel = Runtime->CreateModelCPU(InModelData);
	if (!OutModel.IsValid())
	{
		OutError = TEXT("CreateModelCPU failed");
		return false;
	}

	// IModelCPU::CreateModelInstanceCPU — NNERuntimeCPU.h:45.
	OutInstance = OutModel->CreateModelInstanceCPU();
	if (!OutInstance.IsValid())
	{
		OutModel.Reset();
		OutError = TEXT("CreateModelInstanceCPU failed");
		return false;
	}

	// Validate the tensor surface before shaping: export_onnx.py emits
	// observation [-1,17] float32 -> action_logits [-1,5] float32. Catching a
	// wrong-asset assignment here beats a silent garbage argmax in a fight.
	const TConstArrayView<FTensorDesc> InDescs = OutInstance->GetInputTensorDescs();
	const TConstArrayView<FTensorDesc> OutDescs = OutInstance->GetOutputTensorDescs();
	if (InDescs.Num() != 1 || OutDescs.Num() != 1
		|| InDescs[0].GetShape().Rank() != 2 || InDescs[0].GetShape().GetData()[1] != ObsDim
		|| OutDescs[0].GetShape().Rank() != 2 || OutDescs[0].GetShape().GetData()[1] != NumActions)
	{
		OutError = FString::Printf(TEXT("unexpected tensor surface on '%s' (want 1 input [*,%d] -> 1 output [*,%d]) — wrong ONNX export?"),
			*InModelData->GetName(), ObsDim, NumActions);
		OutModel.Reset();
		OutInstance.Reset();
		return false;
	}

	// Mandatory before RunSync — IModelInstanceRunSync::SetInputTensorShapes
	// (NNERuntimeRunSync.h:82). Concrete shape [1,17]; FTensorShape::Make is
	// NNETypes.h:162.
	const uint32 ShapeData[] = { 1u, static_cast<uint32>(ObsDim) };
	const FTensorShape InputShape = FTensorShape::Make(ShapeData);
	if (OutInstance->SetInputTensorShapes(MakeArrayView(&InputShape, 1)) != EResultStatus::Ok)
	{
		OutError = TEXT("SetInputTensorShapes([1,17]) failed");
		OutModel.Reset();
		OutInstance.Reset();
		return false;
	}

	return true;
}

void UNNEBossPolicyComponent::BeginPlay()
{
	Super::BeginPlay();

	// Source switch (ROADMAP M5 step 4): `-rlbridge` = dev TCP/Python session —
	// NNE stands down for the whole run, the bridge (or its fallback brain) owns
	// the boss. Shipped builds never pass the flag.
	if (FParse::Param(FCommandLine::Get(), TEXT("rlbridge")))
	{
		bEnabled = false;
		UE_LOG(LogTemp, Log, TEXT("NNEBossPolicy: -rlbridge on command line — NNE policy disabled for this session (TCP bridge owns the boss)."));
		return;
	}

	AActor* Owner = GetOwner();
	if (!Owner) return;

	// Peer lookup, project convention: FindComponentByClass, no hard refs.
	BossAction = Owner->FindComponentByClass<UBossActionComponent>();
	ObsComp = Owner->FindComponentByClass<UStateObservationComponent>();
	Bridge = Owner->FindComponentByClass<URLBridgeComponent>();

	if (!BossAction.IsValid())
	{
		UE_LOG(LogTemp, Warning, TEXT("NNEBossPolicy: no BossActionComponent on '%s' — nothing to drive, staying dormant."), *Owner->GetName());
		return;
	}

	UNNEModelData* Data = ResolveModelData();
	if (!Data)
	{
		// Not a Warning: the auto-injected component legitimately idles until a
		// model is wired (BP or GameFeelSettings). The fallback scripted brain
		// still runs the boss via BossActionComponent's own watchdog.
		UE_LOG(LogTemp, Log, TEXT("NNEBossPolicy: no model data wired (ModelData / ArchetypeBank / GameFeelSettings) — dormant; scripted fallback brain covers the boss."));
		return;
	}

	FString Error;
	if (!CreateCpuInstanceForModel(Data, Model, ModelInstance, Error))
	{
		UE_LOG(LogTemp, Error, TEXT("NNEBossPolicy: model init failed: %s"), *Error);
		return;
	}

	InputBuffer.SetNumZeroed(ObsDim);
	OutputBuffer.SetNumZeroed(NumActions);

	UE_LOG(LogTemp, Display, TEXT("NNEBossPolicy: ready — model '%s' [%s] at %.0f Hz on %s."),
		*Data->GetName(), *SelectionSummary, DecisionHz, GNNEBossRuntimeName);

	GetWorld()->GetTimerManager().SetTimer(
		DecisionTimerHandle,
		FTimerDelegate::CreateUObject(this, &UNNEBossPolicyComponent::DecisionTick),
		1.0f / FMath::Max(DecisionHz, 1.0f), /*bLoop=*/true);
}

void UNNEBossPolicyComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (UWorld* World = GetWorld())
	{
		World->GetTimerManager().ClearTimer(DecisionTimerHandle);
	}
	ModelInstance.Reset();
	Model.Reset();
	Super::EndPlay(EndPlayReason);
}

void UNNEBossPolicyComponent::PopulateBankFromSettings()
{
	// A non-empty bank means either a BP author wired it (their table wins) or
	// we already populated on an earlier ResolveModelData call (RunSelfTest can
	// re-enter) — both cases: leave it alone.
	if (ArchetypeBank.Num() > 0)
	{
		return;
	}

	const UGameFeelSettings* Settings = GetDefault<UGameFeelSettings>();
	for (const FNNEArchetypeBankEntry& Row : Settings->NNEArchetypeBank)
	{
		if (Row.Persona.IsNone())
		{
			UE_LOG(LogTemp, Warning, TEXT("NNEBossPolicy: settings NNEArchetypeBank row with empty Persona — skipped."));
			continue;
		}
		if (!Row.ModelData.IsValid())
		{
			UE_LOG(LogTemp, Warning, TEXT("NNEBossPolicy: settings archetype '%s' has no ModelData path — skipped."),
				*Row.Persona.ToString());
			continue;
		}
		// Duplicate persona = authoring mistake with silent mis-pairing potential:
		// TMap::Add would REPLACE the model while the centroid array APPENDS, so
		// the cosine winner's centroid and the served model could come from
		// different rows. First row wins, later duplicates are skipped loudly.
		if (ArchetypeBank.Contains(Row.Persona))
		{
			UE_LOG(LogTemp, Warning, TEXT("NNEBossPolicy: duplicate settings archetype row for '%s' — skipped (first row wins)."),
				*Row.Persona.ToString());
			continue;
		}

		UNNEModelData* Loaded = Cast<UNNEModelData>(Row.ModelData.TryLoad());
		if (!Loaded)
		{
			UE_LOG(LogTemp, Warning, TEXT("NNEBossPolicy: settings archetype '%s' model '%s' failed to load as UNNEModelData — skipped."),
				*Row.Persona.ToString(), *Row.ModelData.ToString());
			continue;
		}

		// Rooted via the ArchetypeBank UPROPERTY for the component's lifetime.
		ArchetypeBank.Add(Row.Persona, Loaded);

		if (Row.Centroid.Num() == 8)
		{
			FArchetypeProfileEntry Entry;
			Entry.Persona = Row.Persona;
			Entry.Profile = Row.Centroid;
			SettingsCentroids.Add(MoveTemp(Entry));
		}
		else
		{
			UE_LOG(LogTemp, Warning, TEXT("NNEBossPolicy: settings archetype '%s' centroid has %d dims (want 8) — model kept, excluded from cosine selection."),
				*Row.Persona.ToString(), Row.Centroid.Num());
		}
	}

	if (ArchetypeBank.Num() > 0)
	{
		UE_LOG(LogTemp, Log, TEXT("NNEBossPolicy: archetype bank populated from GameFeelSettings — %d model(s), %d centroid(s)."),
			ArchetypeBank.Num(), SettingsCentroids.Num());
	}
}

UNNEModelData* UNNEBossPolicyComponent::ResolveModelData()
{
	SelectedArchetype = NAME_None;
	SelectionSummary = TEXT("<unresolved>");

	// 0) Settings-fed bank: the auto-injected component (GameFeelSubsystem
	//    NewObjects us — no BP property pass) gets its per-persona models and
	//    centroids from UGameFeelSettings::NNEArchetypeBank.
	PopulateBankFromSettings();

	// Centroid source: an explicit ArchetypeProfiles asset outranks the
	// settings-carried centroids (same precedence rule as ModelData vs settings).
	// Either source is FILTERED to personas that actually have a bank model:
	// a bank-less persona winning the cosine match would dead-end selection at
	// the global default while a second-best-but-available archetype goes
	// unused (easy to author with a 5-persona profiles asset over a 2-row bank).
	TArray<FArchetypeProfileEntry> SelectableCentroids;
	const TCHAR* CentroidSource = TEXT("");
	{
		const TArray<FArchetypeProfileEntry>* RawEntries = nullptr;
		if (ArchetypeProfiles && ArchetypeProfiles->Archetypes.Num() > 0)
		{
			RawEntries = &ArchetypeProfiles->Archetypes;
			CentroidSource = TEXT("ArchetypeProfiles asset");
		}
		else if (SettingsCentroids.Num() > 0)
		{
			// Bank-backed by construction (PopulateBankFromSettings only keeps
			// centroids whose model loaded) — the filter is a no-op here.
			RawEntries = &SettingsCentroids;
			CentroidSource = TEXT("GameFeelSettings centroids");
		}
		if (RawEntries)
		{
			for (const FArchetypeProfileEntry& Entry : *RawEntries)
			{
				if (ArchetypeBank.Contains(Entry.Persona))
				{
					SelectableCentroids.Add(Entry);
				}
				else
				{
					UE_LOG(LogTemp, Warning, TEXT("NNEBossPolicy: centroid '%s' (%s) has no model in ArchetypeBank — excluded from selection."),
						*Entry.Persona.ToString(), CentroidSource);
				}
			}
		}
	}

	// 1) Archetype bank: pick the persona nearest to the player's STORED profile.
	//    PlayerMemoryComponent carries the cross-encounter decayed profile in from
	//    the patrol fights (M3), so a returning player meets a pre-adapted boss.
	//    Zero encounters = default profile = no signal — skip selection rather
	//    than cosine-matching noise.
	if (SelectableCentroids.Num() > 0)
	{
		if (AActor* Owner = GetOwner())
		{
			if (UPlayerMemoryComponent* Memory = Owner->FindComponentByClass<UPlayerMemoryComponent>())
			{
				if (Memory->GetTotalEncounters() > 0)
				{
					const TArray<float> StoredProfile = Memory->GetDecayedProfile().ToFloatArray();
					float BestCos = -2.0f;
					const FName Best = UArchetypeProfilesAsset::SelectFromEntries(SelectableCentroids, StoredProfile, BestCos);
					if (!Best.IsNone())
					{
						if (const TObjectPtr<UNNEModelData>* Found = ArchetypeBank.Find(Best))
						{
							if (*Found)
							{
								SelectedArchetype = Best;
								SelectionConfidence = BestCos;
								SelectionSummary = FString::Printf(TEXT("archetype: %s (cos=%.2f)"), *Best.ToString(), BestCos);
								UE_LOG(LogTemp, Display, TEXT("NNEBossPolicy: %s — matched stored player profile (%d encounters, centroids: %s, model '%s')."),
									*SelectionSummary, Memory->GetTotalEncounters(), CentroidSource, *(*Found)->GetName());
								return *Found;
							}
						}
						UE_LOG(LogTemp, Warning, TEXT("NNEBossPolicy: archetype '%s' won the cosine match (%.2f) but has no model in ArchetypeBank — falling back."),
							*Best.ToString(), BestCos);
					}
				}
				else
				{
					UE_LOG(LogTemp, Log, TEXT("NNEBossPolicy: player memory has 0 encounters (default profile) — skipping archetype match."));
				}
			}
		}
	}

	// 1.5) Tier 4 biome fallback: when the profile cosine match didn't return
	//      (empty bank, zero encounters, or no candidate above threshold), let
	//      the encounter volume's PreferredPersonaFallback pick from the bank.
	//      Bio design contract: cosine match on a real player profile still
	//      wins — this only fires for new / guest players in a biome where
	//      the level author declared an intent.
	if (!PreferredPersonaOverride.IsNone())
	{
		if (const TObjectPtr<UNNEModelData>* Found = ArchetypeBank.Find(PreferredPersonaOverride))
		{
			if (*Found)
			{
				SelectedArchetype = PreferredPersonaOverride;
				SelectionSummary = FString::Printf(TEXT("archetype: %s (biome-preferred fallback)"),
					*PreferredPersonaOverride.ToString());
				UE_LOG(LogTemp, Display, TEXT("NNEBossPolicy: %s ('%s')."), *SelectionSummary, *(*Found)->GetName());
				return *Found;
			}
		}
		UE_LOG(LogTemp, Warning, TEXT("NNEBossPolicy: PreferredPersonaOverride '%s' has no model in ArchetypeBank — continuing to default."),
			*PreferredPersonaOverride.ToString());
	}

	// 2) Explicit fallback model.
	if (ModelData)
	{
		SelectionSummary = TEXT("default: explicit ModelData property");
		UE_LOG(LogTemp, Display, TEXT("NNEBossPolicy: %s ('%s')."), *SelectionSummary, *ModelData->GetName());
		return ModelData;
	}

	// 3) Settings-driven default — the wiring path for the auto-injected
	//    component when no archetype matched.
	const FSoftObjectPath& SettingsPath = GetDefault<UGameFeelSettings>()->NNEBossModelData;
	if (SettingsPath.IsValid())
	{
		if (UNNEModelData* Loaded = Cast<UNNEModelData>(SettingsPath.TryLoad()))
		{
			ModelData = Loaded; // keep a strong ref for the model's lifetime
			SelectionSummary = TEXT("default: GameFeelSettings NNEBossModelData");
			UE_LOG(LogTemp, Display, TEXT("NNEBossPolicy: %s ('%s')."), *SelectionSummary, *Loaded->GetName());
			return Loaded;
		}
		UE_LOG(LogTemp, Warning, TEXT("NNEBossPolicy: GameFeelSettings NNEBossModelData '%s' failed to load as UNNEModelData."),
			*SettingsPath.ToString());
	}

	// 4) Bank present but no memory/table match: first valid entry beats dormancy.
	for (const TPair<FName, TObjectPtr<UNNEModelData>>& Pair : ArchetypeBank)
	{
		if (Pair.Value)
		{
			SelectedArchetype = Pair.Key;
			SelectionSummary = FString::Printf(TEXT("archetype: %s (no profile match — first bank entry)"), *Pair.Key.ToString());
			UE_LOG(LogTemp, Display, TEXT("NNEBossPolicy: %s."), *SelectionSummary);
			return Pair.Value;
		}
	}

	return nullptr;
}

void UNNEBossPolicyComponent::DecisionTick()
{
	if (!bEnabled || !ModelInstance.IsValid()) return;

	// The bridge always outranks NNE: while a Python client is attached, stand
	// aside completely (cheap poll — IsClientConnected is a socket-state read).
	// Transient by design: NNE resumes the moment the client disconnects.
	if (Bridge.IsValid() && Bridge->IsClientConnected()) return;

	UBossActionComponent* Action = BossAction.Get();
	if (!Action || Action->IsDead()) return;

	UStateObservationComponent* Obs = ObsComp.Get();
	if (!Obs)
	{
		if (!bWarnedNoObsComp)
		{
			bWarnedNoObsComp = true;
			UE_LOG(LogTemp, Warning, TEXT("NNEBossPolicy: no StateObservationComponent on the boss — cannot build observations."));
		}
		return;
	}

	// Mirror BossActionComponent's TargetActor auto-acquire: HeroActor is a public
	// UPROPERTY the BP normally assigns; in a Python-free launch nothing else sets
	// it, so acquire the player pawn here (no accessor added to the obs component).
	if (!Obs->HeroActor)
	{
		Obs->HeroActor = UGameplayStatics::GetPlayerPawn(this, 0);
		if (!Obs->HeroActor) return; // pawn not spawned yet — retry next decision
	}

	// THE obs-mirror strategy: no mirroring at all. CollectObservation() +
	// ToFloatArray() is the exact 17-float vector (order + normalization) the
	// bridge serializes to Python — one producer, zero drift. Extension dims
	// (hero_action/emotion) are separate JSON fields appended Python-side and
	// are NOT part of the 17-dim base policy input.
	InputBuffer = Obs->CollectObservation().ToFloatArray();
	if (InputBuffer.Num() != ObsDim)
	{
		if (!bWarnedBadObsSize)
		{
			bWarnedBadObsSize = true;
			UE_LOG(LogTemp, Error, TEXT("NNEBossPolicy: observation is %d dims, model expects %d — check StateObservationComponent::GetObservationSize()."),
				InputBuffer.Num(), ObsDim);
		}
		return;
	}

	if (!RunInference()) return;

	// Masked argmax — the exported graph is mask-free (export_onnx.py G7); the
	// consumer applies legality exactly like MaskablePPO did in training: illegal
	// logits to -FLT_MAX, then argmax. GetLegalActionMask() is the same predicate
	// ApplyActionMask enforces downstream, so this only saves wasted substitutions.
	const TArray<bool> Mask = Action->GetLegalActionMask();
	int32 BestIdx = 0;
	float BestLogit = -FLT_MAX;
	for (int32 i = 0; i < NumActions; ++i)
	{
		const float Logit = (Mask.IsValidIndex(i) && !Mask[i]) ? -FLT_MAX : OutputBuffer[i];
		if (Logit > BestLogit)
		{
			BestLogit = Logit;
			BestIdx = i;
		}
	}

	// Same entry point the bridge uses — Phase 4 gates (commitment, hysteresis,
	// recovery, reacting) all apply downstream; ExecuteAction also refreshes the
	// bridge watchdog, which parks the scripted fallback brain while NNE drives.
	LastChosenAction = BestIdx;
	Action->ExecuteAction(BestIdx);
}

bool UNNEBossPolicyComponent::RunInference()
{
	// IModelInstanceRunSync::RunSync with caller-owned CPU bindings
	// (NNERuntimeRunSync.h:18/96). Game thread at 15 Hz is fine for this MLP —
	// the same budget the TCP round-trip used to spend.
	UE::NNE::FTensorBindingCPU InputBinding{ InputBuffer.GetData(), InputBuffer.Num() * sizeof(float) };
	UE::NNE::FTensorBindingCPU OutputBinding{ OutputBuffer.GetData(), OutputBuffer.Num() * sizeof(float) };

	if (ModelInstance->RunSync(MakeArrayView(&InputBinding, 1), MakeArrayView(&OutputBinding, 1))
		!= UE::NNE::EResultStatus::Ok)
	{
		if (!bWarnedInferenceFailed)
		{
			bWarnedInferenceFailed = true;
			UE_LOG(LogTemp, Error, TEXT("NNEBossPolicy: RunSync failed — boss falls back to the scripted brain."));
		}
		return false;
	}
	return true;
}

bool UNNEBossPolicyComponent::RunSelfTest(FString& OutSummary)
{
	TSharedPtr<UE::NNE::IModelCPU> LocalModel;
	TSharedPtr<UE::NNE::IModelInstanceCPU> Instance = ModelInstance;

	if (!Instance.IsValid())
	{
		UNNEModelData* Data = ResolveModelData();
		if (!Data)
		{
			OutSummary = TEXT("no model data resolvable (ModelData / ArchetypeBank / GameFeelSettings all empty)");
			return false;
		}
		FString Error;
		if (!CreateCpuInstanceForModel(Data, LocalModel, Instance, Error))
		{
			OutSummary = FString::Printf(TEXT("init failed: %s"), *Error);
			return false;
		}
	}

	TArray<float> Zeros;
	Zeros.SetNumZeroed(ObsDim);
	TArray<float> Logits;
	Logits.SetNumZeroed(NumActions);

	UE::NNE::FTensorBindingCPU In{ Zeros.GetData(), Zeros.Num() * sizeof(float) };
	UE::NNE::FTensorBindingCPU Out{ Logits.GetData(), Logits.Num() * sizeof(float) };
	if (Instance->RunSync(MakeArrayView(&In, 1), MakeArrayView(&Out, 1)) != UE::NNE::EResultStatus::Ok)
	{
		OutSummary = TEXT("RunSync failed on zeros observation");
		return false;
	}

	int32 BestIdx = 0;
	for (int32 i = 1; i < NumActions; ++i)
	{
		if (Logits[i] > Logits[BestIdx]) BestIdx = i;
	}

	static const TCHAR* ActionNames[] = { TEXT("Attack"), TEXT("Block"), TEXT("Dodge"), TEXT("Approach"), TEXT("Retreat") };
	OutSummary = FString::Printf(TEXT("logits=[%.4f, %.4f, %.4f, %.4f, %.4f] argmax=%d (%s)"),
		Logits[0], Logits[1], Logits[2], Logits[3], Logits[4], BestIdx, ActionNames[BestIdx]);

	// Masked pick too, when the executor is reachable — exercises the exact
	// runtime decision path (mask source included).
	if (UBossActionComponent* Action = BossAction.Get())
	{
		const TArray<bool> Mask = Action->GetLegalActionMask();
		int32 MaskedIdx = 0;
		float MaskedBest = -FLT_MAX;
		FString MaskStr;
		for (int32 i = 0; i < NumActions; ++i)
		{
			const bool bLegal = Mask.IsValidIndex(i) ? Mask[i] : true;
			MaskStr += bLegal ? TEXT("1") : TEXT("0");
			const float L = bLegal ? Logits[i] : -FLT_MAX;
			if (L > MaskedBest) { MaskedBest = L; MaskedIdx = i; }
		}
		OutSummary += FString::Printf(TEXT(" | mask=%s maskedArgmax=%d (%s)"),
			*MaskStr, MaskedIdx, ActionNames[MaskedIdx]);
	}

	return true;
}

// ---------------------------------------------------------------------------
// boss.NNESelfTest — headless pipeline verification
//   Usage:  boss.NNESelfTest                       (live component, else default asset)
//           boss.NNESelfTest /Game/Path/To/Model    (standalone asset test)
//   Headless: -game -RenderOffscreen -ExecCmds="boss.NNESelfTest, quit"
// ---------------------------------------------------------------------------

static void BossNNESelfTestStandalone(const FString& AssetPath)
{
	UNNEModelData* Data = LoadObject<UNNEModelData>(nullptr, *AssetPath);
	if (!Data)
	{
		UE_LOG(LogTemp, Error, TEXT("boss.NNESelfTest: FAIL — could not load '%s' as UNNEModelData."), *AssetPath);
		return;
	}

	TSharedPtr<UE::NNE::IModelCPU> Model;
	TSharedPtr<UE::NNE::IModelInstanceCPU> Instance;
	FString Error;
	if (!UNNEBossPolicyComponent::CreateCpuInstanceForModel(Data, Model, Instance, Error))
	{
		UE_LOG(LogTemp, Error, TEXT("boss.NNESelfTest: FAIL — %s"), *Error);
		return;
	}

	TArray<float> Zeros;
	Zeros.SetNumZeroed(UNNEBossPolicyComponent::ObsDim);
	TArray<float> Logits;
	Logits.SetNumZeroed(UNNEBossPolicyComponent::NumActions);
	UE::NNE::FTensorBindingCPU In{ Zeros.GetData(), Zeros.Num() * sizeof(float) };
	UE::NNE::FTensorBindingCPU Out{ Logits.GetData(), Logits.Num() * sizeof(float) };
	if (Instance->RunSync(MakeArrayView(&In, 1), MakeArrayView(&Out, 1)) != UE::NNE::EResultStatus::Ok)
	{
		UE_LOG(LogTemp, Error, TEXT("boss.NNESelfTest: FAIL — RunSync failed on '%s'."), *AssetPath);
		return;
	}

	int32 BestIdx = 0;
	for (int32 i = 1; i < UNNEBossPolicyComponent::NumActions; ++i)
	{
		if (Logits[i] > Logits[BestIdx]) BestIdx = i;
	}
	UE_LOG(LogTemp, Display, TEXT("boss.NNESelfTest: PASS (standalone '%s') logits=[%.4f, %.4f, %.4f, %.4f, %.4f] argmax=%d"),
		*AssetPath, Logits[0], Logits[1], Logits[2], Logits[3], Logits[4], BestIdx);
}

static void BossNNESelfTest(const TArray<FString>& Args)
{
	// Explicit asset path: pure asset->runtime->inference check, no world needed.
	if (Args.Num() > 0)
	{
		BossNNESelfTestStandalone(Args[0]);
		return;
	}

	// Else prefer a live component in a game world (tests the real wiring:
	// archetype resolve + mask source included).
	for (TObjectIterator<UNNEBossPolicyComponent> It; It; ++It)
	{
		UNNEBossPolicyComponent* Comp = *It;
		if (!Comp || Comp->HasAnyFlags(RF_ClassDefaultObject | RF_ArchetypeObject)) continue;
		UWorld* World = Comp->GetWorld();
		if (!World || !World->IsGameWorld()) continue;

		FString Summary;
		const bool bOk = Comp->RunSelfTest(Summary);
		if (bOk)
		{
			UE_LOG(LogTemp, Display, TEXT("boss.NNESelfTest: PASS (component on '%s') %s"),
				*GetNameSafe(Comp->GetOwner()), *Summary);
		}
		else
		{
			UE_LOG(LogTemp, Error, TEXT("boss.NNESelfTest: FAIL (component on '%s') %s"),
				*GetNameSafe(Comp->GetOwner()), *Summary);
		}
		return;
	}

	// No component anywhere (bare level / early ExecCmds) — standalone fallback.
	// Prefer the shipped wiring point (GameFeelSettings::NNEBossModelData) so the
	// self-test exercises the asset the injected boss will actually load; the
	// hardcoded untrained-model path is last resort for a blank project.
	const FSoftObjectPath& SettingsPath = GetDefault<UGameFeelSettings>()->NNEBossModelData;
	const bool bFromSettings = SettingsPath.IsValid();
	const FString AssetPath = bFromSettings ? SettingsPath.ToString() : FString(GNNEBossSelfTestDefaultAsset);
	UE_LOG(LogTemp, Warning, TEXT("boss.NNESelfTest: no live UNNEBossPolicyComponent found — using %s: %s"),
		bFromSettings ? TEXT("GameFeelSettings.NNEBossModelData") : TEXT("hardcoded untrained-model default (setting is empty)"),
		*AssetPath);
	BossNNESelfTestStandalone(AssetPath);
}

static FAutoConsoleCommand GBossNNESelfTestCmd(
	TEXT("boss.NNESelfTest"),
	TEXT("Run one NNE boss-policy inference on a zeros observation and log the 5 logits + chosen action. ")
	TEXT("Optional arg: UNNEModelData asset path (default: live component, else GameFeelSettings.NNEBossModelData, else /Game/Arena/Models/NNM_BossUntrained)."),
	FConsoleCommandWithArgsDelegate::CreateStatic(&BossNNESelfTest));
