"""Download a Hugging Face repo with many parallel range requests.

python tools/figure/fetch.py <repo_id> <dest_dir> [--conn 48]

Some links cap each connection at a few hundred KB/s; many ranges at once fill the line.
Each file is checked against the size the Hub reports. Files already complete are skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CHUNK = 16 * 1024 * 1024
AGENT = "smoothstone-fetch/0.1"


def files(repo: str) -> list[tuple[str, int]]:
    url = f"https://huggingface.co/api/models/{repo}/tree/main?recursive=true"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=60) as r:
        return [(f["path"], int(f["size"])) for f in json.load(r) if f["type"] == "file"]


def get_range(url: str, start: int, end: int, tries: int = 8) -> bytes:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) == end - start + 1:
                return data
        except Exception:
            pass
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"range {start}-{end} of {url} failed")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("dest")
    ap.add_argument("--conn", type=int, default=48)
    a = ap.parse_args()
    dest = Path(a.dest)
    todo = [(p, s) for p, s in files(a.repo)
            if not ((dest / p).exists() and (dest / p).stat().st_size == s)]
    total = sum(s for _, s in todo)
    done = [0]
    lock = threading.Lock()
    t0 = time.time()
    pool = ThreadPoolExecutor(a.conn)
    for path, size in todo:
        url = f"https://huggingface.co/{a.repo}/resolve/main/{path}"
        out = dest / path
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_name(out.name + ".part")
        with open(part, "wb") as f:
            f.truncate(size)

        def job(start, url=url, part=part, size=size):
            end = min(start + CHUNK, size) - 1
            data = get_range(url, start, end)
            fd = os.open(part, os.O_WRONLY)
            try:
                os.pwrite(fd, data, start)
            finally:
                os.close(fd)
            with lock:
                done[0] += len(data)
                mb = done[0] / 1e6
                print(f"\r{mb:,.0f} / {total / 1e6:,.0f} MB  {mb / (time.time() - t0):.1f} MB/s",
                      end="", file=sys.stderr, flush=True)

        list(pool.map(job, range(0, max(size, 1), CHUNK))) if size else None
        part.rename(out)
    print(f"\ndone: {len(todo)} files, {total / 1e9:.2f} GB in {time.time() - t0:.0f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
