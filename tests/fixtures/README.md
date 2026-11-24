# Test fixtures

## gcode/

Real slicer-made G-code, used by tests/test_timelapse.py to check stone's G-code reader and its print
time model against the estimate each slicer wrote in the file. No slicer runs on the build Mac, so
these files are the slicers' own output, gzipped as downloaded.

| File | Slicer | From | License |
|---|---|---|---|
| prusa_screw.gcode.gz | PrusaSlicer 2.7.4, Ender 3 V2 profile, 139 layers, arcs (G2/G3) | [remcoder/gcode-preview](https://github.com/remcoder/gcode-preview) `demo/gcodes/screw.gcode` at 5eaa6d0 | MIT (the repository's license) |
| creality_washer.gcode.gz | Creality Print 5.1.6, K1 profile, 10 layers, Klipper | [vitordmarchiori/Flapping-Wing-UAV-Prototype](https://github.com/vitordmarchiori/Flapping-Wing-UAV-Prototype) `CAD/CAD Files/3D Printing/Washer_1.gcode` at 7c19f0c | CC0 1.0 (the repository's license) |
| orca_cube.gcode.gz | OrcaSlicer 2.3.1-alpha, Klipper, 4 layers | [harpua555/OpenFilamentSensor](https://github.com/harpua555/OpenFilamentSensor) `tools/cubewithironing.gcode` at a007400 | MIT (the repository's license) |

The repositories state these licenses for all their files; none names a separate license for the
models these files were sliced from.

## Other fixtures

`lamine_round6_figure.stl.gz`, `edges/` and `measure/` came in with earlier pull requests (#2, #6, #56); see those for how they were made.
