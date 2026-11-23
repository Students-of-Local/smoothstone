# Gold parts

Reference designs by GPT-6.1 Sol, smoothstone gold set. Each folder holds one engineering spec's
part as Sol made it by hand from the spec in `evals/engineering/<id>.json`:

- `part.scad`: the part, all sizes from the spec's product block plus Sol's design choices
- `build/engineering.json`: the part's frame, fit, retention, load and holes, as the grader reads them
- `NOTES.md`: Sol's reasons for each choice and what it checked

They are the geometry the product recipes adapt: `recipes/round_case` (e04), `recipes/product_holder`
(e05, e06), `recipes/product_mount` (e07), `recipes/board_plate` (e08) and `recipes/knob` (e09).
The recipes size that geometry from any catalog product; these files stay as made, for one
product each. They are not a held out set: every spec here is in the tuning set.

Each passes the engineering grader. To check, from the repo root:

    uv run python evals/gold/grade.py                 # every part here
    uv run python evals/gold/grade.py e08_rpi4_vesa_adapter

It builds each `part.scad` with OpenSCAD into a scratch folder laid out as the grader expects
(`part.stl`, `build/engineering.json`), grades it against the spec with
`evals/engineering_grade.py`, prints PASS or the reasons it fails, and exits 1 if any fails.
