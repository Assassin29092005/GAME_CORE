"""Measure per-persona behavior centroids from recorded replays.

NEXTSTEP Part 3 follow-up: the +NNEArchetypeBank rows in Config/DefaultGame.ini
carry an 8-dim behavior centroid per persona (FPlayerProfile::ToFloatArray()
order). The first rows were hand-authored guesses; this script replaces them
with MEASURED means from the actual training data the persona's policy saw.

Reads replays/<persona>/episode_*.npz (written by replay_recorder.py), slices
the 8 profile dims out of the 17-dim base observation (indices 9-16, see
boss_env.py), and reports:
  - the all-steps mean profile (the centroid — matches the
    FNNEArchetypeBankEntry contract: "the MEAN 8-dim FPlayerProfile the
    persona's policy trained against")
  - the final-step mean (where the EMA converged, for reference)
  - the neutral-centered cosine similarity matrix between persona centroids,
    mirroring UArchetypeProfilesAsset::SelectFromEntries (profiles are centered
    at the 0.5 neutral point before cosine — raw cosine on all-positive
    vectors saturates near 1 and barely discriminates)
  - ready-to-paste +NNEArchetypeBank= ini rows

Usage (from Python/, venv):
    venv\Scripts\python.exe measure_centroids.py
    venv\Scripts\python.exe measure_centroids.py --replay-dir replays
"""

import argparse
import glob
import os

import numpy as np

PROFILE_START = 9
PROFILE_DIMS = 8
PROFILE_NAMES = [
    "Aggression", "DodgeTend", "BlockTend", "OpenerAggr",
    "PressureResp", "Kiting", "ComboCompl", "PosVariance",
]
NEUTRAL = 0.5


def centered_cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity after centering both vectors at the 0.5 neutral
    profile — the same math the C++ archetype selector uses."""
    ac, bc = a - NEUTRAL, b - NEUTRAL
    na, nb = np.linalg.norm(ac), np.linalg.norm(bc)
    if na < 1e-6 or nb < 1e-6:
        return float("nan")  # all-neutral profile carries no signal
    return float(np.dot(ac, bc) / (na * nb))


def measure(replay_dir: str) -> dict:
    out = {}
    for persona_dir in sorted(glob.glob(os.path.join(replay_dir, "*"))):
        if not os.path.isdir(persona_dir):
            continue
        persona = os.path.basename(persona_dir)
        episodes = sorted(glob.glob(os.path.join(persona_dir, "episode_*.npz")))
        if not episodes:
            continue

        all_steps, final_steps, n_steps = [], [], 0
        for ep in episodes:
            with np.load(ep) as data:
                obs = data["obs"]
                if obs.ndim != 2 or obs.shape[1] < PROFILE_START + PROFILE_DIMS:
                    print(f"  ! {ep}: unexpected obs shape {obs.shape} — skipped")
                    continue
                prof = obs[:, PROFILE_START:PROFILE_START + PROFILE_DIMS]
                all_steps.append(prof)
                final_steps.append(prof[-1])
                n_steps += prof.shape[0]

        if not all_steps:
            continue
        out[persona] = {
            "episodes": len(all_steps),
            "steps": n_steps,
            "mean": np.concatenate(all_steps).mean(axis=0),
            "final": np.stack(final_steps).mean(axis=0),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--replay-dir", default="replays")
    args = parser.parse_args()

    results = measure(args.replay_dir)
    if not results:
        raise SystemExit(f"No replays found under {args.replay_dir}/")

    print(f"{'persona':<10} {'eps':>5} {'steps':>7}  " +
          " ".join(f"{n:>12}" for n in PROFILE_NAMES))
    for persona, r in results.items():
        print(f"{persona:<10} {r['episodes']:>5} {r['steps']:>7}  " +
              " ".join(f"{v:>12.3f}" for v in r["mean"]))
        print(f"{'  (final)':<10} {'':>5} {'':>7}  " +
              " ".join(f"{v:>12.3f}" for v in r["final"]))

    personas = list(results)
    if len(personas) > 1:
        print("\nNeutral-centered cosine between measured centroids "
              "(want low/negative off-diagonal = separable archetypes):")
        print(f"{'':<10}" + "".join(f"{p:>10}" for p in personas))
        for a in personas:
            row = "".join(
                f"{centered_cosine(results[a]['mean'], results[b]['mean']):>10.3f}"
                for b in personas)
            print(f"{a:<10}{row}")

    print("\nIni rows (Config/DefaultGame.ini [/Script/GAME_CORE.GameFeelSettings]):")
    for persona, r in results.items():
        model = f"/Game/Arena/Models/NNM_Boss{persona.capitalize()}.NNM_Boss{persona.capitalize()}"
        centroid = ",".join(f"{v:.3f}" for v in r["mean"])
        print(f'+NNEArchetypeBank=(Persona="{persona}",ModelData="{model}",Centroid=({centroid}))')


if __name__ == "__main__":
    main()
