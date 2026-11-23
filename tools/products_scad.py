"""Write the product tables the recipes read from the catalog (src/smoothstone/products):
recipes/fitted_case/products.scad (the fitted case's layout) and recipes/lib/catalog.scad (every
product, for round_case, product_holder, product_mount, board_plate and knob).

uv run python tools/products_scad.py
"""

from pathlib import Path

from smoothstone import catalog

ROOT = Path(__file__).resolve().parents[1] / "recipes"
OUT = ROOT / "fitted_case" / "products.scad"
LIB = ROOT / "lib" / "catalog.scad"

if __name__ == "__main__":
    OUT.write_text(catalog.scad_table())
    LIB.write_text(catalog.catalog_table())
    print(f"wrote {OUT} and {LIB}")
