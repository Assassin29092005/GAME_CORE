"""Export a trained SB3 policy to ONNX for in-engine inference via UE's NNE plugin.

ROADMAP.md milestone M5. The exported network maps a float32 observation vector
(the same one StateObservationComponent builds) to 5 action logits — take the
argmax in C++ to get the EBossAction index. Deterministic, no Python at runtime.

Usage (from D:\\GAME_CORE 5.8\\Python, venv active or via venv\\Scripts\\python.exe):
    python export_onnx.py --model checkpoints/boss_rl_2048_steps.zip
    python export_onnx.py --model models/final.zip --out boss_policy.onnx

Works with PPO and (if sb3-contrib is installed) MaskablePPO checkpoints —
masking is a training-time concern; the exported actor is the same MLP either
way. The ONNX graph stays mask-free (G7): legality is applied at the consumer
as a masked argmax over the logits (verified below), which is what the C++
NNE side must do with the bridge's "mask" field.
"""

import argparse
from pathlib import Path

import numpy as np
import torch as th

from rl_algo import load_checkpoint_auto


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Path to the SB3 .zip checkpoint")
    parser.add_argument("--out", default=None, help="Output .onnx path (default: alongside the model)")
    parser.add_argument("--opset", type=int, default=17)
    args = parser.parse_args()

    model_path = Path(args.model)
    out_path = Path(args.out) if args.out else model_path.with_suffix(".onnx")

    # Zip-sniffed loader (G3): legacy PPO and MaskablePPO both load correctly.
    model, mask_aware = load_checkpoint_auto(str(model_path), device="cpu")
    obs_dim = int(np.prod(model.observation_space.shape))
    n_actions = int(model.action_space.n)
    kind = "MaskablePPO" if mask_aware else "legacy PPO"
    print(f"Loaded {kind} {model_path.name}: obs_dim={obs_dim}, n_actions={n_actions}")

    actor = OnnxActor(model.policy).eval()
    dummy = th.zeros(1, obs_dim, dtype=th.float32)

    # dynamo=False pins the legacy TorchScript exporter (G1) — the dynamo
    # path needs onnxscript and torch is flipping its default.
    th.onnx.export(
        actor,
        dummy,
        str(out_path),
        opset_version=args.opset,
        input_names=["observation"],
        output_names=["action_logits"],
        dynamic_axes={"observation": {0: "batch"}, "action_logits": {0: "batch"}},
        dynamo=False,
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

    with th.no_grad():
        torch_logits = actor(th.as_tensor(test_obs)).numpy()

    try:
        import onnxruntime as ort

        sess = ort.InferenceSession(str(out_path), providers=["CPUExecutionProvider"])
        ort_logits = sess.run(None, {"observation": test_obs})[0]
        ort_actions = ort_logits.argmax(axis=1)
        agree_ort = float((ort_actions == sb3_actions).mean())
        print(f"ONNX-runtime vs SB3 predict agreement: {agree_ort * 100:.1f}% (expect 100%)")
        verify_logits = ort_logits
    except ImportError:
        print("onnxruntime not installed — skipped runtime check "
              "(pip install onnxruntime to enable; the export itself is complete).")
        verify_logits = torch_logits

    # ── Verify consumer-side masked argmax (G7) ──────────────────────────
    # The graph itself is mask-free; legality is applied by the consumer as
    # np.where(mask, logits, -inf).argmax(). Check that random masks always
    # yield a legal action, and a full mask reproduces the plain argmax.
    mask_rng = np.random.default_rng(1)
    masks = mask_rng.integers(0, 2, size=(len(verify_logits), n_actions)).astype(bool)
    masks[~masks.any(axis=1), 0] = True  # ensure >=1 legal per row
    masked_actions = np.where(masks, verify_logits, -np.inf).argmax(axis=1)
    all_legal = bool(masks[np.arange(len(masks)), masked_actions].all())
    full_mask_match = bool(
        (np.where(np.ones_like(masks), verify_logits, -np.inf).argmax(axis=1)
         == verify_logits.argmax(axis=1)).all()
    )
    print(f"Masked-argmax consumer check: legal={all_legal}, "
          f"full-mask==argmax={full_mask_match} (expect True, True)")

    print("\nNNE notes (UE side):")
    print("  - Enable the 'Neural Network Engine (NNE)' plugin (Edit -> Plugins).")
    print(f"  - Import {out_path.name} into the project; NNE exposes it as a model asset.")
    print("  - Feed the SAME {obs_dim}-dim normalized observation the bridge sends,".replace("{obs_dim}", str(obs_dim)))
    print("    run inference (CPU runtime is plenty for an MLP), then apply the")
    print("    action mask as a masked argmax over the 5 logits (set illegal")
    print("    logits to -FLT_MAX before taking the max — the graph is mask-free),")
    print("    and pass the index to BossActionComponent::ExecuteAction.")


if __name__ == "__main__":
    main()
