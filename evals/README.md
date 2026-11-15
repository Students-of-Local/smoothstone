# Evals

Each spec is a request a person would type, an optional picture, and what a passing part must
have. A run passes when the model reached `stone done`, the final part passes `stone check`, the
recipe matches, and every expected parameter is in range (`[lo, hi]` is inclusive, a plain value
must match, `sum` adds parameters, `image_used` means that image parameter was set).

- `tuning/`: specs used while improving the skill and the tool. Their results inform changes.
- `heldout/`: written and sealed before any tuning run (SHA-256 in ../LOG.md and in the
  lfm3-3d-skill LOG.md). They run once, after the skill and tool are frozen.
