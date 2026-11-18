# Research before you model

A part is only as good as the facts under it. Before stone set, find out what the thing really
is and write each fact down with where it came from. Use this card for every request that names
a real object, product, person, animal, character or artwork.

## 1. Say what kind of request it is

- Fits something real: a phone case, a mount, a cover, a replacement part, a holder. Go to 2.
- Looks like someone or something real: a mini figure, a bust, a pet, a statue. Go to 3.
- Copies a famous artwork: a statue, a carving, a relief. Go to 4.
- Made up, with no real thing behind it: skip this card.

## 2. Things that must fit: exact numbers

Every size the part touches needs a number from a source, not a guess.

1. Find the maker's own drawing or spec first. These beat every other source:
   - Apple: Accessory Design Guidelines and the dimensional drawings at
     developer.apple.com/accessories/dimensional-drawings/ (a PDF per iPhone, iPad and Watch,
     free, no sign-in). They give the body size, corner radii, camera plateau, buttons and ports.
   - Other phones, tablets and gadgets: the maker's spec page, then its accessory or case-maker
     guide if it has one.
   - Screws, bearings, magnets and connectors: the part's datasheet or the standard (ISO, DIN).
2. Check each number against a second source. If two sources differ by more than 0.2 mm, use the
   maker's drawing and say which you trusted.
3. No published number: measure. `stone measure <photo>` with a ruler, a bank card or a US
   quarter in the photo, or ask the person for a caliper reading. Never invent a size.
4. Write every number with its source into the job: `stone note "<name> = <value> mm, <source URL>"`.
5. Add clearance for the fit you want, per side, before you set the recipe:
   - Rigid case (PLA, PETG) around a phone: 0.2 to 0.3 mm.
   - Flexible case (TPU): 0 to 0.1 mm, it stretches on.
   - A hole for a button or port: 0.5 mm bigger than the button all round.
   - A peg in a hole: 0.2 mm. A press fit: 0.05 to 0.1 mm.
6. For anything that must fit snugly, print a fit test first: a 10 mm slice of the part, then
   the whole thing.

## 3. Things that must look like someone

1. Get photos from more than one side: front, three-quarter, side, and the back if you can.
   `stone find "<who>"` gets free-licensed photos with credits. The person's own photos are best.
2. Pick the lead photo: face toward the camera, good light, the look people know.
3. List what makes them recognizable before any model draws anything, five to eight points:
   hair (color, part, length), glasses (full frame, half-rim, rimless, shape), facial hair, the
   clothes they are known for, an object they carry, posture. Write the list with
   `stone note "look: ..."`.
4. After the style render, check it against the list point by point. A missed point (heavy frames
   on someone who wears thin half-rims) means style again with that point in the request, before
   the 3D step.
5. Scale: a mini figure is usually 60 to 100 mm with its base. Pick a height and keep it.
6. Name the photographers when you share the part (credits.txt).

Characters someone else owns (movie, game and toy characters, brand mascots): make an original
figure in that spirit or decline. A generic mini figure is fine; a copy of a trademarked toy is not.

## 4. Famous artworks: use the real thing first

1. For a public-domain sculpture, look for a real 3D scan before generating anything. Museum
   open-access scans are measured from the statue itself, so no model can beat them:
   - Scan The World (myminifactory.com/scantheworld)
   - Smithsonian Open Access 3D (3d.si.edu)
   - The museum's own open-access page (many publish CC0 scans)
2. Check the license on the scan page and keep the credit.
3. Scale the scan to the size asked for, then run it through stone's checks and fixes.
4. Generate only when no scan exists, and then use several photos of the work from different
   sides, as in 3.

## 5. Done when

Every number the part depends on has a source or a measurement, the look list exists for a
likeness, and both are in the job's notes. Then go on with stone set.
