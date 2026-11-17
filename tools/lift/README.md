# lift: one image to a printable mesh, locally

`lift.py` turns a clean front view of one figurine (plain white or transparent background) into a mesh, on this Mac's GPU (Apple M5, MPS). It runs the shape model from Tencent Hunyuan3D-2mini and skips texture, since a print needs only geometry. It lives in its own uv project so torch and the model never touch the main smoothstone install.

```
uv run --project tools/lift python tools/lift/lift.py in.png out.stl [--seed N] [--steps N] [--octree N] [--preview out.png]
```

The last line it prints is one JSON object:

```
{"ok": true, "out": "tools/lift/out/doll_mini.glb", "model": "tencent/Hunyuan3D-2mini/hunyuan3d-dit-v2-mini@f90a0f7d", "seconds": 492.9, "load_seconds": 30.9, "gen_seconds": 444.6, "peak_gb": 12.35, "faces": 761846, "watertight": true, ...}
```

On failure it prints `"ok": false` with an `error` field and exits 1.

- `.stl` comes out Z-up with the base on z=0 and the front facing -Y. `.glb` stays Y-up, as glTF expects.
- Size is in model units, about 2 units tall. Scale to millimeters in stone.
- `faces` and `watertight` are read back from the written file, which is what a slicer sees.
- If the input has no real alpha, rembg (u2net) cuts out the subject. White details on a white background get cut with it: the raccoon's white staff flame was lost that way. Hand it a transparent PNG when you have one.
- `peak_gb` is the kernel's lifetime peak physical footprint for the process, which counts MPS allocations in unified memory. RSS alone would read under 1 GB.
- `--preview` writes a front, 3/4 and side clay render through headless Blender (`preview_blender.py`, set `BLENDER` to override the path).

## Setup

From the smoothstone repo root:

```
cd tools/lift
git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git vendor/Hunyuan3D-2
git -C vendor/Hunyuan3D-2 checkout f8db63096c8282cb27354314d896feba5ba6ff8a
uv sync --python 3.12
```

The first run downloads the weights into `tools/lift/weights/` (config and fp16 safetensors only, about 3.8 GB, pinned to Hub revision `f90a0f7d`). rembg downloads `u2net.onnx` to `~/.u2net` the first time it needs it. `vendor/`, `weights/`, `.venv/` and `out/` are gitignored.

hy3dgen is not pip-installed: its setup.py pulls in gradio, fastapi and the texture stack. lift.py puts `vendor/Hunyuan3D-2` on `sys.path` and the pyproject lists only what the shape pipeline imports. Every dependency is pinned with `==`.

## Measured (2026-11-17, M5, 34 GB, MPS, fp16, 50 steps, seed 12345)

| input | output | octree | seconds (load / generate) | peak GB | faces | watertight file |
| --- | --- | --- | --- | --- | --- | --- |
| raccoon_wizard.png (RGBA) | .stl | 380 | 545 (81 / 453) | 12.54 | 738,830 | no (see below) |
| raccoon_wizard, flattened to white RGB (rembg path) | .stl | 380 | 838 (104 / 727) | 12.48 | 686,152 | yes |
| doll.png (RGBA) | .glb | 380 | 493 (31 / 445) | 12.35 | 761,846 | yes |
| doll.png (RGBA) | .stl | 256 | 244 (44 / 196) | 11.34 | 345,112 | yes |

Inputs are from `~/Projects/stable-point-aware-3d/demo_files/examples/`. Previews of each are in `out/*.png`.

The Mac was busy during these runs (load average 19 to 45 from other jobs), so wall time swung from 493 to 838 s for the same settings. About half of generation is the 50 diffusion steps (about 5 s each); the rest is volume decoding, 2,766 chunks over a 380^3 grid. `--octree 256` cut decoding from about 6 minutes to 1:47 and the whole run to 244 s, with half the faces. The two doll previews look the same at preview size; compare the meshes up close before you pick 256 for a print.

The first raccoon run reported watertight from the in-memory mesh, but the written STL reloads as not watertight, because STL stores float32 per-triangle vertices and some welds break on the round trip. lift.py now reads the written file back before it reports, so check `watertight` and repair before slicing.

## Candidates

| model | result |
| --- | --- |
| Hunyuan3D-2mini, `hunyuan3d-dit-v2-mini` | Chosen. Works on MPS in fp16 with no code changes, about 12.5 GB peak, clean watertight-or-near meshes with fine detail (whiskers, pockets, goggles). |
| Hunyuan3D-2mini, `hunyuan3d-dit-v2-mini-turbo` with FlashVDM (5 steps) | Failed on MPS: `RuntimeError: model returned an empty mesh (no surface at mc level)` after 453 s, with a 24.4 GB peak, over the 16 GB budget. Selectable with `--variant turbo` for anyone who wants to debug it. |
| Hunyuan3D-2.1 / 2 full shape | Not tried: 2mini worked. |
| SPAR3D | Not tried. `stabilityai/stable-point-aware-3d` is gated and the `donovan756` account has no access yet (`GatedRepoError`). |
| TripoSR | Not tried: 2mini worked. |

Hunyuan3D code and weights are under the Tencent Hunyuan 3D 2.0 Community License (`vendor/Hunyuan3D-2/LICENSE`, `weights/tencent/Hunyuan3D-2mini/LICENSE`). It excludes the EU, UK and South Korea and has its own use terms. Read it before shipping lift outputs as part of a product.

## In stone

stone calls lift.py with `--octree 256 --chunks 4000` (STONE_LIFT_OCTREE and STONE_LIFT_CHUNKS change them). On the Jensen render that took 234 s at a 9.04 GB peak and wrote a watertight mesh of 251,440 faces.
