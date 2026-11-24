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
