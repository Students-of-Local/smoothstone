# Reference parts

What a landmark needs and the map does not have: a bridge's deck and cables, a tower's splayed legs, a lean, an arch.
A strong model writes them once from cited sources, as two facts in a reference pack
(`src/smoothstone/landmarks/<name>.json`, or `stone landmark "<name>" --refs pack.json`). Any model then builds the landmark
with the same one command.

## Rules

1. Every number comes from the fact's `source`, or from the part's own `source`. A number nobody published is allowed only
   with `"guess": "<how it was chosen>"` on that part, and the build marks it guessed.
2. Metres. `at`, `path` and rings are [x, y] (path: [x, y, z]) from `origin`. y runs along `axis`, a compass bearing in
   degrees (0 = north), and x to its right. z is up from the ground the landmark stands on.
3. `replace` says what of the map goes: `"none"` (the default), `"all"` (the map is not asked), or a list of OSM ids
   the map has.
4. A part thinner than a print can hold, across or up, is widened to 1.2 mm, and its record says so. A part stops at the
   bed. `least` (0.8 to 1.2 mm) asks for a finer minimum on a part held at both ends: a hanger, a cable, a lattice bar. A
   free-standing part keeps 1.2. An opening has no `least`, and a part with a roof has none: a roof keeps its 1.6 mm tip.
5. Openings are cut after every solid is joined, and cut the map's parts too.
6. After `copies`, at most 400 parts. A bad part stops the build, named by its place in the list.
7. `plinth` is the base's outline, where the plan under the parts makes a poor one: water under a bridge, or a lawn. Whatever
   stands on the ground past it keeps its own base. It counts in the print's length. It takes `at`, `turn`, `source` and
   `guess` as a part does, and replaces the mapped grounds of a site. A lattice tower has its own base and refuses it.
   A raised part needs the plinth or another part under it.
8. `lean` tips everything above the base, map parts too, about the ground at the origin.

## Format

    "parts": {"source": "https://...", "origin": [lat, lon], "axis": 0, "replace": "none", "plinth": PLAN,
              "value": [PART, ...]}
    "lean":  {"source": "https://...", "value": [degrees, bearing]}

| kind | fields |
| --- | --- |
| `prism` | a plan, `at`, `turn`, `from`, `to`, and any of `roof` + `roof_rise` (`to` is the roof's top), `ridge`, `top_scale`, `top_shift` [x, y] |
| `lathe` | `at`, `profile` [[z, radius], ...] with z rising |
| `beam` | `path` [[x, y, z], ...], `size` [width, height] or one for each point of `path`, `round` (true: an oval section) |
| `opening` | `at`, `turn` (the way you walk through), `width`, `depth`, `from`, `to`, and either `arch` + `arch_rise` or, in place of `width`, `from` and `to`, an `outline` [[x, z], ...] |

A plan is one of `rect` [x, y], `circle` radius, `ngon` [sides, radius], `ring` [[x, y], ...]. `turn` is degrees clockwise.
Roofs: flat, pyramidal, gabled, hipped, dome, onion, round, half-hipped, gambrel, mansard, skillion (high at -y, falling toward +y).
`ridge` is the ridge's direction, in degrees clockwise from the part's y; without it the ridge follows the long side. Any part takes `id`, `source`, `guess` and `copies`, and any solid without a roof takes `least`:
`{"around": [x, y], "count": n}` (n in all, evenly turned), `{"row": [x, y], "count": n}` (n in all, stepped by x, y) or
`{"mirror": "x"}` (and its mirror image across the y axis) or `"y"` or `"xy"` (all four).

`arch` is true or `round` (rising half the width; another `arch_rise` makes it an ellipse), `pointed` (equilateral; a higher
rise is sharper) or `triangle` (half the width). `arch_rise` is part of the height from `from` to `to`.

## Cases

| input | result |
| --- | --- |
| `rect` [4, 6], `from` 0, `to` 10 | a 4 x 6 x 10 block; x extent 4 m at scale |
| the same, `axis` 90 | y runs east: 6 m east, 4 m north |
| `top_scale` .5 | the top is half the plan |
| `top_shift` [3, 0] | the top's centre is 3 m along x from the foot's |
| `rect` [4, 6], `roof` gabled | the ridge runs along y; with `ridge` 90, along x, and its gables face left and right |
| `lathe` [[0, 5], [10, 1]] | a cone 10 m tall |
| `beam` of two points | a bar between them, of `size`, never under its `least` (1.2 mm unless given) |
| `beam` with `size` [[4, 4], [2, 2]] | 4 m square at the first point, 2 m at the last |
| `beam` with `round` | an oval section of `size`; a vertical one 2 x 2 is a round post |
| `least` .8 on a thin beam | 0.8 mm wide at print scale |
| `plinth` `rect` [40, 60] under a 4 x 6 block | the base is 40 x 60 m at scale, and 60 m is the print's length |
| a part on the ground outside `plinth` | the base takes in its foot |
| `least` .5, two sizes for three points, a plinth with no plan | refused |
| `opening` 4 wide through a 10 m wall | light through the wall; volume falls by the opening's |
| `opening` 4 wide, `arch` pointed | its head is the top 3.46 m; `arch_rise` 5 is sharper, 1 is refused |
| `outline` [[0, 0], [1, 0], [9, 8], [8, 8]] | a diagonal slot; left out where its 0.7 m would print under 0.6 mm |
| `copies` around, 4 | four parts at 90 degrees |
| `mirror` xy of a part at [3, 4] | four parts at [±3, ±4] |
| `replace` all | the map is never asked |
| `replace` [7] | OSM part 7 is gone and the rest stand |
| `lean` [4, 180] | the top moves south by height x tan 4 degrees; the base stays level |
| a `guess` | the record's heights are marked guessed with that reason |
| no plan, `to` <= `from`, a string for a number, an unknown kind or field, `radius` 0, 401 parts | refused, naming `parts[i]` |
| a fact without a source | refused, as today |
