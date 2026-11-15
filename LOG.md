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
