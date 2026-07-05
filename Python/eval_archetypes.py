"""Offline quality/behavior eval for exported ONNX boss brains — NO UE required.

For each .onnx under SourceArt/Models (boss_untrained.onnx skipped unless
--all), drives the brain against a scripted-opponent duel built on
tests/mock_ue_server.MockUEServer for N episodes and reports:

  - mean/std episode reward (BossEnv's real phase-based reward function)
  - action distribution over the 5 EBossAction indices
  - mask-violation attempts actually SENT to the bridge (must be 0 — actions
    are chosen as masked argmax over the logits, exactly what the C++ NNE
    consumer does per export_onnx.py G7)
  - raw-argmax-illegal count (how often the UNMASKED argmax would have been
    illegal — informational, shows the mask doing work)
  - mean decision entropy of the masked softmax (nats; uniform-over-5 =
    ln 5 = 1.609)
  - a 3-line behavioral read + rusher-vs-turtle divergence verdict

ONNX execution: onnxruntime is NOT installed in the venv (checked 2026-07-06;
avoiding a new dep on the shared training machine). The exported actor is a
tiny MLP (Flatten -> Gemm -> Tanh -> Gemm -> Tanh -> Gemm, see
export_onnx.py OnnxActor), so this script executes the graph with a
~30-line numpy interpreter over exactly those op types. If onnxruntime is
ever installed, it is preferred automatically (single-threaded session).

Fairness: every brain faces the IDENTICAL scripted hero — episode i uses
rng seed (base_seed + i) for all brains, so distribution differences come
from the brains, not the opponent.

Run from anywhere (paths are script-relative):
  venv\Scripts\python.exe eval_archetypes.py            # trained brains only
  venv\Scripts\python.exe eval_archetypes.py --all      # + boss_untrained baseline
  venv\Scripts\python.exe eval_archetypes.py --episodes 40 --seed 0

CPU-light by design: single-threaded numpy (env caps below), step_delay=0,
episode cap 150 steps. Whole run (3 brains x 40 eps) ~= 30-60 s.
"""

from __future__ import annotations

import os

# Single-threaded BEFORE numpy import — an online UE training run shares this
# machine (task requirement).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import argparse
import json
import math
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "tests"))

import numpy as np

# We never import torch, but if some import chain pulled it in, pin it too.
if "torch" in sys.modules:
    sys.modules["torch"].set_num_threads(1)

from boss_env import BossEnv
from mock_ue_server import MockUEServer  # tests/

MODELS_DIR = os.path.normpath(os.path.join(_HERE, "..", "SourceArt", "Models"))
ACTION_NAMES = ["Attack", "Block", "Dodge", "Approach", "Retreat"]
LOG = "[EvalArch]"


