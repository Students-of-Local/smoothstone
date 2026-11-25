# Log

- 2026-11-14 Held-out set sealed before any tuning run: 5 requests in evals/heldout/, two of them
  from pictures (dog.png, duck.png, new icons not used anywhere else). They run once, after the
  skill, the tool and the recipes are frozen. Any change after that is a new round with new
  held-out specs. SHA-256:
  cff59dca4ec3c8142d400716ff594564bd3c2d4e0ea3219baead8562f78c9cbd  evals/heldout/dog.png
  ade0daf8417d60a52f5b831991222f3d39ec75001c3acb1fbd809e72971d8573  evals/heldout/duck.png
  4ec8c33077771689781acae45fdcf5a638a256e9de5aa39add33f33a65ca66d0  evals/heldout/h1_gridfinity.json
  47515abcd984992970296433a6ec22933abe1e37a509825dc29ba6d962a98b9a  evals/heldout/h2_phone_stand.json
  e2f9f2cd03d7333d011bf2ebab7f72f2b610233ffc6e2e2074ea9f42f8d628d6  evals/heldout/h3_vase.json
  49be2a8a35e7ff88d8cfd3bcf22a7e9db0ea770f562ac1fcd37a641412fac19a  evals/heldout/h4_dog_keychain.json
  f02861702328565b6c3199be1de81113b891866152412121ec465fbd59807cb2  evals/heldout/h5_duck_cutter.json
- 2026-11-14 Held-out set 2 sealed, written after held-out 1 showed a matcher miss and before any fix for it, so a
  later fix gets a fair test. 6 requests, 2 from pictures (turtle and anchor, Material Design Icons, Apache 2.0,
  drawn from the JetBrainsMono Nerd Font). Nothing has run on them. SHA-256:
  3598fe10d920c2a2b639d76aa627eb52100d5475966240c8ac54f9c8e60229b6  evals/heldout2/anchor.png
  5d0e7288dd4dc27b495ca9a189d8bb16b7400850d90832bfbe15375a5cc7d79f  evals/heldout2/k1_office_sign.json
  98ae813f40184ad53c06480f9c117a622335a9c589697a80929f85c55222de26  evals/heldout2/k2_tool_box.json
  a304da3c5ddf4945cabb559f11464cbf44f8616fb4e2e5927db50e8e72ffb653  evals/heldout2/k3_hook.json
  c102fa7d4f352e9a3cf8583f26c58d4f969f397153bc8adddda47b48a0d1f01a  evals/heldout2/k4_gear.json
  8db7054993d9f2f550af7a05917be31da30ff90f1a44e728c96fd5ddbe0421de  evals/heldout2/k5_anchor_cutter.json
  bab8f102ffebfb702301a660733667547b47fea9e42946d2a00665447ec46e34  evals/heldout2/k6_turtle_relief.json
  ffb43668cb0eac74d82520a30c7fa2cabc334e0370595f2530e22710283b953b  evals/heldout2/turtle.png
- 2026-11-14 Held-out set 2 is withdrawn as a measurement: I wrote it, and my later matcher cases borrowed its
  phrasing ("a box with a lid, 120 mm wide"), so it no longer tests anything blind. It stays in the repo, unused.
  Held-out set 3 sealed instead: 8 requests written by a separate Opus subagent that read only the recipe
  catalog (names, parameters, ranges, help), never the matcher, tests, cards or evals. Its expectations are kept
  as written. Pictures are the turtle and anchor from set 2. Nothing has run on it. SHA-256:
  3598fe10d920c2a2b639d76aa627eb52100d5475966240c8ac54f9c8e60229b6  evals/heldout3/anchor.png
  2c7751a687a618f8ce5ea59ed94d61683fec14fb253023c9fa025aa6916a9cea  evals/heldout3/b1_turtle_cutter.json
  078ba860657c85aaf5b929b9d1a3498ab12c5de495254d87ac1bdbbd3ba01955  evals/heldout3/b2_anchor_keychain.json
  ce33f90a1f07e4719afe4896b8f941c250b6196bc2dc897c26581f9a1afc923a  evals/heldout3/b3_gridfinity_bin.json
  83acc60ee38fb38e35f8d2a28dabaa87da6792fcc4fb132f355455da4b74c8c8  evals/heldout3/b4_fan_guard.json
  1c79a24e55925567095aad43eafb2f6900c75f795ce90a29461e86a9c83edce3  evals/heldout3/b5_spur_gear.json
  972bd7aa751d9f0c69e83a4374769b28f3cd59dff7638cb48cd1e6334bada204  evals/heldout3/b6_wall_hook.json
  08f08cfc0e5da1d5d7f62f93aec4076d4c1fb5a258512b06afa302c4794419bd  evals/heldout3/b7_planter_saucer.json
  c647053796f6d11059d0d5c7112eb4ee73c6d68c8e487872ff15a2905bf7864b  evals/heldout3/b8_cable_comb.json
  ffb43668cb0eac74d82520a30c7fa2cabc334e0370595f2530e22710283b953b  evals/heldout3/turtle.png
- 2026-11-15 Matcher fixes for the misses set 3's NEXT baseline found (2acc951): spelled numbers to 99,
  "one inch" as a length, bool switches by name with "no"/"without", gear and saucer phrases, a bare number
  right after its parameter's name, lengths never fill a count, cable_comb adds 0.3 mm to a cable size. Set 3 is
  spent as a measurement of these fixes: its run (frozen 8fdf099) measures the code before them. 75 tests pass.
- 2026-11-15 Held-out set 4 sealed to measure 2acc951: 8 requests by a separate Opus subagent that read only
  the full parameter catalog, never the matcher, tests, cards, evals or earlier wording. 2 are pictures it drew
  (fish, cat). I have not read the requests. Nothing has run on it. SHA-256:
  442eef802a95c7f574d26eb920ab3190e63374bae021efb3fa27b5f38cdebecb  evals/heldout4/c1_box.json
  ad9574520f70f0128b3df328c41dd88883a568cd6481230d78236da4c56a02fa  evals/heldout4/c2_panel.json
  bfbd6ba07819e1eea9c7cb426859d93b2446f19818d7a1a35aee739cd7686901  evals/heldout4/c3_hook.json
  ea07cbe5bd326da37ad292bfef775f9931cf82dfabfe5c7d47fac8c8d1a7f938  evals/heldout4/c4_vase.json
  0b19c2380eef5abb02a67332040232c16ecc779246730a61ebd17ed8b463b276  evals/heldout4/c5_cablecomb.json
  cc0fbacc5d4cdd1330f273a9f31876f43e6bdd42c7f2469b065319e68ac7c5b0  evals/heldout4/c6_gear.json
  535df6afb08e224c4743c05eb0e465d58a062b9f8f7c80254c899279665d3295  evals/heldout4/c7_cookiecutter.json
  1771baa492dc8e98365ca70cce26c9604241f52a6bb9b6cc3ed5778606040639  evals/heldout4/c7_fish.png
  f90dfa32b06494656e2e8e43f9af6740253ff369393ffda1c63fc495c3e561a0  evals/heldout4/c8_cat.png
  a9b6ca5c35d6b869df76fd7e9a89d9c7616ae98a076952dcad2d99c875e7cf33  evals/heldout4/c8_keychain.json
- 2026-11-15 02:35 Blind set 3 results (frozen 8fdf099, before the matcher fixes). NEXT driver 3/8. LFM3-1.7B: S card
  34/40, S card compacted at step 3 27/40, no card 31/40. Every b8 cable comb run but one set slot_w=5.0 for 5 mm
  cables (spec wants 5.2 to 5.5, clearance); after compaction the planter runs followed NEXT part=saucer (1/5); hook
  width 25 vs 25.4 for "one inch". The S card beat its own NEXT lines: the model fixed magnets, gear style and saucer
  itself. All of these misses are what 2acc951 fixes; set 4 measures that. Output runs2/heldout3, runs2/heldout3.txt.
- 2026-11-15 05:10 Blind set 4 results (frozen ad5d81a). NEXT driver 3/8. LFM3-1.7B: S card 20/40, S card compacted
  20/40, no card 24/40. Worse than set 3 and the S card trails no card. Causes, all tool side: (1) cookie cutter,
  S card 0/5: the model typed the path to silhouette.svg instead of image=image; the silhouette keeps the fish eye
  hole, flange=0 left the cutter in 2 bodies, that FIX names no setting, and NEXT looped to stone show until the
  steps ran out. (2) panel "4 arcade buttons" read as nothing, cutouts stayed 2 (0/15 runs). (3) cable comb "4 mm
  thick" got no clearance and "snap in" no grip (0/15). (4) gear "5mm D shaft" got bore 5.0, no clearance (0/15).
  Fixes on main: a path to any of the job picture files means image (the recipe kind); "an inch"; unquoted label
  text after engrave/that says; counts look one word past the number; clearance unless the 2 words before or 1
  after the number name the parameter; bore fit_add 0.2; "no flange" sets a 0-able size to 0; ches/shes/xes stems;
  comb grip phrases; panel count words; hook reach help shortened. All 32 specs in the four sets match, 85 tests
  pass (the cutter test fails on the old code), sheet all PASS. Set 4 is spent; a new blind set 5 measures this.

## 2026-11-15 blind set 5 sealed

A fresh writer saw only the regenerated parameter catalog and wrote evals/heldout5 (8 specs, 2 drawn pictures, file names that hide the recipe). I have not read the specs. Hashes:

```
98a33e40147aa38c37fec45e5a2348f0f2b9a201b3320414a56e21ef60c74492  d1_alder.json
24fe5474d3025bec7be3f32122d225e6c7c7b3fb806b8434fb119463a5d1abad  d2_birch.json
481aad5aa2ab8f2a9dd8d190fbf18acd5c9fa244d99b4d307a37a53ec735b998  d3_cedar.json
6caa7b03e7bf25db2e3c6a6ff93208f4d4d8fe43c6142bbc66baa743345da118  d3_pic.png
222bd4b2b7b6e934c78fb09094d31e25e16a0edacda148a4d87d40ba31e014bc  d4_dogwood.json
a08ff2d0d66116120cdbb37dbf0d180425dcf08460fb8a519354f6a90758426c  d4_pic.png
dfdd89787c68a92a17343957320223e299d9bb8bb611664d05fb729113f2f9cb  d5_elm.json
2751c94d141fe334eb72378a215683056cc6e5e8442088c3d5307c765a60c2b6  d6_fir.json
9aac2c940b84c16998855ebc7804bfead6bef6aab915f322bea903e7e24d34e8  d7_ginkgo.json
2e861ef5dcc1fa6642014c095bca709989387e96f7d8ad3c0759361ec95c1f25  d8_hazel.json
```

It measures c4201e0 from a frozen worktree.

## 2026-11-15 blind set 5 results (c4201e0)

Run from frozen/894a97d, 5 seeds a condition, LFM3-1.7B on llama-server.

- NEXT lines alone, no model: 4/8.
- S card: 37/40.
- S card, compacted after step 3: 24/40.
- No card: 34/40.

Compaction is the weak spot. After a compaction the model leans on the NEXT line, so the compacted runs fail where NEXT fails. What it found, all tool side:

- "leave off the frame", "I don't need a cable slot": contractions and "leave off" were not read as no. The matcher now checks the 4 words before a name and reads don't, doesn't, won't, leave off, leave out, omit, drop and no need.
- "without hanging holes": a choice param with a none value now goes to none.
- "120 tall" with no unit: a bare number named by the word right after it now fills that size.
- The relief model typed the picture path it was given at stone new. stone sent that raw png to surface(), the plaque built in 2 pieces and raising base_t never fixed it. The picture given to stone new now means the job image.
- On a sign it typed icon=image=<path> and image=<path>. stone refused both and suggested rim. image= now means a recipe's one picture param, and a doubled image= is stripped.
- The model-free NEXT run on set 4 still failed the panel: 4 buttons of 22 mm do not fit the default 60 mm plate, and stone's fix put the count back to 2. Recipes can now name a grow rule for an assert, and the panel widens to fit (128 mm here).

NEXT driver on every held-out set after the fixes: 29/29. 94 tests pass. Set 5 is spent; set 6 measures this cleanly.

## 2026-11-15 blind set 6 sealed

Same protocol as set 5: a fresh writer saw only the regenerated catalog and wrote evals/heldout6 (8 specs, 2 drawn pictures). I have not read the specs. It measures 25a0b83. Hashes:

```
457b372c391476778e32e715bcc6e8dc3eccd08b98c51a137d9417ddef446a9b  e1_marrow.json
77529370abf98ce00655308ce86d9912b1a3396c5d58026b72ff0eeb8edc9791  e2_pic.png
f58487d9ec8ab1d7d2d686171807fd8469f2f51f430bf3b7f9f33aa2648cd48f  e2_quill.json
a5894e06b88f8f56a1d6127400f593be16b2343dccc8cb8922346ef15b0f5cbb  e3_lantern.json
c15d1a94a3ccf109f7a8465fe2feba1989d10258f7c83ad32f17e56821da108d  e4_pebble.json
235504cfe5c58054a911d09871654107b1de1522d146881b803bf05cb18632fa  e5_pic.png
c26ada1d3dc764474e57920f6d903c7fd43dc19c1048376563fc7ecbd38758f8  e5_thistle.json
286de16496aa69b961604ce95e8740f8cbeba6f1877834d2cd60666f946378b7  e6_cobalt.json
4d0dfb307bdd5b22785429dad6c729781b8acec6d96767709abc84ffa80d6332  e7_juniper.json
9c63ddb962eb2ef32c007f2b82d4bf4227456b6581ed86a110f9ca8d5271a7bb  e8_saffron.json
```

## 2026-11-15 blind set 6 results (25a0b83)

Run from frozen/066096c, 5 seeds a condition, LFM3-1.7B on llama-server. This is the clean measurement of the set 5 fixes.

- NEXT lines alone, no model: 6/8.
- S card: 39/40.
- S card, compacted after step 3: 38/40 (set 5 was 24/40).
- No card: 37/40.

