"""The G-code reader and print time model (gcode.py), on real slicer files and small snippets."""

import gzip
import math
import re
from pathlib import Path

import numpy as np
import pytest

from smoothstone import gcode

FIX = Path(__file__).parent / "fixtures" / "gcode"
GCODES = sorted(FIX.glob("*.gcode.gz"))


def _layer_zs(text: str) -> list[float]:
    """Each layer's z as the file says it, read without gcode.py: the ;Z: (or ; Z_HEIGHT:) comment
    after each ;LAYER_CHANGE."""
    zs, want = [], False
    for line in text.splitlines():
        s = line.strip()
        if re.fullmatch(r";\s*(LAYER_CHANGE|CHANGE_LAYER)", s):
            want = True
        elif want and re.match(r";\s*(Z|Z_HEIGHT):", s):
            zs.append(float(s.split(":", 1)[1]))
            want = False
    return zs


@pytest.mark.parametrize("path", GCODES, ids=lambda p: p.name.split(".")[0])
def test_layers_are_the_files_layers(path):
    """(a) Every layer at the z the file gives it, exactly, and as many layers as the header says."""
    want = _layer_zs(gzip.decompress(path.read_bytes()).decode(errors="replace"))
    tp = gcode.load(path)
    assert len(want) > 3
    assert tp.layer_z == want
    if tp.header_layers:
        assert len(tp.layer_z) == tp.header_layers
    assert set(np.unique(tp.layer[tp.extruding()])) <= set(range(-1, len(want)))


@pytest.mark.parametrize("path", GCODES, ids=lambda p: p.name.split(".")[0])
def test_print_time_is_within_10_percent_of_the_slicers_estimate(path):
    """(b) Measured: screw (PrusaSlicer) +1.6%, washer (Creality Print) +0.3%, cube (OrcaSlicer) -1.7%."""
    tp = gcode.load(path)
    assert tp.estimate_s
    assert tp.total_s() == pytest.approx(tp.estimate_s, rel=0.10)


def test_trapezoid_and_triangle_moves_take_their_textbook_time():
    text = "M205 X0 Y0 Z0 E0\nM204 S1000\nG21\nG90\nM83\nG1 X100 F6000\nG1 X98\n"
    tp = gcode.plan(gcode.parse(text))
    # 100 mm at 100 mm/s, 1000 mm/s2, from rest and back to rest (no jerk, then a reversal)
    assert tp.t1[0] - tp.t0[0] == pytest.approx(1.1, abs=1e-6)
    # 2 mm back never reaches 100 mm/s: up to sqrt(a d) and down again
    assert tp.t1[1] - tp.t0[1] == pytest.approx(2 * math.sqrt(1000 * 2) / 1000, abs=1e-6)


CURA = """;FLAVOR:Marlin
;TIME:100
;LAYER_COUNT:2
M82
G92 E0
;LAYER:0
G0 F6000 X10 Y10 Z0.3
;TYPE:WALL-OUTER
G1 F1800 X20 Y10 E1
G1 X20 Y20 E2
;TYPE:FILL
G1 X10 Y20 E3
;LAYER:1
G0 X10 Y10 Z0.5
G92 E0
;TYPE:SKIN
G1 X20 Y10 E1
G91
G1 X0 Y10 E1
G90
"""

BAMBU = """; HEADER_BLOCK_START
; model printing time: 1m 40s; total estimated time: 2m 0s
; total layer number: 2
; HEADER_BLOCK_END
M83
SET_VELOCITY_LIMIT ACCEL=5000
; CHANGE_LAYER
; Z_HEIGHT: 0.2
; LAYER_HEIGHT: 0.2
; FEATURE: Outer wall
; LINE_WIDTH: 0.42
G1 X10 Y10 Z0.2 F3000
G1 X20 Y10 E0.5
G3 X20 Y20 I0 J5 E0.8
; CHANGE_LAYER
; Z_HEIGHT: 0.4
; FEATURE: Sparse infill
G1 Z0.4
G1 X10 Y20 E0.5
"""


def test_cura_layers_features_and_relative_moves():
    tp = gcode.load(CURA)
    assert tp.layer_z == [0.3, 0.5]  # Cura writes no ;Z:, so each layer's first extrusion height
    assert tp.estimate_s == 100
    ext = tp.extruding()
    names = [gcode.FEATURES[k] for k in tp.feature[ext]]
    assert names == ["outer wall", "outer wall", "sparse infill", "solid infill", "solid infill"]
    assert tp.p1[ext][-1, :2].tolist() == [20.0, 20.0]  # G91 moved 10 mm from 20,10
    assert tp.p1[ext][3, 3] - tp.p0[ext][3, 3] == pytest.approx(1.0)  # G92 E0 restarted absolute E


