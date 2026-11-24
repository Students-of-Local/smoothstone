# stone timelapse --fail

Shows how this print would fail, as a video, from the same camera as stone timelapse. It is a
physics model, not a recording. It does not print.

## When to run it
- The person asks "what happens without supports?", "what if it comes loose?", "show me it
  failing", or wants to see why stone says supports are needed.
- After stone build, or on any STL or sliced G-code.

## Rules
- Run: stone timelapse --fail (the built part) or stone timelapse <file.stl> --fail.
  That is auto: it shows the first failure the model predicts for this print.
- "No failure predicted; nothing to show." means the model says it prints. Tell them that. Make a
  video only if they still want one: --fail detach shows a loose part anyway.
- To see it without supports: add --supports off. A named mode turns supports off by itself.
- Named modes, only when asked: --fail supports, --fail detach, --fail droop, --fail bridge.
  "What-if" in the output means the model does not predict it. Say so: "this is for fun".
- --plate dirty: a plate that needs cleaning (holds about 5% as well). Use it when they ask about
  a dirty plate or a part that came loose.
- Always tell the person:
  1. It is a model, not a recording.
  2. What fails and when, from the "Predicted:" or "What-if" line.
  3. The "Main assumption:" line, in plain words.
- The video is fail.mp4. Look at fail_sheet.png before you describe it: the first 2 frames are
  the normal print, the rest are the failure.
- The words: supports = lines print into air and fall (spaghetti). droop = an edge sags down.
  bridge = a long bridge sags. detach = the part comes loose and slides. topple = it tips over.
- Then run the NEXT line it printed.

## Example
Request: What happens if I print the T without supports?
stone timelapse t.stl --supports off --fail ->
  This is a model, not a recording: failsim's physics on stone's own toolpaths.
  Predicted: supports at layer 21 (z 4.2 mm, 22 s in): lines with nothing under them print into
  air and fall (spaghetti).
  Why: ledge 12.0 mm past the layer below droops 11.654 mm.
  Main assumption: Droop of one layer fails the ledge; half a layer is the smallest droop that
  shows. (failsim.droop_rule)
  Video: .../fail.mp4 (33 frames, 4.0 s; frames from layer 21 on are the model)
  Sheet: .../fail_sheet.png
  Data: .../fail.json (11 s)
  NEXT: none, the failure video is made
Reply: Here is a model of it (fail.mp4), not a real recording. Without supports, the arms of the
T start at layer 21 (4.2 mm up) with nothing under them. Those lines fall to the bed and pile up
as spaghetti. Print it with supports on, or turn it upside down.

Request: My plate was dirty. Show me the plate coming loose.
stone timelapse plate.stl --fail --plate dirty ->
  Predicted: detach at layer 1 (z 0.2 mm, 2 min 26 s in): the part comes loose from the plate;
  later layers print into air.
  Why: edge pull 2.69 MPa against a plate bond of 1.11 MPa (margin 0.41).
  Main assumption: A contaminated plate keeps the same fraction of its hold as PP keeps of
  PLA's on a clean plate. (failsim.contamination)
Reply: In the model, a dirty plate lets go after the first layer. The edges pull harder (2.7 MPa)
than the plate holds (1.1 MPa). Then the plastic lands in loose strands and a blob grows on the
nozzle. Clean the plate with soap and water and it holds (the model gives it 2.4 times the pull).