Misses: round_bottom left on in 2 compacted runs, font sans for mono in 2 runs, and 2 no-card lithophane runs that never finished a part.

## 2026-11-17 figure recipe

A new recipe makes a figure of a person, animal or object from photos, on a drum plinth with the name raised on its front. The driving model only sets parameters. When there is no photo, build says FIX and NEXT is `stone find "<who>"`, which pulls license-filtered photos from Wikimedia Commons and Wikidata. Four local helpers then run one at a time, each skipped when its file is already there:

- describe: LFM3-VL-2B 4 bit through mlx-vlm, 3.0 GB, 11 to 16 s, one sentence on how the subject looks.
- style: FLUX.2 klein 4B 4 bit through mflux --low-ram, 7.8 GB, 1 to 2 min, a chibi front view on white.
- lift: Hunyuan3D-2mini on MPS, octree 256 and chunks 4000, 9.04 GB peak, 234 s. The defaults (octree 380) peaked at 12.35 GB.
- repair: trimesh keeps the main body, closes it and decimates to 250k faces.

Driver: LFM3-1.7B Q4_K_M on Parish1's CPU through llama-server, 1.2 GB RSS, request evals/figure/f1_jensen.json, S card.

- Run 1 (runs3): PASS, but the lead photo was serious and three quarter, so the figure lost the jacket and the smile, and find downloaded the same file twice.
- Changes after run 1: the describe step (the style model kept the likeness far better with that sentence in its prompt), clothing in the person prompt with no expression, a friendly smile in the chibi look, and find dedupes by title (test_lead_is_not_downloaded_twice).
- Run 2 (runs4): PASS in 8 commands: status, recipes, show figure, set figure height=90 name=JENSEN, build (FIX, then find), find "Jensen Huang", build (329 s, Part ready), status. The figure is 61 x 61 x 90 mm, one watertight body, 253,354 faces.

Measuring from a photo: an outline traced from a photo with a ruler or card in it took the ruler too. image now crops to the bbox that measure found when the photo is the same file, in either order (test_outline_leaves_the_ruler_out, which failed before the fix).

Suite: 117 passed.

## 2026-11-17 phone_case recipe

A fitted case for the iPhone 17, 17 Pro, 17 Pro Max and Air. Every fit-critical number is in recipes/phone_case/devices.json with its source page in Apple's dimensional drawings and how it was read; tools/phone_devices.py turns that file into devices.scad and the recipe's dims (`--check` fails when they are stale, and a test runs it). The plan-view corner is a Catmull-Rom curve through Apple's Detail A points, clamped to the straight sides and convex-hulled, because the raw spline overshot the sides by 0.035 mm.

Measured cavity at the phone's mid-height (test_cavity_is_phone_plus_clearance), rigid, 0.25 per side:

- iPhone 17: 71.950 x 150.110 for a 71.45 x 149.61 phone
- 17 Pro: 72.350 x 150.510 for 71.85 x 150.01
- 17 Pro Max: 78.480 x 163.930 for 77.98 x 163.43
- Air: 75.200 x 156.680 for 74.70 x 156.18

TPU (0.05 per side) matches the same way. All eight are within 0.001 mm of phone plus 2 x clearance.

Geometry is polyhedron lofts through exact profile rings, not unions of hulls of 0.01 mm slabs. The slab version passed every check on part.off but wrote a part.stl with about 200 edges shorter than 0.0001 mm that loaded as 150 to 240 bodies and not watertight; the STL is the file people print. Two more coincidences were removed: the camera opening and the fit ring's floor cut now reach 0.05 mm into the wall instead of lying on the cavity's face. Every slot also starts past the lip's inner edge, because on the Air (lip reach 0.93) the USB-C and Camera Control slots left a 0.18 mm fin of lip tip.

min_wall is 0.6 for this recipe, not the 0.8 default. The 3rd percentile lands on the intended tapers: the lip tip (0.55 tall at its inner edge, an upright face and a 0.2 chamfer so it is not a knife edge) and the V ceilings of the button slots, which keep every slot under 45 degrees. A 4 mm Air fit ring is the worst case and passes; full cases read 0.99. Other recipes use 0.5 to 0.7.

The recipe is tier S, like every other recipe: at tier M, a new job (tier S by default) hid it and stone recipes sent the model to box.

Not in the drawings, so assumed or derived (each marked in devices.json):

- No single corner radius on any phone; the curve is drawn through the points.
- 17 Pro and Pro Max: the plateau's lower edge has no number. The opening uses the dimensioned area on sheet 4 that contains it (58.01 from the top, R12 and R14 corners).
- Air: no plateau corner radius (the margin rounds it); left button heights assumed at mid-thickness 2.82; the 2.71 port height does not say which face, so the slots cover both; the corner's tangent ends at 19.36 are derived.
- 17 Pro and Pro Max: the 1.88 lens glass label reads from the back plate on one sheet and from the plateau on the other. The case uses only the plateau height.

Stone flow in a temp job: new "A case for my iPhone 17 Pro with DONOVAN on the back", recipes (phone_case first), show (phone=iphone_17_pro text=DONOVAN, nothing left over), set, build: 10 PASS, Part ready.

## 2026-11-18 asking for sizes, change requests, grommet (LFM3-1.7B, card S)

stone set now refuses when the request names something the part must fit and gives no number and no known product. NEXT becomes "ask the person: <question>"; stone note "<answer>" records the answer in brief.md and sends the model back to stone show. A product chosen in the set line (phone=iphone_17_pro) counts as the answer, so stone does not ask twice.

LFM3-1.7B Q4 on CPU, card S, seeds 1 to 3, full context and compacted at step 3:

- Change requests (evals/feedback k1 to k3): 17/18.
- a1 "a cover for the cable hole in my desk", answer "60 mm across": 0/6 before (it guessed a size), 6/6 now, grommet hole_d 60.
- a2 "a case for my phone", answer "an iPhone 17 Pro": 3/6 before the set fix (stone asked again after the model set the phone), 6/6 after.
- t7 "a TPU case for my iPhone 17 Pro Max": 6/6.

New grommet recipe (desk cable hole cover, lip down). The panel grows to fit a round cutout taller than the plate instead of failing an assert.

Figure: the style prompt keeps glasses as thin as in the photo. Thin frames in 4 of 6 seeds, against 2 of 6 before.

## 2026-11-18: the figure Creality Print called broken

Creality Print flagged the small model's Jensen figure: 14 non-manifold edges. Every stone check had
passed, because the checks read OpenSCAD's float64 OFF while the STL that shipped was float32. Twelve
faces whose corners were 1e-9 mm apart collapsed once written, and one sliver had zero area.

Fix: `stone build` rebuilds the mesh through manifold3d at float32 (`clean.for_slicer`, with a light
quadric pass if a sliver is left), and checks run on the shipped STL, including a new `slicer` check
(`clean.slicer_view`: float32 merge, collapsed and zero-area faces, edges not shared by exactly two
faces). The figure went from 13 bad faces to none, volume within 0.01%. Every image-free recipe still
passes. Tests: tests/test_clean.py.

## 2026-11-18 blind set 7 sealed, and figures that look like the person

evals/heldout7 holds six figure requests a fresh writer wrote before this tuning (commit 9953437). I have not read them. They run once, after the tool is frozen. Hashes:

```
649ecb122bd2f76fe3e7ce4ba6bd7fc7e94e50bac651a97796d6d89d8ddfacc0  g1_ash.json
37326fb93f1e0be8abde98270505ed9fe87aef124907297edab022392fdc0a98  g2_beech.json
359aa6616e2e9f411e8fb032dfdb210723fa661f5fabfad3a8b1f943f2bc2b84  g3_cedar.json
ba5902852e15892f02a18333513e7b226e7615baaadab18487f2e6f8c4b0b8c1  g4_hazel.json
be92ecd7bd9c7d3a74bed345deffc3f4a9b935412058434010d340c78684b535  g5_oak.json
04e9a2ade3cfd62b421ff1f727e450b6b839a3c24c9cb70a05114319faeb4fa9  g6_yew.json
```

The owner said the chibi Elon figures "look nothing like elon". A blind Opus likeness judge (evals/judge_likeness.py: a Wikipedia reference image the tool did not pick) scored the chibi 5. With a face crop as the first style picture, a large real head and no LFM3-VL description in the prompt, the same photo scored 9 on two seeds. That look is now the person default (7231dcb). Cold LFM3-1.7B runs, card S, seed 1: Elon 9, Jensen 9, DHH 7 (his hair came out darker than the photo). The Mac's claude is not signed in, so those runs were judged here with evals/rejudge.py. r4_elon_likeness asks 8 for Elon.

## 2026-11-19 review of PR 23: what a figure is of

The round 1 reviewer read the PR's files, heldout7 among them, and quoted two of its requests (g3,
g6) to show `subject_from_request` taking "base" from "the front of the base" and "Yankees" from
"like his Yankees uniform". The parser now takes what the figure noun is "of", else a name in
capitals just before the figure noun, else a "like" that is not one's own. Its tests use other
sentences, but set 7 is no longer blind on how a request names its subject, and the report of its
run will say so.

The same review found `resolve` let a little known person beat a landmark. Live Wikidata showed
worse: "Yoda" was a worm genus, "Batman" a Turkish city, "Mario" a given name and "Shrek" the film.
Now names, genes, works, diseases and agencies never count, read from the class labels; the
candidate known in the most Wikipedias wins, a person, animal or character weighted 1.5 over a
thing; and a fictional character is its own kind, styled with its costume and colors. On 37 live
names every one resolved to the subject a figure means, except "Garfield", which is the president
(defensible) and "Thinker" without "The".

## 2026-11-19 held-out sets for the three figure modes sealed

The goal now is figures of people made three ways: from the model's own research (`stone find`), from 1 to 3 photos the person gives, and from a description (stone draws a FLUX.2 klein portrait, then the same pipeline). Each mode has a held-out set, written by a separate writer this morning before any tuning on it: evals/figure-research (6 people), evals/figure-photo (3 people, 7 free-licensed Wikimedia Commons photos credited in CREDITS.md), evals/figure-desc (4 descriptions). Nothing has run on them. The paint sweep since then tuned on Jensen, Elon and DHH only.

The file names say a trait or two of each person (braids, glasses, a beard), so the sets are not blind on that. The garment and hair words on the desc-mode branch were last changed at 11:09, before the sets were written (11:27 on). Each case runs 2 seeds. The bar, written now, before the run: every check passes and the likeness bar holds (for a description, every trait it names is visible in the views), in at least 80% of runs per mode, and a blind Opus craft judge gives a mean of at least 8 per mode, with a seeded bad control. Likeness per mode, set now: for research, the blind Opus likeness judge (evals/judge_likeness.py) scores at least 7 against a Wikipedia lead image the tool did not pick; for photos, the last photo of each case is held back from the tool as the judge's reference, seed 1 gets only photo 1 (the likely real input, one photo) and seed 2 gets every photo but the reference, and the same judge scores at least 7; for a description, every trait it names is visible in the views, judged blind by Opus. No one reads these files before the run, and the run's report lists every change to `stone find`, the photo path or the prompts made after this commit.

```
d647a6e541edfa9aca2bd027693618f360f3103d05b884b1d820763a485bbc4f  r1_michelle_obama.json
69abb71e9ee15bcc27c55c1b5eefffac8c8082a273e0acd6373d1e05c080db32  r2_priyanka_chopra.json
0ab93b59f545c0d3c00b55932a911522382916cf01b9e664e57325fbf7616bda  r3_dolly_parton.json
db99150a5652b6d85f7fc5edfc68c78a058a968ee3f3801716a163daecd7e1ab  r4_george_rr_martin.json
ead2b1a841ac30cc6afec331a798606c1e2ee123532a16a43b95bd5ddf811e53  r5_iris_apfel.json
b6741a6c23a928a9af3911260f29daecde8ae5a1b519347d71ec0a6137cf8ff8  r6_michael_jordan.json
9fc4065f431c745f15060988e7d7ff8eee420f01c7f93ba5e77f5cdc4d2596d0  CREDITS.md
c777542c7fc2d29af83aad0400ad816efebaeba3716c10024b3f975fe104add9  p1_trench_coat_woman_1.jpg
e307ce51c9a26bf32a99616f55bbad969b1c24db5f525b5db6a36257b1ed5ece  p1_trench_coat_woman_2.jpg
5b2c732b82afe9b1143f1fd90f817adc14e26bdc465fceac94336d00d16f91c4  p1_trench_coat_woman.json
b517c155fb5303047806a43910acc6421427de7daf8ae72f96e84e14e4ea1aed  p2_ghana_groom_1.jpg
2620e2547a369c4b28668979d4128d38da033ceafe843334665426392f10cc36  p2_ghana_groom_2.jpg
071206154eaa5e492059700aa571817a3d06a28b5b5d6ca779fd7d97e24e456a  p2_ghana_groom_3.jpg
593b00b106ff8bc3773fdebaf98a64fa81fe1682523df6fb8a78ec0abdad48f3  p2_ghana_groom.json
3344dfa3e31771547aa20b56f6aad79c29e68674ab608abb615d555b7a5187b6  p3_blonde_mustard_pants_1.jpg
949804327ac7471c87aa265c9d04ba82b38dbf8be6dc6fd4f47b9aa883e5ecdb  p3_blonde_mustard_pants_2.jpg
01bb91d98cef6e27069155d37497dcb6cd939489b54ed8ce3c4531435d3ab3a2  p3_blonde_mustard_pants.json
f47d730af3828fd9102745640e4793318db33e82c328f8ba1c193f8f910bf8f4  d1_old_man_beard_cap.json
b61d8eef7cfc7c891927c122d6d01a06d5a7a38356bb1d65ddf446fc91901ae0  d2_girl_braids_dress.json
d15e0478f82c292fa8c56f2c6ed737a7a99d1404698866a114d87d8d91c05b0e  d3_woman_pixie_glasses.json
381c1eb606406955069ffe0aaf52df1b4fdb7eea09aa4a794069ebdde4173c13  d4_man_curly_beard_boots.json
```

