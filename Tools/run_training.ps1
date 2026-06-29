# ════════════════════════════════════════════════════════════════════════════
# GAME_CORE unattended training harness (ROADMAP.md milestone M1)
#
# Launches the game standalone (small window, low res = low GPU load) together
# with the Python RL trainer, keeps both alive, and restarts the pair if either
# dies. Designed for overnight runs on the dev laptop.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File "D:\GAME_CORE 5.8\Tools\run_training.ps1"
#   ... -MapName Arena            # optional: level to load (omit = project default map)
#   ... -Persona rusher           # optional: forwarded as -AutoHero=<persona> once
#                                 #   the AutoHeroComponent exists (M1) -- harmless before
#   ... -TrainScript train.py     # or train_hierarchical.py etc.
#   ... -MaxRestarts 50
#
# Stop with Ctrl+C -- both processes are cleaned up.
# NOTE: close the UE *editor* first; a -game instance can run alongside it,
# but on 16 GB RAM editor + game + torch will page and ruin throughput.
# ════════════════════════════════════════════════════════════════════════════

param(
    [string]$MapName = "",
    [string]$Persona = "",
    [string]$TrainScript = "train.py",
    [int]$ResX = 640,
    [int]$ResY = 360,
    [int]$MaxRestarts = 50,
    [int]$StartupGraceSeconds = 90   # UE must finish loading + (first run) shader compile
                                     # before the trainer connects, else ConnectionRefused

)

$Engine  = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe"
$Project = "D:\GAME_CORE 5.8\GAME_CORE.uproject"
$Python  = "D:\GAME_CORE 5.8\Python\venv\Scripts\python.exe"
$PyDir   = "D:\GAME_CORE 5.8\Python"
$LogDir  = "D:\GAME_CORE 5.8\Tools\logs"

if (-not (Test-Path $Engine))  { Write-Error "UE not found at $Engine"; exit 1 }
if (-not (Test-Path $Python))  { Write-Error "venv python not found at $Python"; exit 1 }
New-Item -ItemType Directory -Force $LogDir | Out-Null

$ueArgs = @()
if ($MapName -ne "") { $ueArgs += $MapName }
$ueArgs += @("-game", "-windowed", "-ResX=$ResX", "-ResY=$ResY", "-nosplash", "-log")
if ($Persona -ne "") { $ueArgs += "-AutoHero=$Persona" }

function Stop-Pair($ue, $py) {
    foreach ($p in @($py, $ue)) {
        if ($null -ne $p -and -not $p.HasExited) {
            try { Stop-Process -Id $p.Id -Force -ErrorAction Stop } catch {}
        }
    }
}

$restarts = 0
$ue = $null
$py = $null

try {
    while ($restarts -lt $MaxRestarts) {
        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        Write-Host ("[{0}] === Run {1}/{2} -- UE: {3} {4} ===" -f (Get-Date -Format T), ($restarts + 1), $MaxRestarts, $Project, ($ueArgs -join " "))

        $ue = Start-Process -FilePath $Engine -ArgumentList (@("`"$Project`"") + $ueArgs) -PassThru
        Write-Host ("[{0}] UE pid {1} -- waiting {2}s for the TCP bridge to come up..." -f (Get-Date -Format T), $ue.Id, $StartupGraceSeconds)
        Start-Sleep -Seconds $StartupGraceSeconds

        if ($ue.HasExited) {
            Write-Warning "UE exited during startup (code $($ue.ExitCode)). Restarting."
            $restarts++
            continue
        }

        $pyLog = Join-Path $LogDir "train_$stamp.log"
        # Persona doubles as the synthetic player_id so replays/<persona>/ stays
        # separated per play-style (MAML/transfer task splits key off the folder).
        $pyArgs = @($TrainScript)
        if ($Persona -ne "") { $pyArgs += @("--player-id", $Persona) }
        $py = Start-Process -FilePath $Python -ArgumentList $pyArgs -WorkingDirectory $PyDir `
            -RedirectStandardOutput $pyLog -RedirectStandardError (Join-Path $LogDir "train_$stamp.err.log") -PassThru -NoNewWindow
        Write-Host ("[{0}] Trainer pid {1} -- log: {2}" -f (Get-Date -Format T), $py.Id, $pyLog)

        # Babysit: wake every 30 s, restart the pair if either side died.
        while ($true) {
            Start-Sleep -Seconds 30
            if ($ue.HasExited) {
                Write-Warning ("UE died (code {0}) -- recycling pair." -f $ue.ExitCode)
                break
            }
            if ($py.HasExited) {
                Write-Warning ("Trainer exited (code {0}) -- recycling pair. Check {1}" -f $py.ExitCode, $pyLog)
                break
            }
        }

        Stop-Pair $ue $py
        $restarts++
        Start-Sleep -Seconds 5   # let sockets/file handles release
    }
    Write-Host "Reached MaxRestarts ($MaxRestarts). Done."
}
finally {
    # Ctrl+C lands here -- leave nothing running.
    Stop-Pair $ue $py
    Write-Host "Cleaned up. Checkpoints live in D:\GAME_CORE 5.8\Python\checkpoints, TensorBoard logs in Python\tb_logs."
}
