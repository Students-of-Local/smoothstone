# Direction

The owner's standing direction for smoothstone. Every recipe, eval and pull request is checked against it.

Donovan Baney, 2026-11-22, in his words:

> REMEMBER smoothstone and GANTREL are to be to better and they need to integrate very well and easily with things such as Creality CLI and other openstandards for connecting to 3D printers, and later other types of engineering devices, as gantrel is also for product design I want to be able to design my products in it, of course I will be using larger models, but over time we will "distill" through skills so lesser models can learn how to do said things too, and generalize widely and when I mean small I mean
>
> - 1.7B-31B for
> - then up and higher and that
>
> Unto caesar will work in a similar way one can use their sub but the goal is that eventually it will get so Good that local models can easily do taxes for people revolutionizing and helping the world, and I mean the world, write down what I have writted of course yet, ensure this will be done to a high standard


And in the next message:

> It needs an MCP to act with grokbot, and again will have a waitlist for tunnels unless they use dev mode and use their own
> as we will need to either charge or negotiate with them

## What it means for smoothstone

### 1. Keep getting better

- More recipes, better looking parts, and every part passes the print checks. The ratchet in `evals/` only moves up ([AGENTS.md](../AGENTS.md)).

### 2. Integrate very well and easily

- Parts open in the slicers people use, with nothing to fix by hand: Creality Print, OrcaSlicer, Bambu Studio and PrusaSlicer, as STL and as 3MF with color.
- smoothstone is the part maker inside [Gantrel](https://github.com/baney75/Gantrel), which sends parts to printers through Creality's tools and the open printer standards. A change to `stone`'s output is checked against what Gantrel reads.

### 3. Distill through skills to small models

- Larger models show what is possible. Their good runs become recipes, typed parameters and reference facts in the skill, so smaller models make the same parts.
- Small means 1.7B to 31B parameters, with larger models above that. LFM3-1.7B is the floor today. Every tier is benchmarked ([DESIGN.md](DESIGN.md), Evaluation), and "generalize widely" means passing held-out requests the skill was never tuned on.

### 4. An MCP server for Grok Bot

- `stone` is reachable over MCP so Grok Bot, and any assistant that speaks MCP, can make a part with it, directly or through Gantrel's server.
- Reaching it from away from home follows Local Studio's tunnel rule ([local-studio docs/tunnel.md](https://github.com/baney75/local-studio/blob/main/docs/tunnel.md)): hosted tunnels are waitlist-only, because running them costs money and Donovan will either charge for them or negotiate with the provider. Anyone on the dev channel can use their own tunnel today (their own Cloudflare account or Tailscale).
- A server reached through a tunnel needs auth on every path and the public-tools consent ([local-studio#13](https://github.com/baney75/local-studio/issues/13)).

### 5. A high standard

- No claim without a passing build and print check. A fault the owner reports gets a regression spec in `evals/regressions/` that fails before the fix.

Progress is tracked in the "Direction" issue on this repository.
