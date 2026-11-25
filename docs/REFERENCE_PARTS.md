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
3. `replace` says what of the map goes: `"none"` (the default), `"all"` (the map is not asked), or a list of OSM ids.
4. A part thinner than a print can hold is widened to 1.2 mm, and the build says so.
5. Openings are cut after every solid is joined, and cut the map's parts too.
6. After `copies`, at most 400 parts. A bad part stops the build, named by its place in the list.
7. `lean` tips everything above the base, map parts too, about the ground at the origin.

## Format

    "parts": {"source": "https://...", "origin": [lat, lon], "axis": 0, "replace": "none", "value": [PART, ...]}
    "lean":  {"source": "https://...", "value": [degrees, bearing]}

| kind | fields |
| --- | --- |
| `prism` | a plan, `at`, `turn`, `from`, `to`, and any of `roof` + `roof_rise` (`to` is the roof's top), `top_scale`, `top_shift` [x, y] |
| `lathe` | `at`, `profile` [[z, radius], ...] with z rising |
| `beam` | `path` [[x, y, z], ...], `size` [width, height] |
| `opening` | `at`, `turn` (the way you walk through), `width`, `depth`, `from`, `to`, `arch` (true: a round head) |

A plan is one of `rect` [x, y], `circle` radius, `ngon` [sides, radius], `ring` [[x, y], ...]. `turn` is degrees clockwise.
Roofs: flat, pyramidal, gabled, hipped, dome, onion, round, skillion. Any part takes `id`, `source`, `guess` and `copies`:
`{"around": [x, y], "count": n}` (n in all, evenly turned), `{"row": [x, y], "count": n}` (n in all, stepped by x, y) or
`{"mirror": "x"}` (and its mirror image across the y axis) or `"y"` or `"xy"` (all four).

## Cases

| input | result |
| --- | --- |
| `rect` [4, 6], `from` 0, `to` 10 | a 4 x 6 x 10 block; x extent 4 m at scale |
| the same, `axis` 90 | y runs east: 6 m east, 4 m north |
| `top_scale` .5 | the top is half the plan |
| `top_shift` [3, 0] | the top's centre is 3 m along x from the foot's |
| `lathe` [[0, 5], [10, 1]] | a cone 10 m tall |
| `beam` of two points | a bar between them, of `size`, never under 1.2 mm |
| `opening` 4 wide through a 10 m wall | light through the wall; volume falls by the opening's |
| `copies` around, 4 | four parts at 90 degrees |
| `mirror` xy of a part at [3, 4] | four parts at [±3, ±4] |
| `replace` all | the map is never asked |
| `replace` [7] | OSM part 7 is gone and the rest stand |
| `lean` [4, 180] | the top moves south by height x tan 4 degrees; the base stays level |
| a `guess` | the record's heights are marked guessed with that reason |
| no plan, `to` <= `from`, a string for a number, an unknown kind or field, `radius` 0, 401 parts | refused, naming `parts[i]` |
| a fact without a source | refused, as today |
