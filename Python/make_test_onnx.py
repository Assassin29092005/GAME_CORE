"""Build an UNTRAINED MaskablePPO checkpoint and export it through the real
export_onnx.py flow -> SourceArt/Models/boss_untrained.onnx (M5 test pipeline).

Purpose: give the UE side (Tools/import_onnx_model.py -> NNM_BossUntrained ->
UNNEBossPolicyComponent / boss.NNESelfTest) a correctly-shaped model to verify
the whole ONNX->NNE pipeline BEFORE any real training checkpoint exists. The
weights are random on purpose — the pipeline check only needs the tensor
surface: observation [batch,17] float32 -> action_logits [batch,5] float32.

No sockets / no UE needed: the model is constructed on tests/env_stubs.py's
MaskStubEnv (the same 17-dim / Discrete(5) contract BossEnv exposes), wrapped
with the canonical ActionMasker from rl_algo.py.

The intermediate SB3 .zip is saved NEXT TO the onnx (SourceArt/Models/), NOT in
checkpoints/ — train.py's resume logic picks the newest zip in checkpoints/ and
must never resume from an untrained test model.

Run (venv):
    cd "D:\\GAME_CORE 5.8\\Python"
    venv\\Scripts\\python.exe make_test_onnx.py
"""

import sys
from pathlib import Path

PY_DIR = Path(__file__).resolve().parent
REPO_DIR = PY_DIR.parent
if str(PY_DIR) not in sys.path:
    sys.path.insert(0, str(PY_DIR))

from rl_algo import wrap_action_masker  # noqa: E402
from tests.env_stubs import MaskStubEnv  # noqa: E402

OUT_DIR = REPO_DIR / "SourceArt" / "Models"
CKPT_PATH = OUT_DIR / "boss_untrained.zip"
ONNX_PATH = OUT_DIR / "boss_untrained.onnx"


def build_untrained_checkpoint() -> Path:
    from sb3_contrib import MaskablePPO

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Same construction shape as train.py (MlpPolicy, default net_arch) so the
    # exported graph matches what a real checkpoint will produce.
    env = wrap_action_masker(MaskStubEnv())
    model = MaskablePPO("MlpPolicy", env, device="cpu", seed=0)
    model.save(str(CKPT_PATH))
    print(f"[make_test_onnx] Saved UNTRAINED MaskablePPO checkpoint -> {CKPT_PATH}")
    print(f"[make_test_onnx]   obs_space={model.observation_space.shape} "
          f"action_space=Discrete({model.action_space.n})")
    return CKPT_PATH


def export_via_export_onnx(ckpt: Path) -> Path:
    # Reuse the real export flow (OnnxActor extraction + torch.onnx.export +
    # SB3-agreement + masked-argmax verification) by importing export_onnx and
    # driving its main() — no subprocess.
    import export_onnx

    argv_backup = sys.argv
    try:
        sys.argv = ["export_onnx.py", "--model", str(ckpt), "--out", str(ONNX_PATH)]
        export_onnx.main()
    finally:
        sys.argv = argv_backup
    return ONNX_PATH


def report_tensor_shapes(onnx_path: Path) -> None:
    import onnx

    model = onnx.load(str(onnx_path))

    def fmt(value_info):
        dims = []
        for d in value_info.type.tensor_type.shape.dim:
            dims.append(d.dim_param if d.dim_param else str(d.dim_value))
        elem = onnx.TensorProto.DataType.Name(value_info.type.tensor_type.elem_type)
        return f"{value_info.name}: [{', '.join(dims)}] {elem}"

    print("[make_test_onnx] ONNX tensor surface:")
    for vi in model.graph.input:
        print(f"[make_test_onnx]   input  {fmt(vi)}")
    for vi in model.graph.output:
        print(f"[make_test_onnx]   output {fmt(vi)}")
    print(f"[make_test_onnx] PASS — {onnx_path} ready for Tools/import_onnx_model.py")


def main() -> None:
    ckpt = build_untrained_checkpoint()
    onnx_path = export_via_export_onnx(ckpt)
    report_tensor_shapes(onnx_path)


if __name__ == "__main__":
    main()
