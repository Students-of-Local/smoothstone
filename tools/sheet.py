"""Build a recipe's defaults and every example through the real `stone` CLI, then tile the previews.

uv run python tools/sheet.py <recipe> [<recipe> ...] [--out DIR]

Prints one line per build (PASS or the FIX lines) and writes DIR/<recipe>.png.
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def run(job, *args):
    p = subprocess.run(["stone", "--job", str(job), *args], capture_output=True, text=True, cwd=ROOT)
    return p.returncode, p.stdout


def build(recipe, name, params, out):
    job = out / "jobs" / f"{recipe}-{name}"
    image = params.pop("_image", None)
    run(job, "new", f"{recipe} {name}", "--force", *(["--image", str(ROOT / image)] if image else []))
    rc, txt = run(job, "set", recipe, *[f"{k}={v}" for k, v in params.items()])
    if rc == 0:
        rc, txt = run(job, "build")
    bad = [l for l in txt.splitlines() if l.startswith(("FIX", "ERROR")) or "ERROR" in l]
    size = next((l for l in txt.splitlines() if l.startswith("Size:")), "")
    print(f"{recipe:16s} {name:16s} {'PASS' if rc == 0 else 'FAIL'}  {size}  {' | '.join(bad)[:200]}")
    png = job / "build" / "preview.png"
    return name, (png if png.exists() else None), rc == 0


def main():
    args = sys.argv[1:]
    out = Path(args[args.index("--out") + 1]) if "--out" in args else ROOT / "build" / "sheets"
    recipes = [a for i, a in enumerate(args) if a != "--out" and (i == 0 or args[i - 1] != "--out")]
    if recipes == ["all"]:
        recipes = sorted(p.name for p in (ROOT / "recipes").iterdir() if (p / "recipe.json").exists() and not p.name.startswith("_"))
    out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for r in recipes:
        meta = json.loads((ROOT / "recipes" / r / "recipe.json").read_text())
        needs_image = any(p.get("required") for p in meta["params"] if p["type"] == "image")
        shots = ([] if needs_image else [build(r, "defaults", {}, out)]) + [build(r, e["name"], {**e["params"], **({"_image": e["image"]} if e.get("image") else {})}, out)
                                              for e in meta.get("examples", [])]
        failed += sum(1 for s in shots if not s[2])
        if not shots:
            print(f"{r:16s} skipped: needs a photo and has no example (tests cover it)")
            continue
        tile = 450
        sheet = Image.new("RGB", (tile * len(shots), tile + 30), "#1a1b26")
        d = ImageDraw.Draw(sheet)
        for i, (name, png, ok) in enumerate(shots):
            if png:
                sheet.paste(Image.open(png).convert("RGB").resize((tile, tile)), (i * tile, 30))
            d.text((i * tile + 8, 8), f"{name} {'ok' if ok else 'FAIL'}", fill="#c0caf5" if ok else "#f7768e")
        sheet.save(out / f"{r}.png")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
