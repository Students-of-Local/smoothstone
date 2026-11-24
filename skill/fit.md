# Make it fit: stone fit

Run this card when a part has to fit something: a screw, a bearing, a shaft, a lid, a product.
`stone fit` says what each hole and peg will really print at and whether it fits.

## 1. After stone build, run stone fit

```
stone fit
```

It finds the round holes and pegs and the recipe's fit settings. Each line gives:

- the size in the model and the size it will print at;
- what it is for (an M3 screw, a 608 bearing, a lid) and what that needs;
- fits, tight or loose, and the change when it is wrong.

When something is tight or loose, the NEXT line is the `stone set` that fixes it. Run it, then
`stone build`, then `stone fit` again. When everything fits, NEXT goes on with the job.

Holes print small: a round hole is made of flat sides, and plastic squeezes inward as it prints.

## 2. Fit words

- press: pushed in hard, stays put (a knob on a shaft, a bearing in its seat).
- snug: goes on by hand and holds (a lid, a cap).
- slide: moves freely (a peg in a hole, a part in a holder).
- loose: lots of room (a snap clip, a rough fit).

Clearance is always per side: 0.2 mm per side makes a hole 0.4 mm wider than the peg.

## Example

```
$ stone fit
Fit on a typical printer: holes 0.20 mm small, outer sizes true, sizes +/- 0.20 mm
PLA shrinks 0.06%
1 hole_d=3, 2 holes, 96 sides: prints 2.80 mm; M3 screw takes 3.2 to 3.6 mm (ISO 273): tight.
  Change: set hole_d=3.6, prints 3.40 mm (ISO 273 medium for M3: 3.4 mm)
NEXT: stone set panel hole_d=3.6
$ stone set panel hole_d=3.6
$ stone build
$ stone fit
1 hole_d=3.6, 2 holes, 96 sides: prints 3.40 mm; M3 screw takes 3.2 to 3.6 mm (ISO 273): fits
NEXT: none, the part is ready
```

## Limits

- Only round holes and pegs are measured, plus teardrop holes printed on their side. Slots,
  square holes and snap clips are judged only through the recipe's own settings.
- Every number is a typical printer's, good to about 0.2 mm. Say so if the fit matters.
