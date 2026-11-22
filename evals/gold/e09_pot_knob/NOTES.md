Reference design by GPT-6.1 Sol, smoothstone gold set. Copied as made.

# Bourns PTV09A replacement knob

A PLA friction knob for the 6.0 mm maximum diameter, 7.0 mm long S-type knurl in the spec. The body is 18 mm in diameter and 10 mm high, a compact size that gives a finger grip and room for a separate compliant socket. The shallow side groove is an index mark. The spec does not give the knurl tooth depth or a mating spline, so the socket is round and relies on contact with the printed surface. Retention and torque have not been measured on a real shaft.

## Fit and structure

The cylindrical press band is 5.88 mm diameter from STL z=7.9 to z=9.6 mm. Relative to the specified 5.90 to 6.00 mm shaft diameter, its nominal diametral interference is 0.02 to 0.12 mm, or 0.01 to 0.06 mm radially. Printed dimensions and the actual knurl shape change this fit; calibrate the bore on the intended printer. The modeled shaft starts at STL z=10 and its tip is at z=3. The tip has 0.8 mm clearance to the bore floor at z=2.2. This places the start of the knurl at the entry, leaving the plain shaft outside the knob. The entry lead is 0.4 mm long and expands 0.15 mm radially for insertion.

Four 0.6 mm axial slots and a 0.8 mm annular relief divide the socket into four compliant fingers. They are rooted in the common 2.2 mm face. The relief begins at z=2.5 and ends at z=10. Their 4.44 mm outer radius gives 1.50 mm radial thickness at the press band. At z=2.51 mm, radial thickness is 1.420 mm; at z=9.99 mm, it is 1.354 mm. The lead's nominal mouth wall is 1.35 mm radially, or approximately 1.35/sqrt(1+0.375^2) = 1.26 mm normal to the lead before facet effects. The outer shell is 3.76 mm radially outside the annular relief; the index groove cuts 0.35 mm at the outermost radius. The 0.7 mm external chamfers ease the edges. The 144 circumferential facets keep the bore within 0.001 mm of the nominal radius, and 54 steps approximate the gradual axial relief.

The bore between z=2.5 and 7.9 starts at radius 3.02 mm and closes to 2.94 mm. Its axial profile uses f(u)=u^2(3-u)/2, with u=(z-2.5)/5.4. This is the displacement shape of an ideal end-loaded cantilever. For the maximum 3.00 mm shaft radius, the radial displacement required at each station is max(0, 0.08 f(u) - 0.02), which does not exceed 0.06 f(u). Thus the nominal shaft does not force the full press displacement at the root. This comparison uses the nominal smooth envelope, not the unknown knurl roots.

For a preliminary conservative beam estimate, take the maximum 0.06 mm radial deflection, t=1.5 mm, and L=5.4 mm from root to the beginning of the press band. A rectangular fixed-guided beam under imposed tip displacement has maximum strain 3 y t / L^2 = 3 x 0.06 x 1.5 / 5.4^2 = 0.00926, or 0.926%. Doubling it for the spec's safety factor gives 1.852%, below the grader's 2% PLA snap strain reference. This is an idealized comparison, not a measured or proven strain bound for the curved, slotted fingers with a changing section, distributed contact, and unfilleted roots. Stress concentration, printed anisotropy, creep, knurl cutting, and assembly force remain unverified. The previous tip-loaded calculation was replaced because a straight bore also loaded the fingers near their roots. The grader evaluates this part as friction retention, not as a snap. Physical fitting and mechanical validation are needed to establish retention and service life.

The engineering declaration records -0.03 mm on the four sides as the grader's rounded median across the varying profile, and -0.06 mm as the cylindrical band's designed maximum radial interference. These values describe different measurements. The spec's 0.0 to 1.0 mm end-face gap is independent of the side fit.

## Print and checks

Print in STL orientation, flat closed face down and bore upward. The relief and slots grow vertically from the face; the gradual bore transition is approximately 0.015 mm radial change per millimeter of height, and the lead opens toward the top. The design assumes PLA, a 0.4 mm nozzle and 0.2 mm layers for the geometric slicer check. The 0.6 mm slots target clearance larger than one nominal line. Actual nozzle, profile, adhesion, slicer preview and physical print remain unverified. The geometric slicer reports 2.4 mm2 total dropped area distributed over layers and no problems. This check is not a production slicer preview.

The final STL is a single watertight component, 18 x 18 x 10 mm, 17,744 triangles, zero degenerate triangles, zero boundary edges and zero nonmanifold edges. The grader reports a sampled minimum wall of 1.42 mm; this statistic is not a guaranteed absolute minimum. Its 418 fit samples show median -0.03 mm on each side, 0.80 mm at the tip, 100% covered on each required face, and 0% blocked on the open face. A separate denser radial sweep of 100,800 side samples measured 90.56% coverage on each side using the grader's 1.05 mm reach; the slots account for the open portions. The detailed mesh and slicer results are in `build/measurements.json` and the dense sweep in `build/dense-coverage.json`.

An independent final audit reused the grader's surface sampler at 0.15 mm pitch and its signed-gap method, producing 8,544 samples. It measured 87.5% coverage on every side, above the 80% requirement, with median side gaps of -0.015 mm, a 0.800 mm tip gap, and no blockage of the open face. The different coverage results reflect the sampling and gap methods; the coarse grader's 100% result does not mean the slots are closed. This audit also confirmed one manifold component and a 1.420 mm radial root wall. Its results are in `build/independent-check.json`. Final OpenSCAD renders were inspected from the bore and closed-face sides, saved as `build/verified-bore.png` and `build/verified-face.png`.

Final command:

```text
uv run python gold/grade.py evals/engineering/e09_pot_knob.json gold/e09_pot_knob
{
 "pass": true,
 "why": []
}
```