# --------------------------------------------------------------------------- #
# ONNX forward pass
# --------------------------------------------------------------------------- #
class NumpyOnnxPolicy:
    """Numpy interpreter for the exported SB3 actor graph.

    Supports exactly the ops export_onnx.py emits for an MlpPolicy actor
    (Flatten / Gemm / Tanh, plus MatMul/Add/Relu/Identity for safety).
    Raises on anything else rather than silently mis-executing.
    """

    def __init__(self, path: str):
        import onnx
        from onnx import numpy_helper

        model = onnx.load(path)
        self.graph = model.graph
        self.weights = {t.name: numpy_helper.to_array(t).astype(np.float64)
                        for t in self.graph.initializer}
        self.input_name = self.graph.input[0].name
        self.output_name = self.graph.output[0].name
        self.op_types = [n.op_type for n in self.graph.node]

    def logits(self, obs: np.ndarray) -> np.ndarray:
        """obs: (obs_dim,) float -> (5,) float64 action logits."""
        tensors = dict(self.weights)
        tensors[self.input_name] = obs.reshape(1, -1).astype(np.float64)
        for node in self.graph.node:
            x = [tensors[i] for i in node.input]
            op = node.op_type
            if op == "Flatten":
                y = x[0].reshape(x[0].shape[0], -1)
            elif op == "Gemm":
                attrs = {a.name: a for a in node.attribute}
                a_mat, b_mat = x[0], x[1]
                if attrs.get("transA") is not None and attrs["transA"].i:
                    a_mat = a_mat.T
                if attrs.get("transB") is not None and attrs["transB"].i:
                    b_mat = b_mat.T
                alpha = attrs["alpha"].f if "alpha" in attrs else 1.0
                beta = attrs["beta"].f if "beta" in attrs else 1.0
                y = alpha * (a_mat @ b_mat)
                if len(x) > 2:
                    y = y + beta * x[2]
            elif op == "Tanh":
                y = np.tanh(x[0])
            elif op == "Relu":
                y = np.maximum(x[0], 0.0)
            elif op == "MatMul":
                y = x[0] @ x[1]
            elif op == "Add":
                y = x[0] + x[1]
            elif op == "Identity":
                y = x[0]
            else:
                raise NotImplementedError(
                    f"{LOG} unsupported ONNX op '{op}' — extend NumpyOnnxPolicy")
            tensors[node.output[0]] = y
        return tensors[self.output_name].reshape(-1)


class OrtPolicy:
    """onnxruntime-backed policy (used automatically when ort is installed)."""

    def __init__(self, path: str):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(
            path, sess_options=opts, providers=["CPUExecutionProvider"])
        self.input_name = self.sess.get_inputs()[0].name

    def logits(self, obs: np.ndarray) -> np.ndarray:
        out = self.sess.run(
            None, {self.input_name: obs.reshape(1, -1).astype(np.float32)})
        return out[0].reshape(-1).astype(np.float64)


def load_policy(path: str):
    try:
        import onnxruntime  # noqa: F401
        return OrtPolicy(path), "onnxruntime (1 thread)"
    except ImportError:
        return NumpyOnnxPolicy(path), "numpy interpreter (onnxruntime absent)"


