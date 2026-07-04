"""End-to-end smoke test for the MaskablePPO upgrade — NO UE required.

Spins up tests/mock_ue_server.MockUEServer (speaks the exact RLBridge
NDJSON protocol) and drives the real training stack against it:

  BossEnv <-> MockUEServer          (bridge protocol, mask plumbing, heartbeat)
  train.train()                     (make_env wrapping order, MaskablePPO learn,
                                     ReplayRecorder, checkpoints)
  rl_algo                           (resolve_algo, checkpoint sniffing,
                                     load_checkpoint_auto, masked predict)

Run from the Python/ directory with the venv interpreter:
  venv\\Scripts\\python.exe smoke_test.py

Exit code 0 iff every assertion passes. Total runtime should be well
under a minute on the dev laptop.
"""

from __future__ import annotations

import copy
import os
import shutil
import sys
import tempfile
import time

# Run relative to this file so config.yaml / tests/ resolve regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "tests"))

import numpy as np
import yaml

from mock_ue_server import MockUEServer  # tests/
from boss_env import BossEnv
from rl_algo import (
    checkpoint_is_maskable,
    load_checkpoint_auto,
    resolve_algo,
)

PASSED: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    if not cond:
        raise AssertionError(f"{name}{': ' + detail if detail else ''}")
    PASSED.append(name)
    print(f"  PASS  {name}")


def load_cfg() -> dict:
    with open(os.path.join(_HERE, "config.yaml"), "r") as f:
        return yaml.safe_load(f)


# --------------------------------------------------------------------------- #
def smoke_resolve_algo(cfg):
    print("[1] rl_algo.resolve_algo on shipped config.yaml")
    algo_cls, name, maskable = resolve_algo(cfg)
    check("resolve_algo returns shipped algorithm",
          name == cfg["training"].get("algorithm", "PPO"))
    if name == "MaskablePPO":
        check("MaskablePPO resolves maskable=True", maskable is True)
        check("resolved class is sb3_contrib.MaskablePPO",
              algo_cls.__module__.startswith("sb3_contrib"))


def smoke_bridge_protocol():
    print("[2] BossEnv <-> mock bridge protocol")
    with MockUEServer() as server:
        server.hero_hp = 0.25
        server.boss_hp = 0.75
        server.dist = 0.4
        server.reset_restores_hp = False  # keep scripted values through reset

        env = BossEnv(host="127.0.0.1", port=server.port,
                      timeout=5.0, step_delay=0.0, player_id="smoke")
        try:
            obs, _ = env.reset()
            check("reset() returns 17-dim float32 obs",
                  obs.shape == (17,) and obs.dtype == np.float32,
                  f"shape={obs.shape} dtype={obs.dtype}")
            check("obs field mapping (hero_hp/dist/boss_hp)",
                  abs(obs[5] - 0.25) < 1e-6 and abs(obs[6] - 0.4) < 1e-6
                  and abs(obs[8] - 0.75) < 1e-6)
            check("set_player_id reached the bridge",
                  server.wait_for(lambda s: "smoke" in s.player_ids))
            check("default mask is all-legal",
                  env.action_masks().all() and env.action_masks().shape == (5,))

            # Restricted mask propagates
            server.mask = [1, 0, 1, 0, 1]
            obs, _, _, _, info = env.step(0)
            check("restricted mask propagates to action_masks()",
                  np.array_equal(env.action_masks(),
                                 np.array([True, False, True, False, True])))
            check("info carries the action_mask",
                  np.array_equal(info["action_mask"], env.action_masks()))

            # All-zero mask -> all-ones fallback (all-zero would crash MaskablePPO)
            server.mask = [0, 0, 0, 0, 0]
            env.step(2)
            check("all-zero mask falls back to all-ones", env.action_masks().all())

            # Malformed mask -> all-ones fallback
            server.extra_obs_fields = {"mask": "garbage"}
            env.step(2)
            check("malformed mask falls back to all-ones", env.action_masks().all())
            server.extra_obs_fields = {}

            # Unsolicited SendReward line must be skipped, not parsed as obs
            server.inject_lines = ['{"reward": 1.5}']
            obs, _, _, _, _ = env.step(3)
            check("unsolicited reward line skipped (obs stays sane)",
                  abs(obs[8] - 0.75) < 1e-6)

            check("bridge dispatched actions in order",
                  server.wait_for(lambda s: s.actions[:4] == [0, 2, 2, 3]))
        finally:
            env.close()


def smoke_heartbeat():
    print("[3] heartbeat no-op keeps bridge alive without desync")
    with MockUEServer() as server:
        env = BossEnv(host="127.0.0.1", port=server.port, timeout=5.0,
                      step_delay=0.0, player_id="smoke",
                      heartbeat_interval=0.2)
        try:
            env.reset()
            check("heartbeat {action:-1} arrives during send silence",
                  server.wait_for(lambda s: -1 in s.actions, timeout=3.0))
            obs, _, _, _, _ = env.step(1)  # bridge must still be in sync
            check("bridge still in sync after heartbeat", obs.shape == (17,))
            check("real action still dispatched after heartbeat",
                  server.wait_for(lambda s: 1 in s.actions))
        finally:
            env.close()


