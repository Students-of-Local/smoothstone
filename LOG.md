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