# --------------------------------------------------------------------------- #
# Scripted duel opponent (deterministic per seed, identical across brains)
# --------------------------------------------------------------------------- #
class ScriptedDuelServer(MockUEServer):
    """MockUEServer + a scripted hero and simple combat dynamics.

    Dynamics run INSIDE the server dispatch thread when a boss action
    arrives, so the very next observe already reflects the action —
    no one-step lag between action and consequence (unlike mutating the
    hooks from the client thread).

    All quantities normalized 0..1 like the real bridge. The mask mimics
    the C++ GetLegalActionMask spirit: Attack illegal out of range,
    Approach illegal at point-blank, Retreat illegal at max range.
    """

    ATTACK_RANGE = 0.20

    def __init__(self, base_seed: int, **kw):
        super().__init__(**kw)
        self.base_seed = base_seed
        self._episode_idx = -1
        self._rng = np.random.default_rng(base_seed)
        self._hero_state = "approach"
        self._hero_chain = 0

    # -- episode reset (invoked on the bridge "reset" command) --------------
    def _reset_duel(self):
        self._episode_idx += 1
        self._rng = np.random.default_rng(self.base_seed + self._episode_idx)
        self.hero_hp = 1.0
        self.boss_hp = 1.0
        self.dist = 0.5
        self.angle = 0.0
        self.hero_combo = 0
        self.hero_attacking = False
        self.hero_vel = [0.0, 0.0, 0.0]
        self.hero_action = 5
        self.profile = list(
            np.clip(0.5 + self._rng.normal(0.0, 0.05, 8), 0.0, 1.0))
        self._hero_state = "approach"
        self._hero_chain = 0
        self._update_mask()

    def _update_mask(self):
        self.mask = [
            1 if self.dist <= 0.35 else 0,   # Attack: only in/near range
            1,                               # Block: always legal
            1,                               # Dodge: always legal
            1 if self.dist > 0.05 else 0,    # Approach: not at point-blank
            1 if self.dist < 0.95 else 0,    # Retreat: not at max range
        ]

    # -- one combat tick, driven by the boss action -------------------------
    def _tick(self, boss_action: int):
        rng = self._rng
        boss_blocking = boss_action == 1
        boss_dodging = boss_action == 2

        # Boss movement
        if boss_action == 3:
            self.dist = max(0.02, self.dist - 0.07)
        elif boss_action == 4:
            self.dist = min(1.0, self.dist + 0.07)
        elif boss_dodging:
            self.dist = min(1.0, self.dist + 0.04)  # backstep

        # Hero script (same for every brain; rng-seeded per episode)
        hero_attacked = hero_blocking = hero_dodging = False
        if self.dist > self.ATTACK_RANGE:
            # close in, occasionally strafing
            self.dist = max(0.02, self.dist - 0.06)
            self._hero_state = "approach"
            self._hero_chain = 0
            self.hero_action = 3
            self.hero_vel = [0.8, float(rng.normal(0, 0.2)), 0.0]
        else:
            r = rng.random()
            if r < 0.55 or self._hero_chain > 0:   # attack / continue combo
                hero_attacked = True
                self._hero_chain = (self._hero_chain + 1) % 3
                self.hero_action = 0
                self.hero_vel = [0.2, 0.0, 0.0]
            elif r < 0.70:
                hero_blocking = True
                self.hero_action = 1
                self.hero_vel = [0.0, 0.0, 0.0]
            elif r < 0.85:
                hero_dodging = True
                self.hero_action = 2
                self.dist = min(1.0, self.dist + 0.05)
                self.hero_vel = [-0.6, float(rng.normal(0, 0.3)), 0.0]
            else:                                   # reposition
                self.hero_action = 4
                self.dist = min(1.0, self.dist + 0.04)
                self.hero_vel = [-0.4, float(rng.normal(0, 0.4)), 0.0]
        self.hero_attacking = hero_attacked
        self.hero_combo = self._hero_chain

        # Boss attack resolution
        if boss_action == 0 and self.dist <= self.ATTACK_RANGE:
            if hero_dodging:
                dmg = 0.0
            elif hero_blocking:
                dmg = 0.02
            else:
                dmg = 0.06
            self.hero_hp = max(0.0, self.hero_hp - dmg)

        # Hero attack resolution
        if hero_attacked and self.dist <= self.ATTACK_RANGE:
            if boss_dodging:
                dmg = 0.0
            elif boss_blocking:
                dmg = 0.015
            else:
                dmg = 0.05
            self.boss_hp = max(0.0, self.boss_hp - dmg)

        self.angle = float(np.clip(rng.normal(0.0, 0.15), -1.0, 1.0))
        self._update_mask()

    # -- protocol hook -------------------------------------------------------
    def _dispatch_line(self, conn, line):
        try:
            msg = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            msg = None
        if isinstance(msg, dict):
            if "action" in msg and int(msg["action"]) >= 0:
                with self._lock:
                    self._tick(int(msg["action"]))
            elif msg.get("command") == "reset":
                with self._lock:
                    self._reset_duel()
        super()._dispatch_line(conn, line)


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def masked_argmax(logits: np.ndarray, mask: np.ndarray) -> int:
    return int(np.where(mask, logits, -np.inf).argmax())


def masked_entropy(logits: np.ndarray, mask: np.ndarray) -> float:
    z = np.where(mask, logits, -np.inf)
    z = z - z.max()
    p = np.exp(z)
    p /= p.sum()
    nz = p[p > 0]
    return float(-(nz * np.log(nz)).sum())