def smoke_combined_message_dropped():
    print("[3b] combined action+command line drops the command (bridge parity)")
    import socket as _socket

    with MockUEServer() as server:
        conn = _socket.create_connection(("127.0.0.1", server.port), timeout=2.0)
        try:
            # Real RLBridgeComponent::ProcessMessage returns right after the
            # "action" field — the bundled command must yield NO reply.
            conn.sendall(b'{"action": 3, "command": "observe"}\n')
            check("combined line: action still dispatched",
                  server.wait_for(lambda s: 3 in s.actions))
            check("combined line: command NOT dispatched",
                  "observe" not in server.commands)
            conn.settimeout(0.5)
            got_reply = True
            try:
                got_reply = bool(conn.recv(4096))
            except _socket.timeout:
                got_reply = False
            check("combined line: no observation reply sent", not got_reply)

            # Sanity: a standalone observe on the same connection still replies.
            conn.settimeout(2.0)
            conn.sendall(b'{"command": "observe"}\n')
            reply = conn.recv(4096)
            check("standalone observe still replied after combined line",
                  reply.endswith(b"\n") and b"boss_hp" in reply)
        finally:
            conn.close()


def smoke_training(cfg, workdir):
    print("[4] train.train() end-to-end (MaskablePPO x mock bridge)")
    import train as train_mod

    with MockUEServer() as server:
        server.mask = [1, 0, 0, 1, 0]  # only Attack / Approach legal

        tcfg = copy.deepcopy(cfg)
        tcfg["env"].update({
            "host": "127.0.0.1", "port": server.port, "timeout": 5.0,
            "step_delay": 0.0, "max_steps": 8, "player_id": "smoke",
            "heartbeat_interval": 0.0,
        })
        tcfg["training"].update({
            "algorithm": "MaskablePPO", "total_timesteps": 32,
            "n_steps": 16, "batch_size": 16, "n_epochs": 1,
            "device": "cpu", "seed": 7,
        })
        tcfg["logging"] = {
            "tensorboard_dir": os.path.join(workdir, "tb"),
            "checkpoint_dir": os.path.join(workdir, "ckpt"),
            "checkpoint_freq": 100000, "log_interval": 1,
        }
        tcfg["transfer"]["record_replays"] = True
        tcfg["transfer"]["replay_dir"] = os.path.join(workdir, "replays")
        tcfg["constraints"]["enabled"] = False

        train_mod.train(tcfg)

        final = os.path.join(workdir, "ckpt", "final_model.zip")
        check("train() completed and saved final_model.zip", os.path.isfile(final))

        real_actions = [a for a in server.actions if a >= 0]
        check("training drove the bridge (>=32 actions)", len(real_actions) >= 32,
              f"got {len(real_actions)}")
        illegal = sorted(set(real_actions) - {0, 3})
        check("MaskablePPO honored the mask (only legal actions sent)",
              not illegal, f"illegal actions: {illegal}")
        check("bridge saw resets (round-trip reconnects)",
              server.commands.count("reset") >= 2)

        # Replay dataset actually written
        replay_dir = os.path.join(workdir, "replays", "smoke")
        npz_files = [f for f in os.listdir(replay_dir)
                     if f.endswith(".npz")] if os.path.isdir(replay_dir) else []
        check("ReplayRecorder wrote episode .npz files", len(npz_files) >= 1)
        data = np.load(os.path.join(replay_dir, sorted(npz_files)[0]))
        missing = {"obs", "actions", "rewards", "next_obs", "dones"} - set(data.files)
        check("replay schema has obs/actions/rewards/next_obs/dones",
              not missing, f"missing {missing}")
        check("replay obs are 17-dim", data["obs"].shape[1] == 17)

        return final


def smoke_checkpoints(final_ckpt, workdir):
    print("[5] checkpoint sniffing + auto-load + masked predict")
    check("maskable checkpoint sniffed as maskable",
          checkpoint_is_maskable(final_ckpt) is True)

    model, mask_aware = load_checkpoint_auto(final_ckpt, env=None, device="cpu")
    check("load_checkpoint_auto -> mask_aware=True", mask_aware is True)

    obs = np.zeros(17, dtype=np.float32)
    only_block = np.array([False, True, False, False, False])
    action, _ = model.predict(obs, action_masks=only_block, deterministic=True)
    check("masked predict() respects a 1-hot mask", int(action) == 1,
          f"predicted {int(action)}")

    # Legacy PPO checkpoint: sniffed as legacy, loads via PPO
    import gymnasium as gym
    from gymnasium import spaces
    from stable_baselines3 import PPO

    class _StubEnv(gym.Env):
        observation_space = spaces.Box(-np.inf, np.inf, (17,), np.float32)
        action_space = spaces.Discrete(5)

        def reset(self, seed=None, options=None):
            return np.zeros(17, dtype=np.float32), {}

        def step(self, action):
            return np.zeros(17, dtype=np.float32), 0.0, False, False, {}

    legacy_path = os.path.join(workdir, "legacy_ppo.zip")
    PPO("MlpPolicy", _StubEnv(), n_steps=8, batch_size=8,
        device="cpu").save(legacy_path)
    check("legacy PPO checkpoint sniffed as NOT maskable",
          checkpoint_is_maskable(legacy_path) is False)
    legacy_model, legacy_aware = load_checkpoint_auto(legacy_path, env=None,
                                                      device="cpu")
    check("load_checkpoint_auto -> mask_aware=False for legacy",
          legacy_aware is False)
    check("legacy model loads as stable_baselines3 PPO",
          type(legacy_model).__module__.startswith("stable_baselines3"))


# --------------------------------------------------------------------------- #
def main() -> int:
    t0 = time.monotonic()
    workdir = tempfile.mkdtemp(prefix="gamecore_smoke_")
    try:
        cfg = load_cfg()
        smoke_resolve_algo(cfg)
        smoke_bridge_protocol()
        smoke_heartbeat()
        smoke_combined_message_dropped()
        final_ckpt = smoke_training(cfg, workdir)
        smoke_checkpoints(final_ckpt, workdir)
    except AssertionError as e:
        print(f"\nSMOKE FAILED after {len(PASSED)} assertions: {e}")
        return 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    dt = time.monotonic() - t0
    print(f"\nSMOKE OK — {len(PASSED)} assertions passed in {dt:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
