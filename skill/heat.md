# Will it take the heat: stone heat

Run this card when a part lives somewhere warm: a car, a sunny window or deck, a dishwasher, near
a heater. `stone heat` says how soft the plastic gets there, how far a load sags, how much the
part grows, and whether it will warp on the print bed.

## 1. After stone build, say where it lives

```
stone heat where=car
```

`where=` is `car` (a dashboard in summer sun, 85 C), `sun` (dark surfaces in full sun, 70 C),
`dishwasher` (75 C), `outdoor` (hot summer shade, 41.5 C), or a temperature like `where=60C`.
Each is from a measured source; `stone refs service` shows them.

If `stone strength` ran first, its load is used again. To give one here, add the same words:
`load=20N at=tip dir=down fixed=bottom`.

Optional: `material=ASA` (else the job's pick), `enclosed=yes` when the printer has a closed
case (else the printer `stone printer` set, or open), `bed=60` (bed temperature, C).

## 2. Read the answer

- Softens at: the HDT, where the plastic bends under a light load. Past it, the part deforms.
- Keeps N% of its stiffness: how much stiffness and strength are left at that temperature.
- Load: the deflection at room temperature and when hot, and a material that does better.
- Creep: within 20 C of the HDT, a load held for days slowly bends the part.
- Expansion: how much the part grows, and how hard it pushes if held tight at both ends.
- Warp risk: low, medium or high, with the fix (brim, enclosure, or another material).

When it is fine, NEXT goes on with the job. When it is not, NEXT asks the person: a material
that takes the heat, a cooler spot, or a stiffer part. Changing the material is the person's choice.

The numbers and every assumption are in build/heat.json; the warp result is `warp_risk`.

## Example

```
$ stone heat where=outdoor
Part: part.stl, PLA.
Hot summer shade: 41.5 C. PLA softens at 55 C (HDT at 0.45 MPa), glass at 61 C: 13.5 C to spare.
At 41.5 C PLA keeps about 90% of its stiffness and strength.
Load 20 N (the load from the last stone strength): deflection 1.14 mm at room temperature -> 1.27 mm at 41.5 C, safety factor 1.8, little margin. PETG: 2.11 mm, fine.
Creep: within 20 C of its HDT a load held for days slowly bends it (rule of thumb).
Expansion: it grows 0.14 mm over its 77 mm; held tight at both ends it pushes with 4.4 MPa, 14% of its hot strength.
Warp risk on the bed: low (0.28 mm corner lift from 0.35% shrink over 80 mm). Fix: none needed.
NEXT: ask the person: hot summer shade reaches 41.5 C, the 20 N load leaves a safety factor of 1.8 there (2 is fine); print it in PETG?
```