def eval_brain(name: str, onnx_path: str, episodes: int, seed: int,
               max_steps: int) -> dict:
    policy, backend = load_policy(onnx_path)
    print(f"{LOG} {name}: loaded {os.path.basename(onnx_path)} via {backend}")

    server = ScriptedDuelServer(base_seed=seed, port=0)
    server.start()
    env = BossEnv(host="127.0.0.1", port=server.port, timeout=10.0,
                  step_delay=0.0, player_id=f"eval_{name}")
    env._max_steps = max_steps

    ep_rewards, ep_lengths = [], []
    action_counts = np.zeros(5, dtype=np.int64)
    entropies = []
    violations_sent = 0          # sent action illegal under its mask (must be 0)
    raw_argmax_illegal = 0       # unmasked argmax was illegal (mask did work)
    wins = losses = draws = 0
    dist_sum, dist_n = 0.0, 0

    try:
        for _ in range(episodes):
            obs, _ = env.reset()
            total, steps = 0.0, 0
            while True:
                mask = env.action_masks()
                lg = policy.logits(obs)
                action = masked_argmax(lg, mask)
                if not mask[action]:
                    violations_sent += 1
                if not mask[int(lg.argmax())]:
                    raw_argmax_illegal += 1
                entropies.append(masked_entropy(lg, mask))
                action_counts[action] += 1

                obs, reward, terminated, truncated, info = env.step(action)
                total += reward
                steps += 1
                dist_sum += float(obs[BossEnv.IDX_DISTANCE])
                dist_n += 1
                if terminated or truncated:
                    if info["hero_hp"] <= 0.0 and info["boss_hp"] > 0.0:
                        wins += 1
                    elif info["boss_hp"] <= 0.0:
                        losses += 1
                    else:
                        draws += 1
                    break
            ep_rewards.append(total)
            ep_lengths.append(steps)
    finally:
        env.close()
        server.stop()

    total_steps = int(action_counts.sum())
    return {
        "name": name,
        "backend": backend,
        "episodes": episodes,
        "mean_reward": float(np.mean(ep_rewards)),
        "std_reward": float(np.std(ep_rewards)),
        "mean_len": float(np.mean(ep_lengths)),
        "action_pct": (action_counts / max(total_steps, 1) * 100.0),
        "action_counts": action_counts,
        "entropy": float(np.mean(entropies)),
        "violations_sent": violations_sent,
        "raw_argmax_illegal": raw_argmax_illegal,
        "wins": wins, "losses": losses, "draws": draws,
        "mean_dist": dist_sum / max(dist_n, 1),
        "total_steps": total_steps,
    }


def behavioral_read(r: dict) -> list[str]:
    pct = r["action_pct"]
    top = int(pct.argmax())
    defensive = pct[1] + pct[2]
    lines = []
    lines.append(
        f"{ACTION_NAMES[top]}-heavy ({pct[top]:.0f}% of decisions); "
        f"defensive share (Block+Dodge) {defensive:.0f}%.")
    if pct[3] >= pct[4] + 10:
        spacing = "presses in -- Approach dominates Retreat"
    elif pct[4] >= pct[3] + 10:
        spacing = "gives ground -- Retreat dominates Approach"
    else:
        spacing = "neutral spacing -- Approach and Retreat balanced"
    lines.append(
        f"{spacing} ({pct[3]:.0f}% vs {pct[4]:.0f}%); mean fight distance "
        f"{r['mean_dist']:.2f} (attack range 0.20).")
    decisiveness = ("decisive" if r["entropy"] < 0.5
                    else "mixed" if r["entropy"] < 1.1 else "near-uniform")
    lines.append(
        f"Record vs scripted hero: {r['wins']}W/{r['losses']}L/{r['draws']}D "
        f"over {r['episodes']} eps; policy is {decisiveness} "
        f"(entropy {r['entropy']:.2f}/{math.log(5):.2f} nats).")
    return lines