def test_bambu_layers_features_arcs_and_accel():
    tp = gcode.load(BAMBU)
    assert tp.layer_z == [0.2, 0.4]
    ext = tp.extruding()
    assert set(gcode.FEATURES[k] for k in tp.feature[ext & (tp.layer == 0)]) == {"outer wall"}
    assert gcode.FEATURES[tp.feature[ext][-1]] == "sparse infill"
    assert np.all(tp.width[ext & (tp.layer == 0)] == 0.42)
    arc = ext & (tp.layer == 0) & (tp.p0[:, 1] >= 10) & (tp.p1[:, 1] > 10)
    assert arc.sum() > 10  # the half circle is cut into short chords
    length = np.hypot(*(tp.p1[arc, :2] - tp.p0[arc, :2]).T).sum()
    assert length == pytest.approx(math.pi * 5, rel=0.01)
    assert np.all(tp.accel[ext] == 5000)
    assert tp.estimate_s == 120


JERK = "M205 X8 Y8 Z0.4 E5\nM204 S1000\nG21\nG90\nM83\n"


def test_diagonal_start_from_rest_is_the_smallest_jerk_as_prusaslicer():
    """Review #94 F1: a +X+Y move at 100 mm/s runs 100 / sqrt(2) = 70.71 mm/s on X and on Y, both over
    their jerk of 8. PrusaSlicer's GCodeProcessor::process_G1 takes the smallest jerk of the axes over
    theirs: min(8, 8) = 8 mm/s. The old code multiplied the axes: 100 * (8 / 70.71)^2 = 1.28 mm/s."""
    safe, vj, junction = gcode.corner_speeds(gcode.parse(JERK + "G1 X100 Y100 F6000\n"))
    assert safe[0] == pytest.approx(8.0, abs=1e-6)
    assert junction[0] == pytest.approx(8.0, abs=1e-6)


def test_square_corner_rescales_by_the_running_factor():
    """Review #94 F1: +X at 100 then +Y at 100. X leaves at 100 and enters at 0: a full stop, jump
    max(100, 0) = 100 > 8, so the factor is 8 / 100 = 0.08. Y, scaled by that factor as PrusaSlicer
    does: leaves at 0, enters at 100 * 0.08 = 8, jump 8, not over. vj = 100 * 0.08 = 8 mm/s. The old
    code measured Y's jump on the unscaled 100 and got 100 * 0.08 * 0.08 = 0.64. Both moves' safe
    speed (8) is over 0.99 * 8, so the corner starts from the second move's safe speed, 8."""
    safe, vj, junction = gcode.corner_speeds(gcode.parse(JERK + "G1 X100 F6000\nG1 Y100\n"))
    assert vj[1] == pytest.approx(8.0, abs=1e-6)
    assert junction[1] == pytest.approx(8.0, abs=1e-6)


def test_straight_to_diagonal_corner_matches_prusaslicer():
    """Review #94 F1: +X at 100 then +X+Y at 100 (70.71 on each axis). X coasts from 100 to 70.71,
    jump 29.29 > 8, factor 8 / 29.29 = 0.2731. Y, scaled: leaves at 0, enters at 70.71 * 0.2731 = 19.31,
    jump 19.31 > 8, factor 0.2731 * 8 / 19.31 = 0.1131. vj = 100 * 0.1131 = 11.31 mm/s (8 * sqrt(2)).
    The old code gave 100 * 0.2731 * 8 / 70.71 = 3.09. The diagonal's safe speed (8) is under
    0.99 * 11.31, so the corner speed is vj itself."""
    safe, vj, junction = gcode.corner_speeds(gcode.parse(JERK + "G1 X100 F6000\nG1 X200 Y100\n"))
    assert vj[1] == pytest.approx(8 * math.sqrt(2), abs=1e-6)
    assert junction[1] == pytest.approx(8 * math.sqrt(2), abs=1e-6)


def test_limits_hold_from_where_the_file_sets_them():
    """Review #94 r2 F1: a jerk, feed or accel limit the file changes later leaves the earlier moves alone."""
    head = "M205 X8 Y8\nM203 X50\nM201 X500\nM204 S1000\nG90\nM83\n"
    body = "G1 X100 F6000\nG1 Y100\n"
    tp = gcode.parse(head + body + "M205 X20 Y20\nM203 X400\nM201 X9000\nG1 X0\nG1 Y0\n")
    safe, vj, _ = gcode.corner_speeds(tp)
    assert safe[:2] == pytest.approx([8, 8]) and safe[2:] == pytest.approx([20, 20])
    assert vj[1] == pytest.approx(8) and vj[3] == pytest.approx(20)
    first = gcode.plan(gcode.parse(head + body)).t1[0]
    assert gcode.plan(tp).t1[0] == pytest.approx(first)  # X 50 mm/s and 500 mm/s2 until the file says otherwise


