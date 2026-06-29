using UnrealBuildTool;

public class GAME_CORE : ModuleRules
{
    public GAME_CORE(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new string[] {
            "Core", "CoreUObject", "Engine", "InputCore", "EnhancedInput",
            "MotionWarping", "Mover",
            "Sockets", "Networking", "Json", "JsonUtilities"
        });
    }
}