## 2026-11-20 stone find keeps only photos of the one person meant

The owner said: "For figures it needs to ensure the figure referenced is the correct one they want."
Live that day, `stone find` for Michael Jordan took C215's street art stencil of him as photo 3, and
on main Sam Altman's photo 3 was "Ilya Sutskever and Sam Altman in TAU.jpg", a stage panel. This is
a change to `stone find` after the 2026-11-19 seal, so the sealed runs' report must list it.

- An artwork of a person or an animal is left out: its title, Commons categories or object name
  names a painting, drawing, stencil, mural, graffiti, street art, statue, sculpture, wax figure and
  the like, or its structured data (P31) is an artwork class. C215's file is in "Graffiti of
  Michael Jordan".
- A person's photo must show one face that has at least twice the area of the next face and is
  80 px or more on its shorter side (OpenCV YuNet). The TAU panel has two faces of 31 and 29 px.
- That face must be the person's: SFace cosine 0.363 or more (opencv_zoo's own bar) against the face
  in Wikidata's main photo. With no face there (Chris Evans the presenter's main photo shows two
  people) the largest group of faces that agree wins. Michael Jordan's main photo is a close-up
  bigger than YuNet looks for; a grey border around it finds the face.
- Checked on Commons photos of seven people (Michael Jordan, Michael B. Jordan, both Chris Evanses,
  Sam Altman, Elon Musk, Bill Gates; 18 photos each): 235 pairs of one person's main photo against
  another's photos scored 0.26 at most (Michael B. Jordan against Michael Jordan 0.12). The C215
  stencil scored 0.32 against Michael Jordan. Most of a person's own photos scored 0.39 to 0.95; six
  true photos fell under the bar and are lost: a 1984 Michael Jordan profile 22 years younger than
  the main photo (0.25), Chris Evans in sunglasses (0.25) and in a cap and full beard (0.18), Elon
  Musk's face on a stage screen behind him and Javier Milei (0.34, 0.35), and one of Bill Gates
  (0.34). So the line says "a face that may not be his", not "is not".
- Without the models (offline, STONE_FACES=0) find works as before and says the faces went unchecked.
- regressions/r5_jordan_stencil and r6_altman_group_shot check found.json (expect.found): the
  person's Wikidata id, never those two files, one clear face in every photo. Both fail on the
  photos the faulty finds took.

## 2026-11-21 the teacher's half of the loop: where a run first left stone's path

Taken from sybil-solutions/skill-distill (0xSero): the teacher runs the student, finds the first
divergence, fixes the skill there, and reverts a version that scores worse.

- evals/distill.py reads every model run's log.json and finds the first step that explains the
  result: off the NEXT line (fix the card), stopped early (the card's stop rule), a wrong value
  (the card), out of steps on the path (shorten stone's path), every NEXT followed to a failing
  part (fix stone), or a setup FIX (the trial does not count). It also prints the pass rate per
  card version on the specs both versions ran, and flags a version that did worse.
- On the 30 LFM3 runs kept from 2026-11-18 and 11-19, no failure was the card's: 3 were setup,
  4 were stone's own NEXT path (a jagged color edge's NEXT drops a named color, which the shoes
  work addresses), 2 ran out of steps on the path (f5_elon_colors, f6_dhh_colors), and the one
  "off" run kept shoes=black when stone's NEXT dropped it.
- For the steps: stone set on a figure with no photos now says NEXT: stone find "<who>",
  not stone build, which could only end in that FIX. One step less on the figure path. The S card's
  figure lines and example say so, so the S card's SHA changes here (a new version in the ledger).

## 2026-11-21 the random five: flawless printable figures of five people picked at random

Five popular people drawn at random (evals/figure-random): Lamine Yamal, Christopher Abbott, Inde
Navarrette, Shane Gillis, Sienna Miller. Each run on the Mac (FLUX.2 klein style, Hunyuan3D-2mini
lift at octree 384), then judged here: every stone print check, the likeness judge (pass 6) and
the craft judge on the shape (judge_views). The craft judge moves about one point run to run.

- Round 5, before this work: likeness 8 / 9 / 7 / 3 / 9, craft 5 / 8 / 7 / 8 / 8.
- Lamine's hair lifted as loose worms half a mm thick, floating up to 3.1 mm off the head (craft 5).
  printable.strands cuts every strand of a head that has many (STRAND_MANY 16) with one floating
  STRAND_FAR 1.5 mm or more, fills the cut from the opened head, and smooths the join and the hair
  by moving the mesh's own points onto a blurred surface. Rebuilt: craft 7. Christopher Abbott's
  sculpted curls (24 strands, none past 1.3 mm) are left alone: cutting them took him from 8 to 6.
  Inde's long hair (8 strands, three locks 1.7 to 3.2 mm off) is left alone too: cut, her locks
  ended in flat slabs beside the cheek (6 cut, 7 kept).
- Inde's head lift came with a neck far thinner than the body's, and the neck blend took it: a
  3 mm2 neck. The body's own neck now stays in the blend, shrunk at most GRAFT_KEEP (1/160 of the
  height), so hers keeps 75% of the body's; a joined neck under GRAFT_NECK (half) is refused and the
  figure keeps its own head.
- Points below the head grid read the nearest cut's distance at its edge and pulled Inde's feet;
  off the grid they are now far from every cut.
- Folds left by the smoothing (7250 faces on Inde's hair) made the slicer union split off two
  0.01 mm slivers: three bodies. clean.for_slicer drops shells under 0.001 mm3. Easing the folds
  back instead brought the worms back (craft 5 on both), so it was not kept.
- Shane Gillis's likeness stays at 3 to 4. Both his free photos are stage shots under colored
  light that show his ginger hair as brown, and with a 2025 mustache; the judge's reference is
  another year's photo with stubble and a hoodie. Correcting the face crop's color cast by its
  cheeks (hue 42 to 56) scored 3 and 3, and naming his age or dropping "full round face" scored
  3 to 4 on two seeds each: none kept. The photo's hair measured no ginger to name.
- Round 6, all of it on this code, fresh from find to slicer: likeness 8 / 9 / 6 / 4 / 8,
  craft 7 / 8 / 7 / 7 / 6. Every figure passes every print check as one body. Sienna's 6 names
  flecks at her outer eye corners and a few thin fins at her hair ends; her round 5 render rebuilt
  on this code scored 8 with the same flecks named. Inde's 6 is
  the judge's reference pick (7 on round 5 with the same render path); Shane's 4 is his photos.
  Craft stops at 7 to 8 where the lift model leaves soft eyes and hands.

## 2026-11-22 engineering evals: the measuring stick before the capability

Step 1 of the engineering program: a 1.7B model, given "a case for <product>", should climb with
stone until the part is engineered right. Before any capability, a suite measures it:
evals/engineering (e01 to e10, tuning) and evals/engineering_grade.py (fit, covered and open faces,
port access, retention, strength, walls, printable, sources; README "Engineering specs"). Every
product number comes from the maker's own page or drawing, URLs in each spec. e01's heights and port
sizes come from Raspberry Pi's own Pi 5 STEP model (PIP RP-010083), because no Pi drawing gives a
height; it matches every center and height the drawing does give. Dropped for unpublished numbers:
Anker 313 (two sizes on one page), Pi Zero 2 W (no height or connector sizes). Ports with no
published position leave their face open, never guessed. The ratchet now guards evals/engineering.

Baseline, NEXT driver, seed 1, at 7e38f42 (a frozen worktree of it): 0 of 10 pass. engineering/next floor
0.00 of 10. The first baseline named f20a82f, which has no grader: it ran from an uncommitted tree, so
its ten rows in scores.jsonl are replaced by the rerun's.

| spec | product | where it stops | top failure |
| --- | --- | --- | --- |
| e01_rpi5_case | Raspberry Pi 5 | no recipe (nearest phone_case), asks | no finished part |
| e02_flipper_zero_case | Flipper Zero | no recipe (nearest phone_case), asks | no finished part |
| e03_power_bank_case | Anker A1388 10000 mAh | no recipe (nearest phone_case), asks | no finished part |
| e04_airtag_case | Apple AirTag | no recipe (nearest phone_case), asks | no finished part |
| e05_appletv_wall_holder | Apple TV 4K (3rd gen) | no recipe (nearest hook), asks | no finished part |
| e06_iphone_desk_holder | iPhone 17 Pro | builds phone_stand | no engineering.json |
| e07_mac_mini_mount | Mac mini (M4, 2024), 20 N | no recipe (nearest grommet), asks | no finished part |
| e08_rpi4_vesa_adapter | Raspberry Pi 4 on VESA 75 | builds panel 75 x 75, 4.5 mm holes | no engineering.json |
| e09_pot_knob | Bourns PTV09A-4020S-B103 | no recipe (nearest box), asks | no finished part |
| e10_model_number_case | ABX00080 (UNO R4 Minima) | no recipe (nearest phone_case), asks | no finished part |

Every run also fails "the part does not say where the product sits (no engineering.json)": no
recipe writes the file yet.

Review round 1 (7e38f42) fixed specs that a correct part could not pass or a wrong one passed: e04's
keepout is round and the tag is Apple's Detail A dome profile, not a 7.98 mm cylinder; e08 checks the
board's four holes and the VESA 75 holes in the mesh; e07 and e10 need the part under the product in
3 of 4 quarters instead of a screw into the Mac (e07) or a slip gap under the bare PCB (e10, whose
leads are unpublished); e09's shaft tip has its own gap band. The snap arm, screw holes and critical
section are now measured in the mesh. The rerun's stops and top failures match the table above.

Review round 2 closed the ways a part could pass the grade and fail in use: the strength arm is
measured from where the product bears (and, with an attach, to the nearest screw), h_dir must lie
along the load, and the layers come from the beam's axis; the snap arm's catch, its root and its
sides, from 5% of its length every 0.5 mm to 0.25 mm short of its tip, are found in the mesh; e01's power button needs a Ø10 fingertip
(MIL-STD-1472F Figure 12); e05 and e07 must screw to the wall or desk through ISO 273 M4 clearance
holes; screw retention takes through holes (bolt and nut, or a bought standoff) at ISO 273 sizes, so
a correct e08 plate passes; e08 keeps 2.5 mm under the board outside its holes' Ø6 pads for the
through-hole leads; and each source must be one the spec cites for that number, a profile included.
e10 has the same lead question as e08 under a flat floor and is left for its own change. The NEXT
baseline rerun is still 0 of 10 with the same stops and top failures.

Review round 2 of PR 64 closed two more ways through and two more failures. Strength shared the load
by bearing area and graded only the declared section, so a 1.2 x 5 mm strap under one side of e07's
Mac passed with a section declared in the thick wall beside it; the load is now shared by statics (a
rigid body on equal springs), and the load path is swept: every cut from the declared section out to
the bearing points and on to the screws is graded on its own cut face. A correct e08 plate on bought
M2.5 standoffs failed check_holes, which looked for the seat only 1.45 mm under the board; a through
hole is now found along its axis wherever the part is. A through bolt's ring is probed through its
wall, not 2 d deep, so an M3 bolt in a 2.5 mm wall passes; a screw hole's mouth must lie on the
part's surface. e01 gains the Pi 5's four mounting holes with Ø6 pads and a 1.05 mm min_gap under its
body (2.5 mm under the PCB), so a flat floor flush with the PCB fails; product holes are graded as
screw seats only when the part screws to them, and their pads count for support. e01's w and
usb_c_power sources cite the STEP URL they come from. e10 is still left for its own change.

Review round 1 of PR 65: the sweep cut only square to the declared beam axis, so e07's cradle with
its -x wall joined to the top through a 5 x 1.2 mm neck passed with a section at the lip root; every
plane x = const through the neck took the whole wall with it. On a part that hangs from screws the
part is now also cut square to the load, from the farthest share to the farthest screw, and each
cut face is graded whole: the shares' pull over its area plus their moment over its own second
moment of area. Its stress runs along the load, so a cut across a -z load is graded across the
layers (x0.5) whatever layers the declared section lies in (review round 2): the neck reads 70 MPa
against 11.75 allowed, a 15 x 1.5 neck 15 (it passed against 23.5 before), a 20 x 3 neck 3.2, the
whole wall 0.75.

## 2026-11-22 climb 1: a fitted case from a product catalog

The first step up the engineering suite. Stone now has a product catalog,
src/smoothstone/products/<slug>.json, one file per product: the product block of its engineering
spec word for word (name, body, body_sources, features, sources) plus the names and model numbers
people type (aliases, ABX00080 included), which faces must stay open, and for a board where its PCB
sits. These ten products are the tuning set. Products for a held-out set come later and must not be
tuned on.

A new recipe, fitted_case, builds a tray case from a catalog product: a window for every feature
the maker locates on a walled side (its plug or opening plus 0.5 mm), open faces where the maker
locates nothing, standoffs on a board's hole pads (or two ledges under its short ends) 2.75 mm over
the floor for the leads, a clearance per side inside the grader's band (PLA slip 0.3, snug 0.15,
TPU snug 0.1 interference), and retention none, friction, or two snap arms cut free from opposite
walls (strain at 75% of the limit). The build writes build/engineering.json from what the OpenSCAD
echoes it built, with the URL the catalog cites for every size. The request picks the product
(stone show says "Product: <name> (catalog, sourced: ...)"); a product not in the catalog gets a
question for its width, depth and height and which faces have ports, never a guess. It ranks first
only when the request names a catalog product, so iPhone cases stay phone_case. It learns from two
open designs: YAPP_Box (MIT, https://github.com/mrWheel/YAPP_Box) for per-face center-and-size
cutouts, no code copied; BOSL2 (BSD-2, vendored) is the library it may
build on, unused so far.

NEXT driver, seed 1, before (origin/main 887ef71, and the 7e38f42 table above for e04 to e09) and after:

| spec | before | after | after: top failure |
| --- | --- | --- | --- |
| e01_rpi5_case | no recipe, asks | pass | |
| e02_flipper_zero_case | no recipe, asks | pass | |
| e03_power_bank_case | no recipe, asks | pass | |
| e04_airtag_case | no recipe, asks | asks: the catalog has the AirTag, a tray cannot hold its dome | no finished part |
| e05_appletv_wall_holder | no recipe, asks | builds a fitted_case tray | attach: no M4 holes to screw it to the wall |
| e06_iphone_desk_holder | phone_stand | phone_stand | no engineering.json |
| e07_mac_mini_mount | no recipe, asks | no recipe, asks | no finished part |
| e08_rpi4_vesa_adapter | panel | panel | no engineering.json |
| e09_pot_knob | no recipe, asks | no recipe, asks | no finished part |
| e10_model_number_case | no recipe, asks | pass | |

4 of 10. The floor in evals/floor.json is left for the lead to raise.

PR 67 review, round 1, fixed on the branch:

- A case whose walls hide ports: raspberry_pi_4 (its spec grades a VESA plate and locates no ports)
  and mac_mini_m4_2024 (Apple does not locate its bottom power button, and a tray's floor covers the
  bottom) are no longer case products; stone names them and says why. Each case product now records
  port_faces, and a test holds every port face open or located, never an unlocated bottom.
- e01's snap catches hooked air over the body box's edge. The catch now bears on the rear USB stack's
  shell, as GPT-6.1 Sol's gold e01 part does: one arm in the +y wall at x 77.09, catch underside 0.465
  above the shell top (18.815), reaching 0.55 past its edge (0.25 after the 0.3 side shift), y 2.6,
  L 23, strain 1.47% against PLA's 2%. The shell's x span (70.78 to 88.265) is new: the STEP body
  whose y span and top match usb_stack_b's cited bbox, measured from the same STEP file. A product with
  no located catch surface refuses retention=snap, and a test checks every catch over its surface.
- Friction was claimed for a 0.3 mm slip gap. The grader checks only that a friction gap lies in the
  fit's band, so it cannot catch that; the part now claims friction only at a gap at or below zero
  (auto picks it there, and an explicit friction with a gap is refused).

e01, e02, e03 and e10 still pass on --driver next.

PR 67 review, round 2:

- second-S1 fixed: for a product not in the catalog, fitted_case asks only which product it is (maker
  and model). An answer that names none ends the ask: it says fitted_case builds only for products
  with sourced sizes, names some, and points to box for a custom size, instead of asking again.
- first-F1 fixed: with the catch sized for the side clearance, the Pi 5 could slide 1.93 mm toward
  -y (its PCB edge stops on the -y wall, its HDMI shells slide into their windows) and the catch then
  missed the USB shell. Each standoff now carries a 2.4 mm locating pin in the 2.7 mm hole (YAPP_Box's
  size; pin = hole - 0.3), 1.0 mm over the PCB's underside with a 0.4 mm chamfer (no PCB thickness is
  sourced, so 1.0 mm is a stated minimum). The board slides at most 0.15 mm, and the catch reach is
  sized from that: y 2.3 for PLA slip, catch 0.4 past the shell's edge, 0.25 after the worst slide.
  Snap needs pins. This needed the grader change in the commit before it (a pin inside a product's
  mounting hole is not inside the product); e01 fails without it.