def print_table(results: list[dict]):
    hdr = (f"{'brain':<16}{'meanR':>9}{'stdR':>8}{'len':>6}"
           + "".join(f"{a[:4] + '%':>8}" for a in ACTION_NAMES)
           + f"{'entropy':>9}{'maskViol':>9}{'rawIll':>8}{'W/L/D':>10}")
    print("\n" + hdr)
    print("-" * len(hdr))
    for r in results:
        pct = r["action_pct"]
        print(f"{r['name']:<16}{r['mean_reward']:>9.2f}{r['std_reward']:>8.2f}"
              f"{r['mean_len']:>6.0f}"
              + "".join(f"{pct[i]:>8.1f}" for i in range(5))
              + f"{r['entropy']:>9.3f}{r['violations_sent']:>9d}"
              f"{r['raw_argmax_illegal']:>8d}"
              f"{str(r['wins']) + '/' + str(r['losses']) + '/' + str(r['draws']):>10}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--episodes", type=int, default=40)
    ap.add_argument("--all", action="store_true",
                    help="include boss_untrained.onnx as the baseline")
    ap.add_argument("--models-dir", default=MODELS_DIR)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=150,
                    help="per-episode step cap (keeps runtime bounded)")
    args = ap.parse_args()

    brains = []
    for fn in sorted(os.listdir(args.models_dir)):
        if not fn.endswith(".onnx"):
            continue
        name = os.path.splitext(fn)[0]
        if name == "boss_untrained" and not args.all:
            print(f"{LOG} skipping {fn} (baseline; pass --all to include)")
            continue
        brains.append((name, os.path.join(args.models_dir, fn)))

    if not brains:
        print(f"{LOG} FAIL: no .onnx brains found under {args.models_dir}")
        return 1

    t0 = time.monotonic()
    results = []
    for name, path in brains:
        results.append(eval_brain(name, path, args.episodes, args.seed,
                                  args.max_steps))
    dt = time.monotonic() - t0

    print_table(results)
    for r in results:
        print(f"{LOG} {r['name']} -- behavioral read:")
        for line in behavioral_read(r):
            print(f"    {line}")
        print()

    # --- Divergence: rusher vs turtle ------------------------------------ #
    by_name = {r["name"]: r for r in results}
    divergence_ok = None
    ru, tu = by_name.get("boss_rusher"), by_name.get("boss_turtle")
    if ru and tu:
        p, q = ru["action_pct"] / 100.0, tu["action_pct"] / 100.0
        tv = 0.5 * float(np.abs(p - q).sum())
        print(f"{LOG} rusher-vs-turtle action-distribution diff "
              f"(total variation distance): {tv:.3f}")
        for i in range(5):
            print(f"    {ACTION_NAMES[i]:<9} rusher {p[i]*100:5.1f}%  "
                  f"turtle {q[i]*100:5.1f}%  d={((p[i]-q[i])*100):+6.1f}pp")
        divergence_ok = tv >= 0.15
        print(f"{LOG} personality divergence "
              f"{'DETECTED' if divergence_ok else 'NOT DETECTED'} "
              f"(TV {tv:.3f} {'>=' if divergence_ok else '<'} 0.15 threshold)")

    # --- PASS/FAIL summary ------------------------------------------------ #
    checks = []
    checks.append(("all brains loaded and ran full episode count",
                   all(len(r["action_pct"]) == 5 and r["total_steps"] > 0
                       for r in results)))
    checks.append(("0 mask violations sent (masked argmax legality)",
                   all(r["violations_sent"] == 0 for r in results)))
    checks.append(("every brain produced finite rewards",
                   all(math.isfinite(r["mean_reward"]) for r in results)))
    if divergence_ok is not None:
        checks.append(("rusher vs turtle personality divergence (TV >= 0.15)",
                       divergence_ok))

    print()
    hard_fail = False
    for label, ok in checks:
        print(f"{LOG} {'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            hard_fail = True
    print(f"{LOG} {'FAIL' if hard_fail else 'PASS'} -- "
          f"{len(results)} brain(s), {args.episodes} eps each, "
          f"{sum(r['total_steps'] for r in results)} decisions in {dt:.1f}s")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
