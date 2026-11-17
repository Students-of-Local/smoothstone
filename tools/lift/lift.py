"""Single image to 3D mesh ("lift") for smoothstone.

Runs Tencent Hunyuan3D-2mini (shape DiT only, no texture) locally on Apple
MPS. Input: one front-view PNG of a single object on a plain or transparent
background. Output: .glb (Y-up, glTF convention) or .stl (Z-up, for slicers).

Usage:
  uv run --project tools/lift python tools/lift/lift.py in.png out.stl \
      [--seed N] [--steps N] [--octree N] [--variant mini|turbo] \
      [--device mps|cpu] [--preview out.png]

Prints one JSON line at the end:
  {"ok": true, "out": ..., "seconds": ..., "peak_gb": ..., "model": ..., "faces": ...}
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor" / "Hunyuan3D-2"
WEIGHTS = HERE / "weights"
REPO_ID = "tencent/Hunyuan3D-2mini"
REVISION = "f90a0f7df7d5e6f71109cf333f6a95a0ae3194a6"
VARIANTS = {
    # name: (subfolder, default steps, use flashvdm decoder)
    "mini": ("hunyuan3d-dit-v2-mini", 50, False),
    "turbo": ("hunyuan3d-dit-v2-mini-turbo", 5, True),
}
# enable_flashvdm() swaps in this VAE; fetch it up front so hy3dgen does not
# snapshot the whole subfolder (it would also pull the redundant .ckpt).
TURBO_VAE = "hunyuan3d-vae-v2-mini-turbo"
BLENDER = os.environ.get("BLENDER", "/opt/homebrew/bin/blender")

# hy3dgen reads weights from $HY3DGEN_MODELS/<repo>/<subfolder> before HF.
os.environ.setdefault("HY3DGEN_MODELS", str(WEIGHTS))
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
sys.path.insert(0, str(VENDOR))


def peak_footprint_gb() -> float:
    """Lifetime max phys_footprint of this process (macOS), in GB.

    On Apple silicon this includes Metal/MPS allocations in unified memory,
    which RSS does not, so it is the honest peak for GPU work.
    """
    try:
        libc = ctypes.CDLL("/usr/lib/libproc.dylib")
        buf = (ctypes.c_uint64 * 64)()
        RUSAGE_INFO_V4 = 4
        if libc.proc_pid_rusage(os.getpid(), RUSAGE_INFO_V4, ctypes.byref(buf)) != 0:
            raise OSError("proc_pid_rusage failed")
        # rusage_info_v4: 16-byte uuid, then u64 fields; ri_lifetime_max_phys_footprint
        # is the 31st u64 after the uuid -> byte offset 240 -> index 30.
        return buf[30] / 1e9
    except Exception:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9


def ensure_weights(subfolders: list[str]) -> None:
    missing = [s for s in subfolders if not (WEIGHTS / REPO_ID / s / "model.fp16.safetensors").exists()]
    if not missing:
        return
    from huggingface_hub import snapshot_download

    snapshot_download(
        REPO_ID,
        revision=REVISION,
        allow_patterns=[p for s in missing for p in (f"{s}/config.yaml", f"{s}/model.fp16.safetensors")],
        local_dir=str(WEIGHTS / REPO_ID),
    )


def load_rgba(path: Path):
    """Return an RGBA image with the background cut out.

    Uses the alpha channel when it actually masks something; otherwise runs
    rembg (u2net) to cut the subject from a plain background.
    """
    import numpy as np
    from PIL import Image

    im = Image.open(path)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        alpha = np.asarray(im)[..., 3]
        if (alpha < 128).mean() > 0.01:
            return im, False
    from hy3dgen.rembg import BackgroundRemover

    return BackgroundRemover()(im.convert("RGB")), True


def render_preview(mesh_path: Path, png_path: Path) -> None:
    """Three-view (front, 3/4, side) gray clay render via headless Blender."""
    script = HERE / "preview_blender.py"
    cmd = [BLENDER, "-b", "--factory-startup", "-P", str(script), "--", str(mesh_path), str(png_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not png_path.exists():
        raise RuntimeError(f"blender preview failed ({r.returncode}): {r.stderr[-800:]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path, help=".glb or .stl")
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--steps", type=int, default=None, help="denoise steps (mini 50, turbo 5)")
    ap.add_argument("--octree", type=int, default=380, help="marching cubes grid resolution")
    ap.add_argument("--variant", choices=sorted(VARIANTS), default="mini")
    ap.add_argument("--device", default="mps")
    ap.add_argument("--chunks", type=int, default=20000, help="VAE decode query chunk size")
    ap.add_argument("--preview", type=Path, default=None, help="also write a 3-view PNG")
    args = ap.parse_args()

    t0 = time.time()
    subfolder, default_steps, flashvdm = VARIANTS[args.variant]
    steps = args.steps or default_steps
    model_id = f"{REPO_ID}/{subfolder}@{REVISION[:8]}"
    result = {"ok": False, "out": str(args.output), "model": model_id}
    try:
        ext = args.output.suffix.lower()
        if ext not in (".glb", ".stl"):
            raise ValueError(f"output must be .glb or .stl, got {ext!r}")

        import torch
        import trimesh

        if args.device == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError("MPS not available; pass --device cpu")
        dtype = torch.float16 if args.device != "cpu" else torch.float32

        image, used_rembg = load_rgba(args.input)

        ensure_weights([subfolder, TURBO_VAE] if flashvdm else [subfolder])
        from hy3dgen.shapegen import (
            DegenerateFaceRemover,
            FloaterRemover,
            Hunyuan3DDiTFlowMatchingPipeline,
        )

        pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            REPO_ID,
            subfolder=subfolder,
            use_safetensors=True,
            variant="fp16",
            device=args.device,
            dtype=dtype,
        )
        if flashvdm:
            pipe.enable_flashvdm(topk_mode="merge")
        t_load = time.time()

        mesh = pipe(
            image=image,
            num_inference_steps=steps,
            octree_resolution=args.octree,
            num_chunks=args.chunks,
            generator=torch.Generator(device="cpu").manual_seed(args.seed),
            output_type="trimesh",
        )[0]
        if mesh is None or len(mesh.faces) == 0:
            raise RuntimeError("model returned an empty mesh (no surface at mc level)")
        t_gen = time.time()

        mesh = FloaterRemover()(mesh)
        mesh = DegenerateFaceRemover()(mesh)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        if ext == ".stl":
            # Hunyuan outputs Y-up; slicers expect Z-up.
            mesh.apply_transform(trimesh.transformations.rotation_matrix(1.5707963267948966, [1, 0, 0]))
            mesh.apply_translation([0, 0, -mesh.bounds[0][2]])
        mesh.export(str(args.output))
        # Report what a slicer will see: STL stores float32 per-triangle
        # vertices, so welds can break on the round trip.
        written = trimesh.load(str(args.output), force="mesh")

        if args.preview:
            render_preview(args.output, args.preview)

        result.update(
            ok=True,
            seconds=round(time.time() - t0, 1),
            load_seconds=round(t_load - t0, 1),
            gen_seconds=round(t_gen - t_load, 1),
            peak_gb=round(peak_footprint_gb(), 2),
            faces=int(len(written.faces)),
            watertight=bool(written.is_watertight),
            extents=[round(float(x), 3) for x in written.extents],
            device=args.device,
            steps=steps,
            octree=args.octree,
            seed=args.seed,
            rembg=used_rembg,
        )
        if args.preview:
            result["preview"] = str(args.preview)
    except Exception as e:  # report failure as JSON too
        traceback.print_exc(file=sys.stderr)
        result.update(error=f"{type(e).__name__}: {e}", seconds=round(time.time() - t0, 1),
                      peak_gb=round(peak_footprint_gb(), 2), faces=0)
    print(json.dumps(result), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
