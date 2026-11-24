# Shared print fixes

Each folder here is one print problem a person fixed with `stone doctor` and chose to share with
`stone doctor share --send`. stone doctor reads every `*/case.json` when it loads: on the same printer
model, the causes that fixed a failure rank higher next time (at most 3x, Laplace smoothed), and once
two or more cases agree it prints "On <printer>, N of M shared <failure> cases were fixed by <cause>".
Photos also show as examples of their failure.

## What is accepted

- One folder per case, named `<yyyy-mm-dd>-<printer id>-<failure id>-<short hash>/`, holding
  `case.json` and, if there was one, `photo.jpg`.
- `failure` is a taxonomy id from `src/smoothstone/failures/catalog.json`, `cause` one of that
  failure's cause ids, `printer` an id from `src/smoothstone/printers/`.
- The photo is a JPEG at most 1024 px on its long side with no EXIF (stone strips it).
- No home paths, user names, host names, IP or MAC addresses, serials, emails or the printer's own
  name: stone scrubs these before it shows the bundle, and `tests/test_community.py` fails on any left.
- The fix worked for the sender. One case is one person's report, not a proof.

## License

The sender agrees, in the prompt stone shows before anything is sent, that the photo and text are
shared under this repository's MIT license.

## How maintainers merge

1. CI runs `tests/test_community.py` on the pull request: schema, ids, photo size, EXIF, private data.
2. Look at the photo: it shows the failure, no faces, no screens with accounts, nothing private.
3. Check the cause fits what was seen and what fixed it. If it does not, comment and close.
4. Merge. An issue from the print-fix template (sent without gh) becomes a case the same way: a
   maintainer saves the photo with no EXIF at most 1024 px, writes `case.json`, and opens the PR.