def test_a_wait_before_an_arc_is_counted_once_and_stops_the_printer():
    """Review #94 r2 F2: G4 S10 before a 16-chord arc was counted as 160 s. And a wait on a straight line
    is a stop: 100 mm/s, 1000 mm/s2 from rest to rest, twice, with 1 s between."""
    arc = "M204 S1000\nG90\nM83\nG1 X20 Y10 F6000\n{}G3 X20 Y20 I0 J5 E0.8\n"
    wait, none = (gcode.load(arc.format(w)).total_s() for w in ("G4 S10\n", ""))
    assert 10 < wait - none < 10.5
    tp = gcode.load("M205 X0 Y0\nM204 S1000\nG90\nM83\nG1 X100 F6000\nG4 P1000\nG1 X200\n")
    assert tp.total_s() == pytest.approx(1.1 + 1 + 1.1, abs=1e-6)


@pytest.mark.parametrize("h", [0.1, 0.3])
def test_a_cura_width_uses_the_layers_real_height(h):
    """Review #94 r2 F3: a 0.4 mm line at height h over 10 mm is 4h mm3 of 1.75 mm filament."""
    e = 10 * 0.4 * h / (math.pi * 0.875 ** 2)
    tp = gcode.load(f";LAYER:0\nM83\nG0 F6000 X10 Y10 Z{h}\nG1 F1800 X20 Y10 E{e:.6f}\n;LAYER:1\nG0 Z{2 * h}\nG1 X10 E{e:.6f}\n")
    ext = tp.extruding()
    assert tp.height[ext] == pytest.approx([h, h]) and tp.width[ext] == pytest.approx([0.4, 0.4], rel=1e-4)


def test_one_at_a_time_comments_in_words_and_zero_limits():
    """Review #94 r2 F4, F5, F6, S2, S4."""
    tp = gcode.load("; Z: lift nozzle\n;HEIGHT: see profile\nM204 S0\nM201 X0\nM203 X0\nM83\n;LAYER:0\nG1 X10 Z0.3 E1 F0\n"
                    ";LAYER:1\nG1 X20 Z20 E1 F1200\n;LAYER:2\n;LAYER:3\nG1 X0 Z0.3\nG1 X10 E1\n")
    assert np.isfinite(tp.height).all() and np.isfinite(tp.t1).all() and tp.total_s() < 10
    assert tp.height[-1] == pytest.approx(0.3)
    assert gcode.FEATURES[gcode.feature_of("Support material interface")] == "support interface"
    assert gcode.parse("M566 X300\nM203 X12000\nG1 X1 F60\n").max_feed[0][0] == 200  # RepRapFirmware: mm/min


@pytest.mark.parametrize("name,fan,bed,nozzle,chamber,infill", [
    ("creality_washer", 1.0, 50, 230, 35, 15),  # START_PRINT EXTRUDER_TEMP=230 BED_TEMP=50, M141 S35
    ("orca_cube", None, 60, 210, None, 12),  # M190 S60, M109 S210
    ("prusa_screw", 1.0, 60, 200, None, 5),  # 210 C on the first layer, then M104 S200
])
def test_what_the_print_is_run_at(name, fan, bed, nozzle, chamber, infill):
    tp = gcode.parse(FIX / f"{name}.gcode.gz")
    on = tp.extruding() & (tp.layer > 1)
    got = np.median(tp.run[on], axis=0)
    assert got[1] == bed and got[2] == nozzle and (np.isnan(got[3]) if chamber is None else got[3] == chamber)
    assert 0 <= got[0] <= 1 and (fan is None or got[0] == fan)
    assert (tp.infill, tp.material) == (infill, "PLA")


def test_a_file_that_says_nothing_of_heat_is_not_given_any():
    tp = gcode.parse("M107 P2\nM106 P3 S255\n;LAYER_CHANGE\n;Z:0.2\nG1 X10 E1 F1200\n")
    assert np.isnan(tp.run).all() and tp.infill is None and tp.material == ""
    tp = gcode.parse("M140 S55\nM106 S127.5\nG1 X1 E1 F1200\nM140 S0\nM107\nG1 X10 E2\n")
    assert tp.run[0, :2].tolist() == [0.5, 55] and tp.run[-1, :2].tolist() == [0, 55]  # S0 at the end is not the print's bed
    tp = gcode.parse("PRINT_START BED=60 HOTEND=210 NOZZLE=0.4 EXTRUDER=0 CHAMBER_TEMP=0\nG1 X1 E1 F1200\n")
    assert tp.run[0, 1:3].tolist() == [60, 210] and np.isnan(tp.run[0, 3])


def test_the_tool_that_prints_the_part_says_its_heat_and_plastic():
    line = "\nG1 X{} E{} F1200\n".format
    text = ("; filament_type = PLA;PETG\nM104 T0 S220\nM104 T1 S245\n;TYPE:Custom\nM109 S222" + line(1, 1)  # a purge line
            + ";LAYER_CHANGE\n;TYPE:Support\nT0" + line(2, 2) + ";TYPE:Inner wall\nT1" + line(9, 3))
    tp = gcode.parse(text + "M104 T0 S150" + line(20, 5))
    assert tp.material == "PETG" and tp.run[:, 2].tolist() == [222, 222, 245, 245]  # T0 waits at 150 C
    assert gcode.parse(text.replace("T0\n", "\n").replace("T1\n", "\n")).material == ""  # no tool named: not known which
