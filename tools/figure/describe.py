"""Describe how a person, animal or object looks, in one sentence, with a small local vision model.

python tools/figure/describe.py <photo> <person|animal|object> <model_dir>
python tools/figure/describe.py --traits <person|animal> <model_dir> <image> [<image> ...]

Prints only the sentence. With --traits it prints one JSON line instead: for each image, yes or no
(true or false) to the questions in TRAITS, so a render can be checked against the photo. Runs in the style venv (mlx-vlm), about 3 GB peak on Apple silicon.
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


TRAITS = {
    "person": {
        "face": "Is a human face visible in this picture? Answer yes or no.",
        "glasses": "Is the person wearing glasses? Answer yes or no.",
        "beard": "Does the person have a beard or a mustache? Answer yes or no.",
        "hat": "Is the person wearing a hat, a cap or a helmet? Answer yes or no.",
    },
    "animal": {
        "face": "Is an animal's face visible in this picture? Answer yes or no.",
    },
}


def traits(who: str, model: str, images: list[str]) -> int:
    import json

    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template

    m, proc = load(model)
    out = []
    for image in images:
        got = {}
        for key, ask in TRAITS[who].items():
            prompt = apply_chat_template(proc, m.config, ask, num_images=1)
            text = generate(m, proc, prompt, [image], max_tokens=3, temperature=0.0, verbose=False)
            got[key] = str(getattr(text, "text", text)).strip().lower().startswith("yes")
        out.append(got)
    print(json.dumps(out))
    return 0


def main() -> int:
    if sys.argv[1] == "--traits":
        return traits(sys.argv[2], sys.argv[3], sys.argv[4:])
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
