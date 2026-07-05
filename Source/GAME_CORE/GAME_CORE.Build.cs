using UnrealBuildTool;

public class GAME_CORE : ModuleRules
{
    public GAME_CORE(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new string[] {
            "Core", "CoreUObject", "Engine", "InputCore", "EnhancedInput",
            "MotionWarping", "Mover",
            "EngineCameras",  // UDefaultCameraShakeBase / PerlinNoiseCameraShakePattern moved here in UE 5.8
            "DeveloperSettings",  // UGameFeelSettings : UDeveloperSettings
            "AIModule", "NavigationSystem", "GameplayTasks",
            "UMG", "Slate", "SlateCore",
            "NNE",   // M5: NNEBossPolicyComponent in-engine ONNX inference
            "HTTP",  // M6: Firebase REST auth + Firestore telemetry upload
            "Sockets", "Networking", "Json", "JsonUtilities"
        });

        // Editor-only deps (ArenaEditorTools brush spawning). Guarded so
        // packaged / -game builds never link editor modules.
        if (Target.bBuildEditor)
        {
            PrivateDependencyModuleNames.AddRange(new string[] {
                "UnrealEd", "EditorFramework"
            });
        }
    }
}