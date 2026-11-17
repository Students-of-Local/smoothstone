"""Describe how a person, animal or object looks, in one sentence, with a small local vision model.

python tools/figure/describe.py <photo> <person|animal|object> <model_dir>

Prints only the sentence. Runs in the style venv (mlx-vlm), about 3 GB peak on Apple silicon.
The style model keeps a likeness far better when this sentence is in its prompt.
"""
from __future__ import annotations

import sys

ASK = {
    "person": ("Describe only how this person looks, for a sculptor, in one sentence: hair color and "
               "style, glasses frame shape and color if any, facial hair, apparent age and ethnicity, "
               "and the clothes on the upper body with their color and material. No expression, no "
               "background."),
    "animal": ("Describe only how this animal looks, for a sculptor, in one sentence: species and "
               "breed, fur or feather colors and markings, ear and tail shape, expression. No background."),
    "object": ("Describe only this object, for a sculptor, in one sentence: what it is, its overall "
               "shape and proportions, colors, materials and distinctive details. No background."),
}


def main() -> int:
    photo, who, model = sys.argv[1], sys.argv[2], sys.argv[3]
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template

    m, proc = load(model)
    prompt = apply_chat_template(proc, m.config, ASK.get(who, ASK["object"]), num_images=1)
    out = generate(m, proc, prompt, [photo], max_tokens=120, temperature=0.0, verbose=False)
    text = getattr(out, "text", out)
    print(" ".join(str(text).split()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