2026-11-22, PR 67 round 2: the grader's fit check read a locating pin inside a mounting hole as the
part inside the product (1.85 mm on e01), so it refused the pins that keep a Pi from sliding off its
snap catch. A hole is empty through the board: check_fit now leaves out samples inside a hole
feature's own diameter (not its pad, no margin). A standoff pushed into the board around the hole
still fails (test_pi5_standoffs_into_the_board_fail, test_a_pin_wider_than_the_hole_still_pushes_into_the_board).

## 2026-11-22 climb 2: five product recipes from the Sol gold set

The second step up the engineering suite, on the climb 1 catalog. Five new tier S recipes build a
part for any catalog product of the right kind, each adapted from a reference design by GPT-6.1
Sol, smoothstone gold set (copied as made into evals/gold/, each passing the grader:
`uv run python evals/gold/grade.py`):

- round_case (from e04): split shells for a round product, a flexure hinge at the back and a latch
  at the front, open over every feature the maker locates on top. PETG.
- product_holder (from e05 and e06): an open top cradle on a desk or, "on the wall", screwed up
  with two countersunk screws through a side the maker does not need clear, the floor sized for the
  load; an upright product gets low guides and a backrest, a port underneath raises it on a 45
  degree shelf over a cable slot. PLA.
- product_mount (from e07): an under desk channel, roof screws in counterbores, two rails under
  the product, front snap tabs, rear stops, printed on its front end. PETG.
- board_plate (from e08): a VESA 75 or 100 adapter plate for a board, countersunk clearance holes
  for bought standoffs at the board's own holes (2.7 mm holes take M2.5), a vent under the board.
  PETG, for the warmth behind a monitor.
- knob (from e09): a press on knob, four fingers freed by a relief ring grip the shaft 0.06 mm
  under its size; a D shaft gets a flat. PLA.

The catalog says which products each recipe may take (catalog.KINDS) and writes
recipes/lib/catalog.scad, the rows the recipes read. A recipe reports what it built through one
echo, stone_eng, read into build/engineering.json. A product named with punctuation the phrases do
not read ("Mac mini (M4, 2024)") is still found, and its model numbers are used up as the name, not
offered as sizes. A variant word (Pro Max, mini, Plus) keeps catalog.find off the plain model.
fitted_case no longer makes "holder", so holders go to product_holder.

NEXT driver, seed 1, before (climb 1, c17e4a6) and after:

| spec | before | after |
| --- | --- | --- |
| e01_rpi5_case | pass | pass (fitted_case) |
| e02_flipper_zero_case | pass | pass (fitted_case) |
| e03_power_bank_case | pass | pass (fitted_case) |
| e04_airtag_case | asks, no finished part | pass (round_case) |
| e05_appletv_wall_holder | fitted_case tray: no M4 holes to screw it to the wall | pass (product_holder, mount=wall) |
| e06_iphone_desk_holder | phone_stand: no engineering.json | pass (product_holder) |
| e07_mac_mini_mount | asks, no finished part | pass (product_mount) |
| e08_rpi4_vesa_adapter | panel: no engineering.json | pass (board_plate, vesa=75) |
| e09_pot_knob | asks, no finished part | pass (knob) |
| e10_model_number_case | pass | pass (fitted_case) |

10 of 10, all on the tuning set. The floor in evals/floor.json is left for the lead to raise.

Every catalog product each recipe may take builds with stone's checks passing, but one:
product_mount for the Anker A1388 (151 mm long, 16 mm low) tips standing on its front end. Open:
a snap off brim, or printing it on its roof with supports, is the owner's call. Flipper Zero on a
wall refuses with a reason: the catalog keeps every one of its sides clear.

Where the grader passes something that would not hold in real life:
- e04: the grader takes any snap arm; the round case's latch holds the two halves shut, not the
  AirTag itself. That is right here, but the grader would pass an arm that held nothing.
- e09: coverage sampled at 0.7 mm reads 100% though the finger slots are open; sampled finer it is
  near 88 to 90%, still over the 80% floor.
- e08: the grader does not check the standoffs or the screws' grip in them; the plate assumes
  bought metal standoffs of the stated length.
- e06: a desk holder declares no load, so nothing checks the backrest against a hand pressing the
  phone's screen; a held out desk spec with a load would fail.

## 2026-11-22 climb 3: stone's text for small and mid size models

Stone's own NEXT path passed all 10 engineering specs after climb 2; real models did worse. The logs
showed four faults in stone's text, not in the models' grasp of the job:

- LFM3-1.7B, right after `stone show fitted_case` (e02, e10; t2 with cable_comb): it spent its whole
  2048 token budget re-reading the parameter list (every choice and help line) and stopped with no
  tool call. Its reasoning tripped on `product = raspberry_pi_5` printed as the default beside NEXT
  product=flipper_zero, and on the example for another product.
- LFM3-1.7B (e03, e06): `stone recipes` said NEXT: stone show fitted_case for a power bank sleeve and
  product_holder for an iPhone desk stand; the model read the titles ("Fitted case for a product",
  "Product holder"), judged the NEXT line a mistake and showed product_holder or phone_stand.
- LFM2.5-24B-A2B (e03, e04, e06, e10): it skips `stone recipes` and guesses names (power_bank_case,
  airtag_case, desk_stand). The unknown name went to the nearest name, phone_case, and phone_case took
  a power bank, an AirTag and an Arduino ("ABX00080"), set phone=iphone_17_pro or asked "What phone
  model...".
- LFM2.5-24B-A2B (e04): show said "Not placed yet: 2021 one; one" for "an Apple AirTag (the 2021
  one)", and the model spent four steps on size=2021.

What changed (src/smoothstone/cli.py, match.py; tests in tests/test_fitted_case.py, each failing
without its change):

- Tier S `stone show`, when the request fills what the part needs (nothing left unplaced, the product
  named, no photo to place): the filled values, then "The NEXT line below already holds every value
  the request gives; run it as written.", then the other parameters one short line each with no help
  text and no example. `stone show <recipe> --all`, tier M and L, and any request that leaves a size
  unplaced keep the full list.
- A product parameter (fitted_case product, phone_case phone, every catalog recipe) shows no default:
  "(no default: the exact one the request names, else ask)". An example that sets another product is
  left out.
- When the request names a catalog product, `stone recipes` leads with why its pick fits: "For this
  request: fitted_case makes the sleeve for the Anker Power Bank ... from its published sizes."
- `stone show` and `stone set` of a recipe that cannot take the named catalog product, or makes
  nothing the request names, while the request's recipe takes it and fits better, print FIX and send
  the model to that recipe (phone_case for a Flipper Zero, phone_stand for an iPhone 17 Pro the catalog
  holds, product_holder for a sleeve). An iPhone case still goes to phone_case.
- A made up recipe name that is not a typo of a real one (power_bank_case is not phone_case) goes to
  the request's recipe, not the nearest name.
- A year or model number of 4 or more digits from the product's own name is used up, with a "one"
  right after it, so "(the 2021 one)" is not offered as a size.

Before: climb 2 (8a31f55, PR 70). After: 5c065bc. openai driver on Ollama, card S, seeds 1 to 3.
Each run's log is kept outside the repo; two before tuning runs hit the shared /tmp disk quota inside
stone and were rerun, and Ollama answered HTTP 400 once (24B, e02 s2, before), a crash with no log
that its rerun passed.

| model | suite | before | after |
| --- | --- | --- | --- |
| LFM3-1.7B | engineering | 26 of 30 | 30 of 30 |
| LFM2.5-24B-A2B | engineering | 19 of 30 | 30 of 30 |
| LFM3-1.7B | tuning | 20 of 21 | 21 of 21 |

| spec | 1.7B before | 1.7B after | 24B before | 24B after |
| --- | --- | --- | --- | --- |
| e01_rpi5_case | 3 | 3 | 3 | 3 |
| e02_flipper_zero_case | 2 | 3 | 3 | 3 |
| e03_power_bank_case | 2 | 3 | 0 | 3 |
| e04_airtag_case | 3 | 3 | 1 | 3 |
| e05_appletv_wall_holder | 3 | 3 | 3 | 3 |
| e06_iphone_desk_holder | 2 | 3 | 0 | 3 |
| e07_mac_mini_mount | 3 | 3 | 2 | 3 |
| e08_rpi4_vesa_adapter | 3 | 3 | 2 | 3 |
| e09_pot_knob | 3 | 3 | 3 | 3 |
| e10_model_number_case | 2 | 3 | 2 | 3 |

Steps cut off at the 2048 token limit: 1.7B engineering 5 before, 0 after; 24B 4 before, 1 after;
1.7B tuning 1 before, 0 after. Model minutes for the 30 engineering runs: 1.7B 37 to 28, 24B 47 to 34.

Every 1.7B run after was made on 5c065bc. The 24B runs after for every spec but e04 were made on the
first commit of this climb (979f7ab); the second commit changes stone's text only for e04's round_case
(checked by diffing match.suggest_full on every engineering and tuning request against every recipe),
so the 24B's e04 was rerun on 5c065bc (2 of 3 on 979f7ab, 3 of 3 on 5c065bc).

`--driver next` on 5c065bc: 10 of 10 engineering specs pass.

Open: e07 s2 on the 24B before set material=PLA on product_mount (PETG default); it passed after, but
nothing stops a model from overriding a material the recipe picked for a reason. When the 1.7B's
reasoning is cut at the token limit it then writes its tool call as text in its reasoning
(`<function=stone>...`), which the openai driver does not read; climb 3 removed the cutoffs that led
there, but the driver gap remains (a harness change, left out of this climb so before and after
measure stone's text alone).

Held-out, measured once on this climb's code and not tuned on (evals/engineering_heldout, x01 Steam
Deck stand, x02 MX Master tray): 0 of 14. `--driver next` fails both, so the gap is stone's, not
the models': neither product is in the catalog, and stone has no path for a product the person
describes by its measured size with a source. Most runs ended with no engineering.json; LFM3-1.7B
seed 1 on x01 and seed 3 on x02 died on Ollama HTTP 400. The scores stay out of evals/scores.jsonl.
Next track: a holder, mount or case for any product given its size and source, climbed on tuning
specs only, with these two sealed as the check.

## 2026-11-23 climb 4: a part for a product stone does not know

After climb 3, a request naming a product the catalog lacks ("a mount for my Mac Studio") ended with
no engineering.json: stone asked "Which product is it, exactly?", then had nowhere to go. Now the
size comes from the person, with its source, and every product recipe takes it.

What changed:

- `stone product add "<name>" --size W D H [--corner-r R] [--round] --source "<URL or measured by the
  person>" [--open FACES]` writes job/products/<slug>.json in the catalog's schema ("set": "job", the
  name and any model number as aliases, each size naming its source, fitted_case true for a box).
  --round is a disc: W is the diameter. With no --source it refuses: stone never estimates a size.
