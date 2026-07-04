"""
Algorithm selection / checkpoint helpers for the MaskablePPO upgrade.

Centralizes:
  - config-driven PPO vs MaskablePPO resolution (training.algorithm)
  - legacy-vs-maskable checkpoint sniffing (the only discriminator, see G3)
  - auto-loading either checkpoint kind
  - the canonical ActionMasker wrapping (gymnasium 1.2.x dropped wrapper
    attribute forwarding, so mask discovery must go through env.unwrapped)
"""

import glob
import os
import zipfile

# Heartbeat no-op: BossActionComponent::ExecuteAction refreshes the 45s
# connected-watchdog BEFORE its range check rejects -1 with only a log
# warning, and RLBridgeComponent never replies — so {"action": -1} keeps
# the bridge alive during learn() pauses without dispatching anything or
# desyncing newline framing (G4).
HEARTBEAT_NOOP_ACTION = -1


def resolve_algo(cfg: dict):
    """Return (AlgoCls, name, maskable) from cfg["training"]["algorithm"]."""
    raw = cfg.get("training", {}).get("algorithm", "PPO")
    name = raw.upper().replace("_", "").replace("-", "")

    if name == "PPO":
        from stable_baselines3 import PPO
        return PPO, "PPO", False

    if name == "MASKABLEPPO":
        # Import inside the branch so plain-PPO works without sb3-contrib.
        try:
            from sb3_contrib import MaskablePPO
        except ImportError:
            raise SystemExit(
                "training.algorithm is MaskablePPO but sb3-contrib is not "
                "installed. Install with: pip install \"sb3-contrib==2.9.*\""
            )
        return MaskablePPO, "MaskablePPO", True

    raise ValueError(
        f"Unsupported algorithm: {raw!r}. Use \"PPO\" or \"MaskablePPO\"."
    )


def checkpoint_is_maskable(path: str) -> bool:
    """
    True iff the SB3 .zip checkpoint was saved by MaskablePPO.

    An SB3 zip stores a "data" JSON member; "MaskableActorCriticPolicy" /
    "sb3_contrib" appears in it iff the checkpoint is MaskablePPO (G3).
    Returns False on any read error (treat unreadable as legacy PPO).
    """
    try:
        with zipfile.ZipFile(path) as zf:
            data = zf.read("data").decode("utf-8", errors="replace")
        return "MaskableActorCriticPolicy" in data or "sb3_contrib" in data
    except (OSError, KeyError, zipfile.BadZipFile):
        return False


def load_checkpoint_auto(path, env=None, device="cpu"):
    """
    Load a checkpoint with the algorithm that saved it.
    Returns (model, mask_aware: bool).
    """
    if checkpoint_is_maskable(path):
        try:
            from sb3_contrib import MaskablePPO
        except ImportError:
            raise SystemExit(
                f"Checkpoint {path} is MaskablePPO but sb3-contrib is not "
                "installed. Install with: pip install \"sb3-contrib==2.9.*\""
            )
        return MaskablePPO.load(path, env=env, device=device), True

    from stable_baselines3 import PPO
    return PPO.load(path, env=env, device=device), False


def wrap_action_masker(env):
    """
    Wrap with ActionMasker as the OUTERMOST training wrapper (outside
    Monitor): gymnasium 1.2.x no longer forwards attributes through
    wrappers, and DummyVecEnv.env_method("action_masks") getattrs the
    outermost env — so the mask fn must reach the base env explicitly
    via env.unwrapped (G2).
    """
    from sb3_contrib.common.wrappers import ActionMasker
    return ActionMasker(env, lambda e: e.unwrapped.action_masks())


def find_latest_checkpoint(checkpoint_dir: str):
    """Newest *.zip in checkpoint_dir by mtime, or None."""
    zips = glob.glob(os.path.join(checkpoint_dir, "*.zip"))
    if not zips:
        return None
    return max(zips, key=os.path.getmtime)
