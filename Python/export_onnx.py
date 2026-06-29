"""Export a trained SB3 policy to ONNX for in-engine inference via UE's NNE plugin.

ROADMAP.md milestone M5. The exported network maps a float32 observation vector
(the same one StateObservationComponent builds) to 5 action logits — take the
argmax in C++ to get the EBossAction index. Deterministic, no Python at runtime.

Usage (from D:\\GAME_CORE 5.8\\Python, venv active or via venv\\Scripts\\python.exe):
    python export_onnx.py --model checkpoints/boss_rl_2048_steps.zip
    python export_onnx.py --model models/final.zip --out boss_policy.onnx

Works with PPO and (if sb3-contrib is installed) MaskablePPO checkpoints —
masking is a training-time concern; the exported actor is the same MLP either way.
"""

import argparse
from pathlib import Path

import numpy as np
import torch as th


class OnnxActor(th.nn.Module):
    """The actor path of an SB3 MlpPolicy: obs -> action logits."""

    def __init__(self, policy):
        super().__init__()
        self.features_extractor = policy.features_extractor  # FlattenExtractor for MlpPolicy
        self.mlp_extractor = policy.mlp_extractor
        self.action_net = policy.action_net

    def forward(self, obs):
        feats = self.features_extractor(obs)
        latent_pi = self.mlp_extractor.forward_actor(feats)
        return self.action_net(latent_pi)  # (batch, n_actions) logits


def load_model(path: str):
    from stable_baselines3 import PPO

    try:
        return PPO.load(path, device="cpu")
    except Exception:
        try:
            from sb3_contrib import MaskablePPO

            return MaskablePPO.load(path, device="cpu")
        except ImportError as exc:
            raise SystemExit(
                f"Could not load {path} as PPO, and sb3-contrib is not installed "
                f"to try MaskablePPO. Original error context: {exc}"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Path to the SB3 .zip checkpoint")
    parser.add_argument("--out", default=None, help="Output .onnx path (default: alongside the model)")
    parser.add_argument("--opset", type=int, default=17)
    args = parser.parse_args()

    model_path = Path(args.model)
    out_path = Path(args.out) if args.out else model_path.with_suffix(".onnx")

    model = load_model(str(model_path))
    obs_dim = int(np.prod(model.observation_space.shape))
    n_actions = int(model.action_space.n)
    print(f"Loaded {model_path.name}: obs_dim={obs_dim}, n_actions={n_actions}")

    actor = OnnxActor(model.policy).eval()
    dummy = th.zeros(1, obs_dim, dtype=th.float32)

    th.onnx.export(
        actor,
        dummy,
        str(out_path),
        opset_version=args.opset,
        input_names=["observation"],
        output_names=["action_logits"],
        dynamic_axes={"observation": {0: "batch"}, "action_logits": {0: "batch"}},
    )
    print(f"Exported -> {out_path}")

    # ── Verify: exported actor must agree with model.predict on random obs ──
    rng = np.random.default_rng(0)
    test_obs = rng.uniform(0.0, 1.0, size=(64, obs_dim)).astype(np.float32)

    with th.no_grad():
        torch_actions = (
            actor(th.as_tensor(test_obs)).argmax(dim=1).numpy()
        )
    sb3_actions = np.array(
        [model.predict(o, deterministic=True)[0] for o in test_obs]
    ).reshape(-1)

    agree = float((torch_actions == sb3_actions).mean())
    print(f"Torch-actor vs SB3 predict agreement: {agree * 100:.1f}% (expect 100%)")

    try:
        import onnxruntime as ort

        sess = ort.InferenceSession(str(out_path), providers=["CPUExecutionProvider"])
        ort_logits = sess.run(None, {"observation": test_obs})[0]
        ort_actions = ort_logits.argmax(axis=1)
        agree_ort = float((ort_actions == sb3_actions).mean())
        print(f"ONNX-runtime vs SB3 predict agreement: {agree_ort * 100:.1f}% (expect 100%)")
    except ImportError:
        print("onnxruntime not installed — skipped runtime check "
              "(pip install onnxruntime to enable; the export itself is complete).")

    print("\nNNE notes (UE side):")
    print("  - Enable the 'Neural Network Engine (NNE)' plugin (Edit -> Plugins).")
    print(f"  - Import {out_path.name} into the project; NNE exposes it as a model asset.")
    print("  - Feed the SAME {obs_dim}-dim normalized observation the bridge sends,".replace("{obs_dim}", str(obs_dim)))
    print("    run inference (CPU runtime is plenty for an MLP), argmax the 5 logits,")
    print("    and pass the index to BossActionComponent::ExecuteAction.")


if __name__ == "__main__":
    main()