- catalog.py sees the current job's products (catalog.use_job, set by every stone command), so
  slugs_for, kinds_for, find and get include them, and fitted_case, round_case, product_holder and
  product_mount offer them. A build for a job product passes the CATALOG and PRODUCTS tables with -D,
  so recipes/lib/catalog.scad and recipes/fitted_case/products.scad stay as generated.
- When the request names a part for a product ("a mount for my X", "a cup that holds my X"), the
  recipe stone ranks first builds from the catalog and the catalog has no X, `stone show` and
  `stone set` stop with NEXT: ask the person: X's width, depth and height in mm, and where the
  numbers come from (the maker's spec page, or their own ruler). stone never sets a default product.
  `stone note "<answer>"` reads the sizes (the metric one when the maker prints two units, so
  "7.7 inches (19.7 cm)" is 197) and the URL, keeps the answer out of the request, and NEXT is the
  exact `stone product add` line; a missing size or source is asked for again.
- round_case leaves the top open, with no rim, for a product whose open faces hold +z (a cup).
- evals/run.py: after the person speaks, the next driver runs `stone note '<their words>'`, as the
  cards tell a model to, instead of stone status. Grading is unchanged.
- Cards S, M, L and SKILL.md: an unknown product means ask for its size and source, then
  stone product add; never guess a size.

New tuning specs, each with a follow-up where the person gives the maker's numbers and the URL:
e11_mac_studio_mount (product_mount, 197 x 197 x 95, https://support.apple.com/en-us/122211) and
e12_homepod_mini_cup (round_case, 97.9 across, 84.3 high, https://support.apple.com/en-us/111914).
evals/engineering now holds 12 specs; the catalog still holds the first 10.

`--driver next`, seed 1: e11 pass (status, recipes, show, ask; note, product add, set, build, 1100 s
with the grader), e12 pass (296 s), e01 to e10 10 of 10. The new specs were not run on the code
before this climb. The scores stay out of evals/scores.jsonl. Tests: tests/test_job_products.py, each
failing without the change; the Garmin watch test in tests/test_fitted_case.py now expects the size
question and, for an answer with no source, a question for the source.

Open:
- e11 holds load_n 20 (stone's default; the request names no load). Apple lists 2.74 kg (M4 Max) and
  3.64 kg (M3 Ultra), 26.9 N and 35.7 N. The built mount reads 1.44 MPa at its weakest section under
  20 N against 23.5 MPa allowed, so its geometry carries the real weight, but nothing makes stone
  design for it: stone takes no weight yet.
- e12's cup is round_case's clamshell (two half shells, a flexure loop, a 6.8 mm latch) on the
  enclosing cylinder. Apple publishes no profile for the rounded HomePod mini and does not locate its
  power cable, which a closed floor and walls would trap. The grader sees neither.
- The held-out x01 and x02 were not run or read.

### Round 2: what the real model runs showed

Before (round 1 code, card S, Ollama, seeds 1 to 3 on e11 and e12): LFM3-1.7B 1 pass, 3 fail, 2 crashed
(e11 s1 and s3 left no log.json; the error itself was not kept); LFM2.5-24B-A2B 0 pass, 6 fail, 0 crashed.
The logs showed models noting stone's question instead of asking it, a round product asked for a depth
its maker does not give, sizes set on the recipe with nowhere to go, and a call written as text.

Stone's text and rules:

- At the ask, NEXT comes first and the note hint after it: "After the person answers (not before):
  stone note ...". The output contract allows that one line below an ask's NEXT, and nothing else.
- `stone note` refuses a note that is the question: the question itself, a restatement with no number
  or URL of its own, or a note with no number or URL that asks for a size or speaks to the person
  ("please provide", "where did you get them"). The person answers as "I"; stone's question says
  "you". Before this, "your own ruler" in a noted question became the source "measured by the person".
- While the job waits on an unknown product's size, `stone set` with sizes gives FIX and NEXT = the
  exact `stone product add` line, sourced from what the person's answer already gave through
  stone note, else a placeholder to fill.
- A round product (round_case on top, or the request says round, cup, puck or disc) is asked its
  diameter and height. stone note reads "97.9 x ? x 84.3", and a width and height with no depth, as
  diameter and height; `stone product add --round --size D H` takes the two numbers.

Harness change (evals/drivers.py, evals/run.py), apart from stone's text: when a reply has no
tool_calls, the openai driver runs a `<function=stone><parameter=command>...` call written as text,
logs the step with "text_call": true, and the score line counts them. No after run used it.

Checks on d5d2f42: `--driver next` 12 of 12 (e01 to e12); the suite and timing test pass; ratchet holds.

After (same models, card S, seeds 1 to 3; out under the climb4 scratchpad after/):

| Model | e11 s1 | e11 s2 | e11 s3 | e12 s1 | e12 s2 | e12 s3 | Total |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LFM3-1.7B | fail | fail | pass | pass | fail | crash (HTTP 500) | 2 pass, 3 fail, 1 crash |
| LFM2.5-24B-A2B | fail | fail | fail | fail | fail | fail | 0 pass, 6 fail |

LFM3 ran on 8a38fce. 24B e11 s1 ran on 8a38fce; the rest ran on 31005b6. On 8a38fce, 24B e11 s2 failed
sources (its noted question became the source); on 31005b6 the note was refused, and it failed fit.
24B e12 s2's source leak is what d5d2f42 fixes; it was not rerun.

Why they fail now: in 11 of 12 runs the model never ran stone note after the person answered. It ran
`stone set <recipe> width=... depth=... height=...` with its own numbers, and the redirect turned them
into the product add line. Every run that copied the maker's metric figures (197, 97.9) passed;
every run that rounded or converted the inches (196, 195.58, 98) failed fit, 0.7 mm into the product.
Other fails: LFM3 e12 s2 wrote `stone product add "X" size=97.9,97.9,84.3 round open z source=...`,
which stone read as the name; 24B e12 s1 set `size=` on round_case, which no size key reads.

Open:
- A rule for the sizes a model sets itself: while the job waits on a product's size and stone note has
  not read an answer, the set redirect could ask for `stone note "<the person's words>"` first, so
  stone reads the maker's metric figure. That changes what the round 2 brief asked set to print,
  so it is not made here.
- `stone product add` could read the name=value words stone set takes (size=, source=, round, open).

### Round 3: sizes come from the person's own words

- While the job waits on an unknown product's size and no stone note has read an answer, `stone set`
  with sizes gives FIX and NEXT = `stone note "<the person's words, copied exactly>"`, never the
  product add line, so converting units and rounding stay stone's job (the metric figure wins when a
  page prints inches too). Once a note gave every size and a source, a set with numbers more than
  0.05 mm off says so and keeps the noted ones, and show and set give the noted product add line
  instead of asking again.
- round_case reads size= (one number is the diameter) and diameter= on stone set; a size= the shell
  split ("size=196 196 94") is read whole.
- `stone product add` reads name=value words in any order (size=WxDxH or size=W D H, w= d= h=,
  diameter=, source=, round, open=..., name=), and gives back the exact corrected line for a word it
  cannot read.
- Cards S, M and SKILL.md: note the person's words exactly; never convert or round a number.

A first round 3 run, on aaf74a3, showed a full note followed by `stone set ... size=196 196 94` asking
the person again; 01310d8 fixes that, and every check and run below is on 01310d8.
Checks: suite 874 passed, timing passed, `--driver next` e01 to e12 12 of 12, ratchet holds.

| Model (card S, e11 and e12, seeds 1 to 3) | Pass | Fail | Crash | Text calls |
| --- | --- | --- | --- | --- |
| LFM3-1.7B, round 3 | 3 | 1 | 2 (Ollama HTTP 400, e11 s1, e12 s3) | 0 |
| LFM2.5-24B-A2B, round 3 | 6 | 0 | 0 | 0 |

LFM3's fail (e11 s2) ran out of tokens after the person answered and made no call. In 24B e11 s2
and s3 and e12 s3, the model still set its own numbers (196, 95), and stone sent it to note the
person's words, which gave 197 and 97.9. Runs are under the climb4 scratchpad after3/.

Open: a model that writes its own conversion into the note ("7.7 inches (196 mm)", 24B on aaf74a3)
still gets its numbers; stone cannot tell them from the person's.

### Round 4: PR 76 review round 1

- A `stone set` with sizes while no note has read an answer no longer offers a `stone note
  "<...>"` line to fill in: a model that had not asked yet filled it with its own guess. NEXT is the
  ask itself, FIX says the sizes were not set, and the note line comes after NEXT. stone go stops on
  the question and tells the person to run stone note with their answer, then stone go.
- NEXT lines quote the product name, the source, a figure's name and recipe text with shlex.quote
  where a shell would act on them; first_url stops at shell characters. Tests run the lines through
  a real shell.
- With several W x D x H triples in an answer, the metric one wins over inches.

Checks on 885eff1: suite 891 passed, timing passed, `--driver next` e01 to e12 12 of 12. The ratchet
holds against the merge base f2d5fa0 and on climb4 merged with origin/main, but not against
origin/main alone: main gained floor groups (#73 to #75) since climb4 branched.

| Model (card S, e11 and e12, seeds 1 to 3, run one model at a time) | Pass | Fail | Crash | Text calls |
| --- | --- | --- | --- | --- |
| LFM3-1.7B, round 4 | 4 | 0 | 2 (Ollama HTTP 400 e11 s2, HTTP 500 e12 s3) | 1 |
| LFM2.5-24B-A2B, round 4 | 4 | 2 | 0 | 0 |

The 24B lost two runs (e11 s1 and s3) because NEXT now asks while the person had already answered:
after the answer it set sizes, got "ask the person" back 7 and 8 times, never ran stone note, and ran
out of steps. In round 3 the same move led to stone note and a pass. An HTTP 400 came with one model
alone on Ollama, so the crashes are not only from two models at once.
- 2026-11-24 stone doctor floors (doctor/top1, doctor/top3, doctor_heldout/top1, doctor_heldout/top3 in
  evals/floor.json). evals/doctor: 45 cases written before the words were tuned (d*, r_k2_detached_plate),
  then two sets Codex (gpt-6.1-sol) wrote blind from the taxonomy alone, each scored once before its misses
  were used to tune: h* (30) scored top-1 33%, top-3 40%; b* (40) scored top-1 57.5%, top-3 67.5%. After
  tuning, all 115: top-1 99%, top-3 95%. evals/doctor_heldout is a third blind set (40, same model, written
  after the tuning) scored once: top-1 60%, top-3 70%. Nobody tunes on it; a later round needs a new set.
  SHA-256 of the sealed set, file by file:
  be751c2c73fb09af85de3d893b220b299462196efdca3dd5564819b790689ce9  evals/doctor_heldout/f01_corner_peel.json
  117affe787475bc0c0724a5de807c80d8bb956991f08ff9289cae7de195b46b6  evals/doctor_heldout/f02_skating_badge.json
  866339efd69f8affde9b64ef793bdffac8efe40707f1836ed26602636f198b80  evals/doctor_heldout/f03_air_nest.json
  e06c0cdac4b49fe9e6cfc1cfd4f56cfc280518a9135b6ab817e02b4a86fa9218  evals/doctor_heldout/f04_heater_snowball.json
  82512f6c24eb7b2f911431e6b67461d7ce9ad909ab9d709a2de4038fcc262fc7  evals/doctor_heldout/f05_hairy_fence.json
  d0ba2b4080169cb021b279785c5dba222dc0c00d4f61eac6510e9bc7c52c6fba  evals/doctor_heldout/f06_sparse_walls.json
  f35cab7cd1c7313f14a6548e1dbc7f9a74b87b29afa29dcbdd53012620b1b2d8  evals/doctor_heldout/f07_plowed_top.json
  6ee9a5646456eef995055a9cbb7071560d1741c5a579b2f1fe3dc38cefed04d5  evals/doctor_heldout/f08_no_output.json
  415af2c2a740cae972067d4be92c120d139626bd1f8487c3e3fb6788ae394a0d  evals/doctor_heldout/f09_sideways_roof.json
  cebc49c97d6bbc7f2b4e77a17dd560e821fd2e50c84b8a902fd29638451930f0  evals/doctor_heldout/f10_wide_base.json
  31c816cf7c834f8df8f020c7c5757ebebd8f92516b0da3552377d122f0ff4ea3  evals/doctor_heldout/f11_regular_stripes.json
  cffe7f5a11b703df9bc72fa2ea5e3fb125a991a02a5a28628e4e19b4a7be5a17  evals/doctor_heldout/f12_split_layers.json
  bcd0a061400a354c02a49f97dbf386c0cabc1609f4aa163d064a657ec625f7af  evals/doctor_heldout/f13_echo_letters.json
  1633df926b77ce29ccf4e700a5f79ee4fff00cdd7e86b51176e307d4015b8418  evals/doctor_heldout/f14_sagging_chin.json
  b0e85e05c2d45f878af93559cee7e241d4f83fac7745f31f020b360c0a9c9760  evals/doctor_heldout/f15_sagging_span.json
  fe361708835b12991045fbce4a7cdc386434242ec63d9300e15f14be9df36d75  evals/doctor_heldout/f16_fallen_trees.json
  38ceb87e541c09672641edf579c4fe70d73fa6ac6cb5d7caa9a1aed9a9a65f26  evals/doctor_heldout/f17_patchy_sheet.json
  f9ae30f57858feba29bcda72cbd2ba2b1d6514a12a5eed14443eef8f31295d95  evals/doctor_heldout/f18_random_bumps.json
  b8fa33a81b7b24518f59efc50d4dc1cb225c381ba264126deb004b20531e7539  evals/doctor_heldout/f19_vertical_zip.json
  d2c54d2e43605b55725d916e97410c7e34d9b210e42539ab30b91a794085f368  evals/doctor_heldout/f20_popping_spool.json
  61848254780554485384d94174ac2298c8e4893a810899eaba8a7a0dea518fed  evals/doctor_heldout/f21_enclosed_pla.json
  cb3f59618c403db3a1357c1e94a58a123747e88f2f12579adb038b0e6480a2da  evals/doctor_heldout/f22_chewed_tpu.json
  8cf91a3070289b12b43366bfbb98de13809fc1e5c3ad34735004f34dc9f94fda  evals/doctor_heldout/f23_fallen_spire.json
  4530d422326e7fa6cc8d1a0798e47cc625336f6a6ad3bbef22c587135e821651  evals/doctor_heldout/f24_abs_fissure.json
  61a724312be6c057d65d98cb90999cb84cdfeda80e8f5d02743c29cd1c9c886f  evals/doctor_heldout/f25_holey_roof.json
  4ff5e452dba9e6d3581ee46977c58aa7edc28983b694b45bcb88475f540e8994  evals/doctor_heldout/f26_cfs_cut.json
  b6bccb614298a57437a5db266e9f9b861f4f39b363c54f6a8d7e209aba1404a9  evals/doctor_heldout/f27_interface_weld.json
  61a6784b241bc477e1f6d9bd9f5be79d349e4625b290e692bfcdb00e642b3ae2  evals/doctor_heldout/f28_temp_halt.json
  06a19f1084aa10ba38a94d2ed34f953125d1105544211ff2b42caffd824238b5  evals/doctor_heldout/f29_clean_release.json
  6b84c144978cdc8b84b1b0100b427cdd2efed9c4511a2f8dd5fc1441268b1980  evals/doctor_heldout/f30_asa_corners.json
  553e293d7e7c8db15099adaec5e435b5e752b48cabe3d21a9260b12a19a74981  evals/doctor_heldout/f31_ams_load_loop.json
  fe3a1570d9974275a14a6880586cd80face51b5277c95e683d143511fc648aaa  evals/doctor_heldout/f32_hotend_cocoon.json
  f001ddc2da0b03fd52be7f1c7e735952c39fcc4225a3c01a2d715570e1b5da53  evals/doctor_heldout/f33_bridge_curtain.json
  3f580d2d43a026b416973b396c896077b4754de9599e6eeed841fef0fff4064b  evals/doctor_heldout/f34_tpu_rattle.json
  c9d7688974b1da631462b1d7b1611bc33df4380215d1e7995c35e6a8aeb0e570  evals/doctor_heldout/f35_stair_step.json
  43457417217bb4e4a61a26f640ef2e0e454acaaa94c3d2b8216edfbc58575ba7  evals/doctor_heldout/f36_sensor_jump.json
  ba75a534a543c65aa9d835993ba4972ec7a5bdcdd42daf8c56420ca603ebb80e  evals/doctor_heldout/f37_interface_gap.json
  b0ac3769424947812e6030e6a8c0ca3b0b65148fa66bd4def71651d776c03bb8  evals/doctor_heldout/f38_pc_cold_split.json
  2da0319e2380c5db0d17571a6a0d61faa9c53fd8dd1db5e1b5feeedbafde3125  evals/doctor_heldout/f39_nozzle_stop.json
  a98993443da7e3ad3f506fbe866e97a7044e6132b802e16f2c1d9b4389ebe378  evals/doctor_heldout/f40_bendy_sparse.json


## 2026-11-23 models 1: a landmark no recipe makes, from the best open model

What changed for the person:
- A request for a landmark no recipe makes ("a model of Cologne Cathedral that fits my 220 mm bed")
  no longer ends in "no recipe": `stone recipes` sends it to `stone models "<landmark>"`, which looks
  the landmark up on Wikidata for its names in ten languages, searches Printables and Wikimedia
  Commons (Sketchfab only with the person's own key in STONE_SKETCHFAB_TOKEN; Thingiverse and
  MyMiniFactory are left out), leaves out what is not a model of it (keychains, lamps, maps, signs,
  LEGO sets, paid models, closed licenses) and lists the best five with author, license, files and
  popularity, plus a plain note for each license that limits the print (NC, ND, standard).
- `stone models --take <n>` downloads it (STL, 3MF read without lxml, or a glTF zip), keeps the whole
  model file over its parts and leaves out cranes, pins and an older year's version, writes
  credits.txt, joins and repairs it (holes closed, torn bodies rebuilt as solids, crumbs dropped) and
  stands it on its base.
- `stone build` scales it to the size asked (tall, long, longest side, or the largest that fits the
  bed), names its thin features (needles, blunt points, rods, thin edges, and how much the slicer
  drops), cuts it into numbered parts that fit the bed with square pin holes (filament pegs where a pin
  does not fit, glue where neither does), lays each part flat side down, and runs stone's checks on
  every part and the pins, with grams and hours each and in total. Every mesh change gets a line.
  build/views.png shows it assembled, build/layout.png the parts as they print.
- A failing build's NEXT is the next model (`--take n+1`); with none left, a question for the person.

Evals: evals/models m01 to m06 and evals/models_heldout h01 to h06 (sealed, never run, in GUARDED).
evals/models_grade.py: credits, every part's fit and checks run again, the parts put back together
within 3% of the size asked, and a blind Opus judge on the views against the Wikipedia lead photo.

`--driver next`, seed 1, on 8340029:

| spec | result | model it ended on | why |
| --- | --- | --- | --- |
| m01_cologne | PASS, judge 8 | 923462 assistantmaster, CC BY-NC-SA | 204 x 109 x 216 mm, all 14 checks |
| m02_notre_dame | FAIL, judge 7 | none fitted at the end | min_wall 0.28 and 0.40 mm; take 2 fails watertight (touching solids, below); the 10 step budget ran out on take 4 |
| m03_sagrada | FAIL, judge 7 | 1631289 Ninomalbinho, CC BY-NC-ND | 8 parts, 24 pins; parts 2, 4 to 8 fail islands; takes 1 and 2 fail min_wall 0.55 mm or islands |
| m04_eiffel | FAIL, judge 8 | none fitted at the end | thin features spoke on every take; all fail min_wall (0.10 to 0.14 mm), overhang 14 to 18% and islands |
| m05_taj_mahal | PASS, judge 9 | 1791921 Bazzar701, CC BY-NC-ND (3MF) | take 1 failed min_wall 0.41 mm; 150 x 150 x 107 mm, all 14 checks |
| m06_st_basils | FAIL, judge 9 | St. Basil's, 2 takes | min_wall 0.29 and 0.63 mm, overhang, islands |

The first run (6bd4bcd) found the faults 8340029 fixes: "St. Basil's" searched as "St" and took an
egg cup named Stockholm (the judge scored it 1), a 3MF needed lxml, a LEGO set was offered, and the
2014 and 2022 versions of one Eiffel model were merged.

Unchanged: `--driver next` on evals/engineering e01 to e10, 10 of 10. pytest `-n 16 -m "not timing"`
878 passed, 1 skipped (the network test); `-m timing` 1 passed. `ratchet.py --check-git origin/main` holds.

Open:
- stone's min_wall (0.8 mm, two nozzle lines, at the 3rd percentile of thickness) fails nearly every
  real landmark model at a desk size, including ones made and printed by thousands (MiniWorld3D). The
  thin features report already names them. Whether a found model should keep that bar, report it
  instead, or use the slicer's own floor (0.1 mm, what Arachne still draws) is a decision for the
  owner, not this climb; nothing here lowers a check.
- x and y cuts leave pieces of leaning spires starting in the air in the next part (m03 islands).
  Cutting only in z where the footprint fits, or laying each piece on its own, is the next step.
- Models built from solids that only touch keep coincident vertices that a float32 STL merges into
  non-manifold edges (m02 take 2, m04 take 2). A union with copies shifted 0.01 mm fused them but
  took over 20 minutes, so it is not in.
- A run spends 3 of its 10 steps before the first take, so it tries at most 3 or 4 models.
- The Printables API is undocumented and may change; the search fails softly with a FIX line. The
  Sketchfab path is untested here: no key was set.

## 2026-11-24 models 2: thin walls measured, supports, cuts only where the bed is too small

What changed (11d596b), as the lead decided after models 1:
- A found model's min_wall is measured, not a bar: a part fails only when over 1.5% of its volume is
  under one nozzle line, or when what the slicer drops cuts a piece loose. The 1.5% comes from models
  people print: the Taj, St. Basil's and Notre-Dame picks sit at 0.03 to 0.10%, and the most made
  Eiffel model (180 makes) at 0.89%. The report names the remedy: print bigger, a 0.2 mm nozzle, or resin.
  Recipes and engineering parts keep the 0.8 mm bar and the overhang limit.
- Overhangs and pieces in the air print on supports; the build reports the grams and hours of support.
- Splits cut in z first and across only where the footprint is wider than the bed, at the smallest
  section away from spires, and every part is laid flat.
- A clear lead in the ranking is taken without a question.

`--driver next`, seed 1, on 11d596b, judged blind against the Wikipedia lead photo:

| spec | result | judge | what the judge marked down |
| --- | --- | --- | --- |
| m01_cologne | PASS | 8 | west spires, tower proportion, west facade |
| m02_notre_dame | PASS | 9 | transept rose windows |
| m03_sagrada | PASS (take 2) | 8 | facade bell towers, overall massing |
| m04_eiffel | PASS | 9 | top antenna, lattice and arch detail |
| m05_taj_mahal | PASS | 9 | main dome, plinth |
| m06_st_basils | PASS | 9 | domes, bell tower |

6 of 6, up from 2 of 6. Unchanged: `--driver next` on evals/engineering e01 to e10, 10 of 10.

Also found this round: two sessions on Parish1 were killed by systemd-oomd while the suite ran with
`-n auto` beside these evals, and /tmp there is RAM. Heavy jobs now go through `scripts/heavy` (#81),
and video frames are packed (#98).

Open: the held-out six stay sealed until the build path (`stone landmark`) is graded too; LFM3-1.7B
has not driven a landmark run yet.

## 2026-11-24 landmarks 1: a landmark built from its references

What changed for the person: "Print me Cologne Cathedral, about 20 cm tall" builds the cathedral
itself, true to its measured shape, instead of taking a stranger's mesh. `stone landmark "<name>"`:
- finds the landmark on Wikidata (coordinates, height, style) and its outline and every
  `building:part` in OpenStreetMap's Simple 3D Buildings (height, min_height, roof shape and height);
- builds each part's walls and roof (gabled, hipped, pyramidal spires, domes, onion domes), and adds a
  style kit keyed on the Wikidata style: Gothic buttresses, pointed windows, pinnacles, portals and a
  rose window; Mughal onion dome on a drum with its finial, iwans and chhatris; domes with drum and lantern;
  steel lattice;
- loads a cited reference pack (`src/smoothstone/landmarks/<slug>.json`) for facts OSM lacks, and a
  tier L model can add one with `--refs`;
- makes it printable at the size asked: spires and finials thickened from the top down, never
  shortened, walls at least 1.2 mm, a 2 mm plinth, then modelprint's checks, split, pins and views;
- credits OpenStreetMap contributors (ODbL), Wikidata and Wikipedia; every guessed height is marked
  guessed in `refs/landmark.json`. With no 3D parts in OSM (Sagrada Familia) it says so and NEXT is
  `stone models`.
A request to find or download a model ("Find me an open model of ...") still goes to `stone models`;
the six evals/models requests now say "Find me an open model of", sizes and beds unchanged.

Evals: evals/landmarks l01 to l06, graded by evals/landmarks_grade.py on the checks and bed, height to
length and width within 4% of the cited references, the tallest point within 4% of its cited height,
feature counts, credits, and the blind Opus judge on the views against the Wikipedia lead photo.
Notre-Dame's spec names its tallest point, the restored 96 m spire, with its source, because Wikidata's
height (P2048) for it is the 69 m west towers. evals/landmarks is now guarded by the ratchet.

`--driver next`, seed 1:

| spec | landmark built | judge | found model (m spec) | judge |
| --- | --- | --- | --- | --- |
| Cologne | PASS | 8 | PASS | 8 |
| Taj Mahal | PASS | 8 | PASS | 9 |
| Milan | PASS | 6 | (none) | |
| Notre-Dame | PASS | 7 | PASS | 9 |
| St Paul's | PASS | 8 | (none) | |
| Eiffel Tower | PASS | 8 | PASS | 10 |

Proportions land within 2% of the references (Cologne height over length 1.083 against 1.082).
LFM3-1.7B with card S built Cologne and the Taj Mahal on its first try, one `stone landmark` call each,
judged 8 and 8.

Open: the built models score a point or two under the best found models on likeness, because tracery,
crockets and sculpture are simplified. Milan has fewer, thicker pinnacles than its 135. Physical prints
untested. The held-out six stay sealed until the last run of this track.

## 2026-11-24 landmarks 2: closer to the real building, and buildings with no reference pack

What changed for the person: the six landmarks with a cited pack look more like the real ones, and a
cathedral nobody wrote a pack for (Westminster Abbey, St. Vitus, Florence) builds from its OpenStreetMap
parts alone. GPT 6.2 Sol wrote the modeling and was stopped at a two hour limit before its report; the lead
finished it, found the faults below and ran the checks.

- Gothic detail: flying buttresses as open self-supporting arches, rose windows, west galleries, gables and
  towers, from pack facts (landmark_gothic.py). Detail too fine for the size is dropped and the build says so.
- No pack: matched west towers, a dome split from its lantern, bell towers Wikidata lists as part of the
  building, low walls from the outline (landmark_massing.py). A nave mapped as two gabled halves about a
  church's axis gets one ridge, marked as inferred (Florence had an "M" roof).
- Milan: 135 pinnacles. 115 positions are from the Duomo's published plan, 4 side pins are mirrored and 16
  around the crossing are approximated; the pack says so. Pier widths come from the mapped outline.
- Fixed from landmarks 1: a taper scaled about the map origin, so corner pinnacles leaned. Now `_tapered`.
- Name search prefers an exact name; a cached answer is used only for the name it was found under.
- Grading: the judge's bar for landmarks is 8 (found models keep theirs). `in_mesh` counts a feature in the
  printed mesh, not in the generator's labels: Milan has 134 standing (the main spire is under its statue),
  and the old model 50 of its 54 labels. l03 now wants 135 pinnacles, 134 in the mesh, where it wanted 50 labels.
- New specs: l07 to l10 (no pack) and regressions/r8_milan_pinnacles.

`--driver next`, seed 1, one attempt per code state. "Before review" is c3aa0d6. "After review" is the last
state whose change can touch that spec: 626a339, fabe827 (St. Vitus, Florence) or 647c3df (Milan).

| spec | landmarks 1 | before review | after review |
| --- | --- | --- | --- |
| l01 Cologne | 8 | 9 | 8 |
| l02 Taj Mahal | 8 | 8 | 9 |
| l03 Milan | 6 | 8 | 7: FAIL |
| l04 Notre-Dame | 7 | 9 | 9 |
| l05 St Paul's | 8 | 8 | 8 |
| l06 Eiffel Tower | 8 | 8 | 8 |
| l07 Westminster Abbey | new | 9 | 9 |
| l08 St. Vitus | new | 8 | 8 |
| l09 Florence Cathedral | new | 9 | 8 |
| l10 Sydney Opera House | new | not built: the honest FIX line and NEXT `stone models` | same |
| r8 Milan pinnacles | 50 of 135 standing | 134 standing, judge 7: FAIL | judge 7: FAIL |

Milan is below the bar. l03, r8 and LFM3-1.7B ask for the same model: the judge gave 7, 7, 8 on fabe827 and
7, 7, 8 on 647c3df. The steady complaint is right: the six front piers are too shallow to see. Open, next.
LFM3-1.7B with card S, one `stone landmark` call: Milan 8 on 647c3df; Westminster 9 and the Sydney fallback at
6963db0. m01 to m06 pass (found models, run before the review fixes).
Suite on 647c3df 1452 passed, 2 skipped; timing passes; the ratchet holds.

From review: the pier feet hung 2 mm over the bed and made the print 2.6 mm too long; a Mughal building with no
pack and a bell tower outside Gothic lost their facade detail; estimated pinnacle heights were filed as
measured. Front spire tips now come from the laser survey (65 m and 55.25 m), not the map's rounder 60 and 46.
The first fixes stopped Milan from building (626a339, a loose shaving) and split St. Vitus's low walls in 45
pieces (judge 7); the unit tests passed on both, and only the evals caught them.

Open, from the judge: Milan's piers are shallow and its spires plain rods; the Taj lacks its guldastas; the Eiffel's second deck is nearly missing; St Paul's side
walls are blank; St. Vitus's south tower is too slim. Physical prints untested. The held-out six stay sealed.

## 2026-11-24 Milan's front piers

Milan's six front piers are now square shafts as wide and as tall as the survey says, with a groove up the
broad ones, string courses and gablets; the front spires step from a shaft to a needle. Course heights and the
spire's step are estimated from a photograph, and the pack says so. The limit for a loose gable shaving grows
with the print, a guard proven on a synthetic block only: Milan built at 290, 320, 350 and 400 mm without it.

The judge did not move: l03, r8 and LFM3-1.7B (card S) got 7, 7, 7 at 1964db8, where 647c3df got 7, 7, 8. All
three still fail the bar of 8. It says the piers barely project. They project the 1.8 m the map gives, 2.3 mm at
this size, and its one front view draws the facade about 120 pixels wide with the light head on. Whether the
views are too coarse is the next question, tested on older models first. Suite 1454 passed, 2 skipped; timing
passes; the ratchet holds.

## 2026-11-24 Rejected: showing the landmark judge the faces up close

views.png draws a facade about 120 pixels wide with the light head on, so a 2 mm pier does not show there. The
trial gave the judge a second picture from the print files: the four faces, 560 pixels each, turned 25 degrees,
lit from one side. Same rubric and bar. The gates were committed before any judging (272438e, not merged):
medians of three on saved builds, and one miss rejects the change.

| Saved build | views.png | With the faces | Gate | |
| --- | --- | --- | --- | --- |
| landmarks 1 Milan | 6 | 7, 7, 8 | below 8 | held |
| Milan at 647c3df, tapered piers | 7 | 8, 8, 8 | below 8 | MISSED |
| landmarks 1 Notre-Dame | 7 | 7, 7, 7 | below 8 | held |
| St. Vitus at 626a339, walls in 45 pieces | 7 | 8, 8, 7 | below 8 | MISSED |
| Cologne's build asked as Milan | not asked | 1, 1, 1 | 5 or less | held |
| Florence's build asked as St Paul's | not asked | 1, 1, 1 | 5 or less | held |

Two misses: rejected. The views cannot tell a better model from an easier picture, so Milan's 7, 8, 8 at 1964db8
under them counts for nothing and its score stays 7. The judge keeps views.png and Milan stays below the bar.
The passing landmarks (once each): Cologne 8, Taj 8, Notre-Dame 9, St Paul's 9, Eiffel 8, Westminster 8,
St. Vitus 8, Florence 8.

What the close pictures showed, as things to build, not scores: Milan's crossing spire is a thick smooth cone and
its pinnacles blunt rods; Cologne's two west towers do not match, and its choir walls are loose slabs; the Taj's
iwans are smeared and its minarets differ; St. Vitus's great tower steps in above the eaves; Florence's tribune
half-domes and lantern are plain; St Paul's side walls are nearly blank.

## 2026-11-24 landmarks 3: roof directions, repeated parts and twin towers

- `roof:direction` is the way a roof face looks, so a skillion roof is high behind it. We built it the other way
  and did not read ENE and its kind. The maps of five landmarks carry 202 directed skillion parts (Cologne 6,
  Notre-Dame 28, the Eiffel Tower 8, Westminster 120, St. Vitus 40), and all agree with OSM's sense. Not all became
  shed roofs: the tower is a lattice, Notre-Dame's pack turns some into flying buttresses, and some of Cologne's
  came out right by luck.
- A part with no height takes the level its same-plan twins share, or is dropped when that level is already drawn.
  The Taj's south-west minaret had three such parts standing as 40 m columns.
- Where the map details only one of two matched west towers, the other gets the same details, mirrored and marked
  guessed. Cologne's map draws its gables and pinnacles on the south tower only.

One eval each at 5eef4d5, `next` driver, card S, all passing: Cologne 9 (was 8), Taj 9 (was 8), Westminster 9
(was 8), Notre-Dame 9, St. Vitus 8, Milan 8, St Paul's 8, Eiffel 8, Florence 8. Milan, St Paul's, the Eiffel Tower
and Florence are the same meshes as before, byte for byte, so Milan's 8 is the judge's noise on the mesh that got
7, 7, 7 at 1964db8. It is not progress, and Milan still counts as below the bar.

## 2026-11-24 landmarks 2 review: what the grader measures and how a name finds a building

The round 2 mediums on PR 116, fixed.

- An exact name counts first unless its kind names a place and does not end in a building word (a "cathedral city"
  is a city, a "parish church" is not a parish). Evidence of a building (its kind, a style, an architect, a floor
  count) comes ahead, and stands in for a missing description. Cached answers from the old ranking are ignored. The
  old list of place words missed "human settlement". Of 30 names looked up live, 28 answer as before; Windsor now
  gives the castle (it gave a parliament constituency) and Mont Saint-Michel gives the abbey. Still wrong, and not from this change:
  "Pantheon" gives a building in Leipzig and "St Pauls" a church in Bristol.
- With no pack, the west towers are the west end's pair when it has one, so a taller choir pair does not win.
- A low part mapped off the ground keeps its roof beside the outline's walls, on wall up to its own base, unless
  its height is guessed or a part as tall as the walls stands over it.
- `in_mesh` counts pinnacles in the files that print, turned back to the generator's frame. Milan: 134.
- A spec's cited length and width are compared with the built print at scale, 4% tolerance. A linked bell tower
  moves the reference only where the spec names that tower. Westminster's length is 0.7% off, St. Vitus's 1.1% and
  0.8%, Florence's 2.5% and 1.4%.
- l09's cited width is now 97 m, the survey outline's. It was Wikidata's 90 m, which nothing compared, which does not
  say where it is taken, and which the build (98.4 m) missed by 9%.

Westminster, St. Vitus and Florence rebuilt from saved references are byte-identical before and after. The nine
saved builds pass the new measurements; no judge ran, because no mesh changed.

## 2026-11-24 landmark names: the thing a person means

100 famous names, looked up once and scored from the recorded answers. main before #138 gave 78 and main 79:
"White House" was Moscow's, "Buckingham Palace" a cottage in Western Australia, "Rialto Bridge" one in Dublin and
"Petra" a particle accelerator.

- A lookup reads Wikidata's search, the article Wikipedia gives for that exact name, and Wikipedia's search. If
  Wikipedia does not answer, Wikidata's search still does.
- The score is how many Wikimedia sites write about a thing, times whether the name is its name (accents, "St." and
  "Saint" and "The" aside), times whether it is a building. A town scores .02, so "Reims" and "Santiago de
  Compostela" give their cathedrals.
- The names were split in two. First score on the half kept back: 48 of 52. The misses showed "meeting place" and
  "historic place" read as towns, an attack taken for a building, and an exact name weighed over fame; after those
  fixes, 98 of 100. "Salisbury" still gives the city (no search returned the cathedral) and "Skellig Michael" the
  island group. A third set of 50 names, scored once after that and not tuned on: 47. "Peterhof" gives an inn and
  "Mezquita" a mosque in Huelva; the third, "Frauenkirche", gives Dresden's, which is fair.
- After review: an event word before a building's kind ("siege castle") leaves it a building; fires, crashes and the
  like are events; a name may say the place ("Example Tower Paris"); a busy or broken-off Wikipedia answer counts as
  none; a population dated before 1900 is nobody living there. Scores unchanged: 47 of 48, 51 of 52, 47 of 50. Left:
  the exact name of a part whose Wikipedia title redirects to a much better known building still gives the building.
- The 98 are a recorded test, `tests/fixtures/landmark/names.json`. No sealed landmark's name is in any set.

### 2026-11-24: reference parts

A pack can carry parts (`docs/REFERENCE_PARTS.md`): prisms, lathes, beams and openings, from cited sources, for what the
map does not have, and a lean. A strong model writes them once; every model builds them with `stone landmark "<name>"`.

- A pack may give its own `plinth`, a beam may taper along its path and be round, and a part held at both ends may be as
  fine as 0.8 mm (`least`). These were the writer's wishes after the first three packs. Hollow lathes were written and
  taken out in PR 157's review: their walls came out thin on a slope, and no pack uses one.

### 2026-11-24: a guessed height, and rooms that are not parts

From 40 landmarks never built before (no model, no judge), looked at one by one.

- A part with no mapped height took the median height of all measured parts, each counted once. York Minster's eight
  pinnacles at 54 to 63 m made six small chapels 54 m blocks. It now takes the height at which half the ground covered
  by measured ground parts is lower: 22 m there. With nothing measured on the ground, the old median stands.
- `indoor`, `room` and underground elements are not parts. The White House's four toilets stood as 21 m blocks.

### 2026-11-24: a landmark's name is enough

- The 1.7B model's one attempt at l16, "A 3D print of the Arc de Triomphe", went to the figure recipe: the name has no
  building word, so no request route saw a landmark. Where no recipe fits, a request whose own subject is a shipped pack's
  name, or a name Wikidata knows best as a structure that stands (5 or more sitelinks), now goes to `stone landmark`.
- A name is looked up only as the thing asked for: not in "a clip for the Arc" or "a white house". A definite answer is
  kept for 7 days; an offline or partial one counts as no, for 10 minutes.
- A statue is refused by what Wikidata calls it, before any map: its pedestal or the building under it was built.
- Routing is not a promise to build. A statue, or a site with no mapped outline and no pack, is refused there, and the
  next command is `stone models "<name>"`, where a real model of it may be found.

### 2026-11-24: PR 141's review mediums

- Several parts with no height at one spot share the missing levels, lowest first. They stood as full columns.
- A twin's level counts only within the height of the stack it joins, so a pinnacle's plan repeated on another tower
  gives none. An explicit `min_height=0` is kept.
- A guessed height raised by a sourced amount stays marked guessed.

The parts of 41 saved maps resolve the same before and after.

### 2026-11-24: the base follows the plan

The 2 mm base was the convex hull of the plan, a boat-shaped plate around Speyer, Lincoln and Buckingham Palace, and the
judge's complaint on St. Vitus. It now follows the mapped plan, with short joiners between bodies, as Notre-Dame's
already did (its `plinth_follows_plan` fact is gone). The Eiffel Tower's four feet keep one plate.

- A model too slender to lean the 10 degrees the print check asks for gets a wider base (the Washington Monument leaned 7).
- Two walls that meet along a line are welded with a thin bar where that line stops the mesh from closing. Westminster
  needed it, 262 short edges 10 to 34 mm up; its old base happened to close.
- Where that still leaves a sliver, edges under 0.03 mm are collapsed (0.01 before). The Lotus Temple failed on one.

One judged build each on the new base: Cologne 9, Taj 9, St Paul's 9 (was 8), Westminster 9, St. Vitus 8, all passing, and
the judge no longer mentions St. Vitus's base. The other four graded bases are unchanged.

### 2026-11-24: which mapped thing is the landmark

- A castle, fort or bridge that Wikidata ties to a map area, not a building, is every part and building on it. Windsor
  Castle was its Round Tower; Edinburgh Castle, Tower Bridge and the Alhambra were refused. Windsor, with 13% of its
  ground measured, is now refused too. A building that bears the landmark's whole name is still the landmark.
- A site past the map search is searched again, up to 1 km.
- Overpass is asked for the landmark's own area; it answered with buildings alone. A dome on a castle keeps its walls.
- A tower, obelisk, dome, cone or pyramid with its own height and no parts is its own part; a gabled box is not. An
  obelisk tapers to 63%, guessed.
- A statue is refused as one.
- A bridge whose mapped parts cover under half of its area is refused. The Golden Gate Bridge (2%) was its two towers.
- Where the parts that stand on the ground cover under half of a building and rise above the outline's own height, the
  outline is a part too. The Dome of the Rock was its dome with no octagon, and Angkor Wat's galleries stood in the air.
  Of 50 saved maps this changes those two and the Flatiron Building, and none that is graded.

### 2026-11-24: the Space Needle and the Leaning Tower of Pisa

Two packs of reference parts, written by GPT-6.2 Sol from engineering and museum sources it opened and photographs it
compared, built by the one command. One judge each on the builds they were written from: Space Needle 9, Pisa 9.
Then built once each from the plain request, as a small model would (l12, l13): 9 and 9, every check passing.
A grading spec may now cite a plan's dimensions (`dimensions`, with a source and why) where the map has no outline, or
not the one that prints: Pisa's axis moves 3.9 m in its height, and its sixth gallery sets the length. The bridge Sol wrote first scored 6 (hangers as fat as
the tower legs, a bar for a base), so it waits for a redo on the finer parts.

### 2026-11-24: Golden Gate Bridge, Stonehenge, Himeji Castle and the Arc de Triomphe

Four packs of reference parts by GPT-6.2 Sol, with grading specs l11 and l14 to l16. Every attempt, in order, one judge
each on what the plain command builds:

| spec | attempts (pack commit: result) |
| --- | --- |
| l11 Golden Gate | 94bb6a2: likeness 7, fail. 2428759, slimmer legs and a hanger every 100 ft: 7, fail |
| l14 Stonehenge | 94bb6a2: 9, pass |
| l15 Himeji | 94bb6a2: build refused, its map id was the outline. 6f3fa96, every part redrawn: 8, pass |
| l16 Arc | 94bb6a2: likeness 9, fail on width (sculpture past the published 22.21 m). 4908e8b: build refused, axis 90 degrees off. dc120bf: 9, pass |

l11 stays open: at 180 mm true scale its towers are 2.5 mm wide. Stonehenge's 6.7 m is the great trilithon's standing
stone above ground (Wikipedia). Its turf margin is the pack's choice.

LFM3-1.7B, card S, one attempt each, judged: l11 7, fail (4908e8b, the pack before the variant). l12, l13, l14 and l15:
9, 9, 9, 9, pass. l16 fail: the request went to the figure recipe, which "a landmark's name is enough" fixes. The packs
changed under that run: l12 ran on 2428759, l13 to l16 on dc120bf.
One rerun each on the final code (514914b): l11 7, fail; l16 9, pass.

Of 40 landmarks never built before, 35 now build (30 before). Not built: the Statue of Liberty and Windsor Castle, and
the Golden Gate, Himeji and Stonehenge, which these packs cover.

### 2026-11-25: Windsor Castle

A pack of reference parts by GPT-6.2 Sol, with grading spec l21. Sol's weekly quota ended before it compared its build with
the photographs. One attempt each at 398a5b3: judged 8, pass; LFM3-1.7B, card S, 8, pass. Not from a source: the ground is
taken as 46 m above the sea, so the 39.3 m height holds the print to the pack. The judge's notes stay open: the Round Tower
reads low, and the George IV Gateway's two towers do not stand out.

The review's geometry findings were fixed after that: towers and gates that hung past their terrace stand on the ground,
tower caps follow their towers, windows are shallow and clear of Augusta Tower, and the chapel's bays are three where
they were four so a window prints between its buttresses. Judged once at d749999: 9, pass, with the same two notes.
LFM3 was not rerun.

### 2026-11-24: a card for landmarks

`skill/landmarks.md` says how a large model writes the shapes a map lacks, and what makes a landmark read as itself at
print size, from the three packs judged above. A refused landmark points a tier L model there. Smaller tiers still get
`stone models` alone.

### 2026-11-24: PR 150's review mediums

A collapsed sliver's edge is no longer welded, and no bar goes below the bed; bodies that
meet only at a corner or across a hairline gap get a real join; the base is widened after the style's detail is added.

### 2026-11-25: the Sydney Opera House, the Petronas Towers and the Dome of the Rock

Three packs of reference parts by GPT-6.2 Sol, the first with lofts. Sol's weekly quota ended before it compared its own
builds with the photographs, so only the judge has. Every attempt, one each:

| spec | judged build | LFM3-1.7B, card S |
| --- | --- | --- |
| l10 Sydney | 398a5b3: 9, pass | 398a5b3: 9, pass |
| l22 Petronas | 398a5b3: no verdict (Wikipedia's lead image is an SVG logo). 2c50e9d, the judge takes the first photo: 9, pass | 398a5b3: no verdict, same cause. 2c50e9d: fail, no build. 7a998dc: 9, pass |
| l23 Dome | 398a5b3: 9, pass | 398a5b3: 9, pass |

The failed Petronas run was routing: the request's name was read as "Petronas Towers to 3D print", so `stone new` named no
landmark and the model went to the figure recipe. Earlier runs reached `stone landmark` by the model's own choice. A
name in capitals is now read anywhere in a sentence (the figures are in PR 172).

l10's height (67 m, Wikidata) and plan (183 x 118 m, New South Wales) are cited now. Not from a source: the
Dome's porches reach 28.7 m from the centre along the door axes by the pack's choice, 51.5 m across in the smallest box, at 45 degrees. Petronas's plan is the pack's measure of the map's podium and bustles.

The review found that the opera house's sails fanned from one point under their lowest row, in mid air. Each foot now runs
straight down into the deck: `stone slice` at 0.2 mm finds 2 unsupported ledges, 24 before. Its stair starts at the
pavement, the concert hall's portico at Petronas shows, the Dome's windows clear its porch hoods, the south hood
stands on its columns, and a ring that crosses itself is refused. Judged once each after that: Sydney 8 (9 before; the new notes
are on the shells' spacing and shape), Petronas 9 (the first try gave no verdict: the judge could not read the photo until
PR 171), the Dome 9. LFM3 was not rerun. The Dome's porch roofs are 12 ledges before and after.

The second review round found that the plan sizes checked the packs against themselves. Petronas is held to 258.4 x 218.9 m
now, the box round the mapped mall, towers and bustles, and the Dome to the source's 49.7 m between faces, which its porches
widen by 3.6%. Sydney's base carries the published 183 x 118 m; a test holds the building to the mapped 170.5 x 114.2 m. A
first try made the base follow the map: judged 9, but failed Wikipedia's 183 m, which the spec already named, so it went
back. The corner of one restaurant sail that ran past its deck, the lopsided apex of the tallest sail, a slot behind
Petronas's entrance and thin piers beside the Dome's doors are fixed, and an opening's outline that crosses itself is
refused as a ring's is. Judged once each: Sydney 9, Petronas 9, the Dome 9, every check passing.

### 2026-11-25: openings another part covers, and four packs fixed

The second review of those packs found 14 windows of Himeji's (15 came out) and 2 pockets of Golden Gate's that were sealed inside
another part or cut the tower legs, and that no test cut the openings. A sealed one is now left out and named in the
notes, and the shipped-pack test cuts every opening and refuses a pack that has one. Golden Gate's shafts and struts keep
their own width (`least`), and its cables end at the saddle's published height. The credits name OpenStreetMap only where
a shape was drawn from it. One attempt each at bfc50f9, judged: l11 8, l15 9, l14 9, l16 9, every check passing (before:
7, 8, 9, 9). LFM3-1.7B, card S, l11, one attempt
on the same commit: 7, fail, on the portals. Two judges on the same shape gave 8 and 7, so l11 stays open at the line:
at 180 mm its tower legs are 1 mm wide and the gap between them is 1.4 mm.

### 2026-11-25: Tower Bridge, the Sagrada Familia, the White House and the US Capitol

Four packs of reference parts by GPT-6.2 Sol, with grading specs l17 to l20, all redrawn (`"replace": "all"`). I
corrected three before any judge ran: the White House and Sagrada no longer name map ids a mapper can delete, the White
House's south stairs run out to where HABS sheet 8 ends them, and Tower Bridge's slab ends at its abutments. One attempt
each at 2f710fb, judged: l17 9, l18 9, l19 8, l20 8, every check passing. LFM3-1.7B, card S, one attempt each on the same
commit, judged: 9, 9, 8, 8, pass.

After those runs the 8 Sagrada aisle recesses that lay wholly inside the transepts were taken out. They were sealed
voids, so nothing on the outside changed, and it was not judged again.

Not from a source: the Capitol's 4 m drop to the west terrace is the pack's guess; the White House chimneys (22.27 m) and
its depth to the stairs (51.7 m) are scaled from HABS's west elevation; Tower Bridge's 71.99 m is 63 m above the road plus
the 29 ft 6 in of headway under it. The judges' notes stay open: White House windows and attic too faint, the Capitol's
drum short, Sagrada's nave windows plain.

### 2026-11-25: batch 3's review

PR 170's reviewers read the packs' numbers, and these were wrong on the print: gables that faced along the road, not
across it (Tower Bridge's road dormers, Sagrada's nave end); the walkways 1 m under their published level; the Capitol's
wing roofs inside a solid parapet and its west stairs inside the terrace; the White House's north columns off the end of
their landing and the Truman balcony's posts off its deck; two louvres and two recesses inside other walls. One build and
one judge each at fc3259e: l17 9, l18 9, l19 8, l20 8, every check passing, as before. LFM3-1.7B was not run again: it
types the same one command, and the packs' names did not change.

More that is not from a source: l18's 95 m width is the pack's own base, l19's 22.27 m is built 22.58 m with the
chimneys, and Tower Bridge's road sits at a guessed 11.3 m, which makes its top 74.3 m over the pack's water, not 71.99.
The White House's windows are cut 1.3 m deep; views.png is lit from the camera, so a recess does not darken there.

### 2026-11-25: Two skyscrapers from the map alone

Specs l24 (Empire State Building) and l25 (Chrysler Building) have no pack: they hold what the map alone builds. One
attempt each at a036be4, judged: l25 8, pass; l24 7, open, because the map draws its mooring mast as a plain needle.
The judge could not answer for the Chrysler at first, since its article has no lead image; it now takes the article's
first photo, and that second look is the 8.

LFM3-1.7B, card S, one attempt each at 9fa3fdd, judged: Sydney 9, Windsor 9, Petronas 9, Dome 9 (the packs' final JSON)
and Chrysler 9, all pass. Empire State: no landmark at all. `stone recipes` listed the figure recipe, because "state"
reads as a typo of "statue", and the model set a figure's height. The same held for the Sacre-Coeur ("cover"), Marina
Bay Sands ("stand") and the Hook Lighthouse. A recipe that fits only through words of a known structure's name no
longer takes the request. Mount Rushmore and Mont Saint-Michel, which collide with "mount", are not known structures
to the lookup and still go to a recipe.

After that change LFM3-1.7B, one attempt at f6d4ce3, builds the Empire State Building: every check passes and the judge
gives 7, the same open mast.

Mount Rushmore is a mountain to Wikidata, so its request went to the under desk mount. A place of two or more words that
40 or more wikis write about now counts as a known landmark; the job goes on to the open models. "Mont Saint-Michel" is
still no known name: its item is called "Mount Saint-Michel" and the abbey is another. It needs a pack.

Eighteen more landmarks without packs, built from the map alone on 2026-11-25. Fourteen built and nine of them hold up.
Five were called ready and were wrong. Tokyo Tower was a 150 m stub of a 332.6 m tower; it is now refused, as is any map
whose tallest part is under three quarters of the sourced height. The Porta Nigra was two end blocks joined by a strip; it
is refused, as is any map whose separate pieces (a thin strip joins nothing, a shed is no piece) cover under 60% of the plan,
or one piece under 40%. Cape Hatteras Lighthouse (a cylinder) and the
Temple of Heaven (a drum and a cone) are one plain shape on the map: stone now looks for an open model first, and when
there is none, `stone landmark --plain` builds the plain shape and says so. Rialto Bridge is a solid block with no arch; a bridge whose
parts stand on over 90% of its plan is now refused (Tower Bridge's map: 3%). On 60 other
landmarks' saved references the two floors refuse only two old wrong readings (White House, Sagrada Familia).
The Brooklyn Bridge stopped at "HTTP Error 400": the map API refuses an area with over 50,000 nodes, and is now asked for a
smaller one. The bridge is refused all the same, since the map has no area for it.

The Lotus Temple at 18 cm tall failed on one sliver that 0.03 mm did not collapse. Edges under 0.05 mm are now collapsed
when nothing finer closes the mesh. A nozzle's line is 0.4 mm.

LFM3-1.7B on four landmarks with no pack (2026-11-25, one run each) passed none of the four. It built the Cape Hatteras
Lighthouse as a cylinder and said only that it was ready; a plain shape is now a question to the person (#189). It ended
Rialto Bridge with no message at all. Tokyo Tower's three open models all failed: one was laid out four files in a row
1.36 m long (#188), one needs 43 g of supports and stands on too little, and one touched itself along six edges. Found
models are now welded there as landmarks are. The test for that showed the repair before it, which every part goes
through, closing two touching boxes by cutting 17% off them and calling it clean; a repair that changes the volume by
over 0.5% is now refused. The one model named for the Temple of Heaven is an owl (#188).
With the fixes Tokyo Tower prints from its first model, 200 mm tall, all 15 checks passing, on stone's own NEXT lines.

The question stone asks when no open model of a landmark prints (Cape Hatteras, Rialto; LFM3-1.7B, five seeds each, one
run per code state): 7 of 10 runs put it to the person, then 1 of 3 with a line "Reply with just this" (stopped early),
then 3 of 10 with other parts refused while it waits. The misses thought past 2,048 tokens about who "the person" is, how
to ask and what was left to fix. Six wordings of that result were replayed over 16 landmark names, and the best two over 16
fresh ones: "NEXT: none. Your reply to the user is: ..." with the search lines left out asked in 29 of 32, the first wording
in 20 of 32. The ten runs with it: 10 of 10. Adding
"After the person answers (not before): stone note ..." below it, as stone's other questions have, asked in 29 of 32 again.
It is there because larger models need it, not for a gain: noting the answer is still the gap. Given the person's yes or
no, the 1.7B model noted it in 0 of 24 replays without that line and 2 of 24 with it. The ten runs on the code with that
line and the first review fixes: 8 of 10 (the 10 of 10 was before them); both misses thought past the cut. At temperature 0.1 five seeds are close to one sample.
