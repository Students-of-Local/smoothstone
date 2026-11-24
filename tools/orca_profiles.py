"""Each printer's own slicer settings, per plastic, from OrcaSlicer's profiles.

Writes recipes/lib/refs/printer_settings.json: for every printer in src/smoothstone/printers, the process it
ships with (speeds, accelerations, line widths, shells) and, for every plastic stone has strength data for,
the nozzle, plate and chamber heat, the fan and the flow the hotend can melt.

    git clone --filter=blob:none https://github.com/OrcaSlicer/OrcaSlicer && git -C OrcaSlicer checkout <COMMIT>
    python tools/orca_profiles.py OrcaSlicer [--check]
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "recipes" / "lib" / "refs" / "printer_settings.json"
COMMIT = "a31c95e273d3423abf185a444d70beae4941c697"
CHECKED = "2026-11-24"
LIBRARY = "OrcaFilamentLibrary"
MATERIALS = ("PLA", "PETG", "ABS", "ASA", "PC", "PA", "TPU", "PLA-CF", "PETG-CF")
MACHINES = {
    "anycubic_kobra_3": ("Anycubic", "Anycubic Kobra 3 0.4 nozzle"),
    "bambu_a1": ("BBL", "Bambu Lab A1 0.4 nozzle"),
    "bambu_a1_mini": ("BBL", "Bambu Lab A1 mini 0.4 nozzle"),
    "bambu_h2d": ("BBL", "Bambu Lab H2D 0.4 nozzle"),
    "bambu_p1p": ("BBL", "Bambu Lab P1P 0.4 nozzle"),
    "bambu_p1s": ("BBL", "Bambu Lab P1S 0.4 nozzle"),
    "bambu_x1c": ("BBL", "Bambu Lab X1 Carbon 0.4 nozzle"),
    "creality_ender3_v3": ("Creality", "Creality Ender-3 V3 0.4 nozzle"),
    "creality_ender3_v3_se": ("Creality", "Creality Ender-3 V3 SE 0.4 nozzle"),
    "creality_k1_max": ("Creality", "Creality K1 Max (0.4 nozzle)"),
    "creality_k1c": ("Creality", "Creality K1C 0.4 nozzle"),
    "creality_k2": ("Creality", "Creality K2 0.4 nozzle"),
    "creality_k2_plus": ("Creality", "Creality K2 Plus 0.4 nozzle"),
    "elegoo_centauri_carbon": ("Elegoo", "Elegoo Centauri Carbon 0.4 nozzle"),
    "elegoo_neptune_4_pro": ("Elegoo", "Elegoo Neptune 4 Pro 0.4 nozzle"),
    "prusa_core_one": ("Prusa", "Prusa CORE One 0.4 nozzle"),
    "prusa_mini": ("Prusa", "Prusa MINI 0.4 nozzle"),
    "prusa_mk4s": ("Prusa", "Prusa MK4S 0.4 nozzle"),
    "qidi_q1_pro": ("Qidi", "Qidi Q1 Pro 0.4 nozzle"),
    "sovol_sv08": ("Sovol", "Sovol SV08 0.4 nozzle"),
    "voron_24": ("Voron", "Voron 2.4 300 0.4 nozzle"),
}
WIDTHS = {"outer_wall": "outer_wall_line_width", "inner_wall": "inner_wall_line_width",
          "sparse_infill": "sparse_infill_line_width", "solid_infill": "internal_solid_infill_line_width",
          "top_surface": "top_surface_line_width", "first_layer": "initial_layer_line_width", "support": "support_line_width"}
SPEEDS = {"outer_wall": "outer_wall_speed", "inner_wall": "inner_wall_speed", "sparse_infill": "sparse_infill_speed",
          "solid_infill": "internal_solid_infill_speed", "top_surface": "top_surface_speed", "support": "support_speed",
          "bridge": "bridge_speed", "first_layer": "initial_layer_speed", "first_layer_infill": "initial_layer_infill_speed",
          "travel": "travel_speed"}
ACCELS = {"default": "default_acceleration", "outer_wall": "outer_wall_acceleration", "inner_wall": "inner_wall_acceleration",
          "top_surface": "top_surface_acceleration", "travel": "travel_acceleration", "first_layer": "initial_layer_acceleration"}
SHELLS = {"wall_loops": "wall_loops", "bottom_shell_layers": "bottom_shell_layers", "top_shell_layers": "top_shell_layers",
          "sparse_infill_density": "sparse_infill_density", "infill_direction": "infill_direction"}


class Profiles:
    """A vendor's profiles and the library's, each inheriting inside its own (a vendor's may go on into the library)."""

    def __init__(self, root: Path, vendor: str):
        self.root, self.by = root, {v: self._read(root / v) for v in (vendor, LIBRARY)}
        self.vendor = vendor

    @staticmethod
    def _read(folder: Path) -> dict:
        """What OrcaSlicer loads: the files the vendor's index lists."""
        out, index = {}, json.loads(folder.with_name(f"{folder.name}.json").read_text(encoding="utf-8"))
        for f in (folder / x["sub_path"] for k in index if k.endswith("_list") for x in index[k]):
            d = json.loads(f.read_text(encoding="utf-8"))
            out[d.get("type"), d["name"]] = {**d, "_file": f}
        return out

    def names(self, kind: str, bundle: str) -> list[str]:
        return [n for k, n in self.by[bundle] if k == kind]

    def get(self, kind: str, name: str, bundle: str | None = None) -> dict:
        """A profile with what it inherits and includes."""
        bundle = bundle or self.vendor
        if (kind, name) not in self.by[bundle]:
            bundle = LIBRARY
        d = self.by[bundle][kind, name]
        out = dict(self.get(kind, d["inherits"], bundle)) if d.get("inherits") else {}
        out.pop("instantiation", None)
        out.pop("compatible_printers", None)
        for inc in d.get("include", []):
            out.update(self.get(kind, inc, bundle))
        return {**out, **d}

    def url(self, d: dict) -> str:
        rel = d["_file"].relative_to(self.root.parents[1]).as_posix()
        return f"https://github.com/OrcaSlicer/OrcaSlicer/blob/{COMMIT}/{quote(rel)}"


def num(v, of: float | None = None) -> float | None:
    """A setting's number (a list's first: the standard nozzle); a percentage is of `of`."""
    v = v[0] if isinstance(v, list) and v else v
    m = re.fullmatch(r"\s*(-?[\d.]+)\s*(%?)\s*", str(v))
    if not m:
        return None
    x = float(m[1]) * ((of / 100) if m[2] and of else 1)
    return int(x) if x == int(x) else round(x, 4)


def filament(p: Profiles, machine: str, material: str) -> dict:
    """The maker's own generic profile of the plastic for this machine, the one for the fewest machines, else the
    maker's plainest named one, else Orca's generic for any printer. Never another brand's product."""
    mine = [d for n in p.names("filament", p.vendor) for d in [p.get("filament", n)] if d.get("instantiation") == "true"
            and num_type(d) == material and machine in d.get("compatible_printers", [])]
    plain = rf"(.* )?Generic {re.escape(material)}( @.*)?"
    maker = (p.vendor, "Prusament") if p.vendor == "Prusa" else (p.vendor, "Bambu") if p.vendor == "BBL" else (p.vendor,)
    mine = [d for d in mine if re.fullmatch(plain, d["name"]) or d["name"].startswith(maker)]
    mine.sort(key=lambda d: (not re.fullmatch(plain, d["name"]), len(d["compatible_printers"]), len(d["name"]), d["name"]))
    return mine[0] if mine else p.get("filament", f"Generic {material} @System", LIBRARY)


def process(p: Profiles, machine: str, mc: dict) -> dict:
    """The machine's default process; where that names none in the tree, its 0.20 mm one (the standard before the others)."""
    if mc["default_print_profile"] in p.names("process", p.vendor):
        return p.get("process", mc["default_print_profile"])
    mine = [d for n in p.names("process", p.vendor) if n.startswith("0.20mm") for d in [p.get("process", n)] if machine in d.get("compatible_printers", [])]
    return min(mine, key=lambda d: ("Standard" not in d["name"], len(d["name"]), d["name"]))


def num_type(d: dict) -> str:
    t = d.get("filament_type", "")
    return t[0] if isinstance(t, list) and t else t


def entry(key: str, value, note: str, quoted: str, p: Profiles, d: dict) -> dict:
    return {"id": f"orca.{key}", "topic": "printers", "value": value, "note": note, "quote": quoted,
            "source": f"OrcaSlicer {d['_file'].relative_to(p.root.parents[1]).as_posix()}", "cite": f"OrcaSlicer {d['name']}",
            "url": p.url(d), "checked": CHECKED}


def build(checkout: Path) -> list[dict]:
    root, out = checkout / "resources" / "profiles", []
    for pid, (vendor, machine) in MACHINES.items():
        prof = json.loads((ROOT / "src" / "smoothstone" / "printers" / f"{pid}.json").read_text())
        p = Profiles(root, vendor)
        mc = p.get("machine", machine)
        pr = process(p, machine, mc)
        nozzle = prof["nozzle_mm"]
        # a machine with one plate is sliced for the high temp plate, whatever the plate is; a Bambu has them all
        many = (vendor == "BBL" or mc.get("support_multi_bed_types") == "1") and "textured" in prof["bed_surface"]["type"].lower()
        line = num(pr.get("line_width"), nozzle) or None
        widths = {k: num(pr.get(v), nozzle) or line for k, v in WIDTHS.items()}
        accels = {k: num(pr.get(v), num(pr["default_acceleration"])) or num(pr["default_acceleration"]) for k, v in ACCELS.items()}
        value = {"layer": num(pr["layer_height"]), "widths": widths, "speeds": {k: num(pr.get(v), num(pr.get("outer_wall_speed"))) for k, v in SPEEDS.items()},
                 "accels": accels, "shells": {k: num(pr.get(v)) for k, v in SHELLS.items()} | {"sparse_infill_pattern": pr.get("sparse_infill_pattern")},
                 "retract_mm": num(mc.get("retraction_length")), "nozzle_volume_mm3": num(mc.get("nozzle_volume"))}
        out.append(entry(f"{pid}.process", {k: v for k, v in value.items() if v is not None},
                         f"{prof['name']}: layer and widths mm, speeds mm/s, accelerations mm/s2. nozzle_volume_mm3 is the filament from the cutter to the nozzle's tip.",
                         f"\"name\": \"{pr['name']}\"", p, pr))
        for m in MATERIALS:
            d = filament(p, machine, m)
            bed = many and num(d.get("textured_plate_temp")) or num(d.get("hot_plate_temp"))
            value = {"nozzle": num(d["nozzle_temperature"]), "bed": bed, "chamber": num(d.get("chamber_temperature", d.get("chamber_temperatures"))) or None,
                     "fan_min": num(d.get("fan_min_speed")), "fan_max": num(d.get("fan_max_speed")),
                     "fan_long": None if num(d.get("reduce_fan_stop_start_freq")) or not num(d.get("fan_min_speed")) else 0,
                     "fan_min_layer_s": num(d.get("fan_cooling_layer_time")), "fan_max_layer_s": num(d.get("slow_down_layer_time")),
                     "max_flow": num(d.get("filament_max_volumetric_speed")),
                     "diameter": num(d.get("filament_diameter"))}
            own = machine in d.get("compatible_printers", [])
            out.append(entry(f"{pid}.{m}", {k: v for k, v in value.items() if v is not None},
                             f"{m} on the {prof['name']}: C, the flow the hotend melts in mm3/s, filament mm, and the fan in %: at fan_min on "
                             "layers longer than fan_min_layer_s, at fan_max on ones shorter than fan_max_layer_s, in between between."
                             + ("" if value["fan_long"] is None else " It stops the fan on the longer ones: fan_long.")
                             + ("" if own else " OrcaSlicer's profile for any printer: it has none for this one."),
                             f"\"name\": \"{d['name']}\"", p, d))
    return out


def text(entries: list[dict]) -> str:
    rows = ",\n".join("  " + json.dumps(e, ensure_ascii=False) for e in entries)
    about = f"Each printer's slicer settings per plastic, written by tools/orca_profiles.py from OrcaSlicer at {COMMIT}. Do not edit by hand."
    return f'{{"about": {json.dumps(about)},\n "entries": [\n{rows}\n]}}\n'


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("checkout", type=Path)
    ap.add_argument("--check", action="store_true", help="fail when the file is not what the checkout says")
    a = ap.parse_args()
    head = subprocess.run(["git", "-C", str(a.checkout), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != COMMIT:
        sys.exit(f"{a.checkout} is at {head or 'no commit'}, not {COMMIT}")
    if subprocess.run(["git", "-C", str(a.checkout), "status", "--porcelain", "--", "resources/profiles"], capture_output=True, text=True).stdout:
        sys.exit(f"{a.checkout} has edited profiles")
    got = text(build(a.checkout))
    if a.check:
        sys.exit(0 if OUT.read_text() == got else f"{OUT} is not what {a.checkout} says")
    OUT.write_text(got)
