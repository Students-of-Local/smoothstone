"""Write recipes/fitted_case/products.scad from the product catalog (src/smoothstone/products).

uv run python tools/products_scad.py
"""

from pathlib import Path

from smoothstone import catalog

OUT = Path(__file__).resolve().parents[1] / "recipes" / "fitted_case" / "products.scad"

if __name__ == "__main__":
    OUT.write_text(catalog.scad_table())
    print(f"wrote {OUT}")
