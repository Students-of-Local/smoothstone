# Failure photo gallery

Real photos of 3D print failures, each labeled with one id from the failure taxonomy
(`src/smoothstone/failures/taxonomy.json`), so an agent can set a person's photo beside known cases of
the same failure. A smaller set of frames labeled `healthy` shows prints going fine, for contrast.

- `<failure id>/<slug>.jpg`: the photo, at most 768 px on its long side, JPEG quality 85, no EXIF or GPS.
- `labels.jsonl`: one line per photo with `file`, `failure`, `also` (other ids visible in the same
  photo), `printer`, `material`, `title`, `source`, `license`, `author`, `url`, `note` (one line on what
  is visible) and `synthetic` (true for rendered frames, which are not photos).
- `CREDITS.md`: attribution for every photo, generated from `labels.jsonl`.

`printer` uses a smoothstone printer id (such as `creality_k2` or `bambu_a1_mini`) when the source
names that exact printer, and the source's own words otherwise. `null` means the source did not say.

A label says what the photo shows, read together with the source's title and description or the
accepted answer. It does not claim the cause. When a note names a fix, it is the source's fix.

## Add a photo

1. Check the license on the source page yourself. The gallery takes only the licenses in
   `LICENSES` in `tools/gallery_credits.py`: CC0, public domain, CC BY 2.0 to 4.0, CC BY-SA 2.0 to 4.0,
   and MIT for photos the owner shares under this repository's license. No NC, no ND, nothing
   without a stated license.
2. Look at the photo. Keep it only when the failure is plain to see and the label is clear from the
   picture and its source. If two ids fit equally, leave it out.
3. Add it:

   ```sh
   uv run python tools/gallery_add.py photo.jpg --failure stringing --slug benchy-hairs \
       --license "CC BY 2.0" --author "Jane Doe" --url https://www.flickr.com/photos/... \
       --title "Stringy benchy" --source "Flickr" --note "fine hairs span the gap between the two towers"
   ```

   It resizes the photo, strips its metadata, appends the label and rewrites `CREDITS.md`.
4. Check the labels by eye with `uv run python tools/gallery_sheet.py [ID ...]`, which writes one
   contact sheet per id to `/tmp/gallery-sheets`, then run `uv run pytest -q tests/test_gallery.py`.

## License

Each photo keeps its own license, listed in `labels.jsonl` and `CREDITS.md`; the repository's MIT
license does not cover photos under CC licenses. CC BY-SA photos stay under CC BY-SA. The only change
made to any photo is the resize and re-save described above.
