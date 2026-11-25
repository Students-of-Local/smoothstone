# A landmark: stone landmark

Any model runs one command. A large model can also write the shapes a landmark lacks, once, for every model after it.

## 1. Build it

```
stone landmark "<name>"
```

It looks the name up, reads the map and the landmark's cited facts, builds it to the size in the request, checks that it
prints and draws `build/views.png`. Follow its NEXT line. Nothing else is needed when it says Part ready. `--size 180` sets
the longest side in mm.

## 2. Look at it

Open `build/views.png`. Say what it shows and what it lacks. `refs/landmark.json` has every number, its source, and whether it
was guessed. Never call a guessed size measured.

## 3. It is refused, or a part of it is wrong (tier L)

The map does not hold every landmark: a bridge is a flat deck, a tower's splayed legs are a circle. Write what is missing:

1. Read docs/REFERENCE_PARTS.md. It is the whole format: prisms, lathes, beams and openings in metres, copies, a lean, a base.
2. Find real numbers. Owner, engineering, survey and museum pages first (research.md). Open each page you cite and put its URL
   on the fact or the part. A number nobody published takes `"guess": "<how you chose it>"`. Never invent a citation.
3. Save it as `pack.json` in the job folder and run `stone landmark "<name>" --refs pack.json`. A bad part is named by its
   place in the list.
4. Open `build/views.png` beside two photographs. List what differs, fix the largest difference, build again. Stop when
   the next difference is smaller than 1 mm at print size.

Start from the closest pack in src/smoothstone/landmarks: space-needle.json (legs, core, saucer),
leaning-tower-of-pisa.json (arcades, columns, a lean, replacing only some of the map).

What makes one read as itself at print size:

- The outline first. Get the heights, the widths at four or five levels and the big gaps right before any detail.
- Open what is open. An arch or a portal you can see through reads from across a room; a recess does not.
- Keep the thick things thicker than the thin ones. If hangers are widened to the minimum, the towers must still be wider. Use
  `least` 0.8 on parts held at both ends, and draw fewer of them.
- Every part meets another one or the ground, with 0.3 m of overlap. A part in the air gets a post you will not like.
- Give it a base that means something (water, lawn, steps) with `plinth` when the plan underneath is a poor shape.

## 4. A pack worth keeping

It built, it looks right beside the photographs, and every number has its source or its guess: offer it to smoothstone as
`src/smoothstone/landmarks/<name>.json`, so a small model builds the same one from its name alone.
