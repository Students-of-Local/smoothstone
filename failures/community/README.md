# Shared print fixes

Each folder here is one print problem a person fixed with `stone doctor` and chose to share.
`stone doctor share` never uploads anything: it scrubs the case, shows the person every word and the
photo, and prints a prefilled link to a print-fix issue. The person attaches the photo and submits the
issue on GitHub themselves. A maintainer reads the issue and adds the folder (`case.json` plus
`photo.jpg`) here in a pull request. stone doctor reads every `*/case.json` when it loads: on the same printer
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

The sender agrees, in the prompt stone shows and again in the issue form's checkbox, that the photo
and text are shared under this repository's MIT license.

## How maintainers merge

1. Read the print-fix issue. Look at the photo: it shows the failure, no faces, no screens with
   accounts, nothing private. Check the cause fits what was seen and what fixed it. If it does not,
   comment and close.
2. Add the folder in a pull request: save the photo as `photo.jpg` with no EXIF at most 1024 px,
   write `case.json` from the issue's fields, and link the issue.
3. CI runs `tests/test_community.py` on the pull request: schema, ids, photo size, EXIF, private data.
4. Merge.
