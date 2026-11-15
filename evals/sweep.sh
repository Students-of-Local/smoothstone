#!/bin/sh
# evals/sweep.sh <spec dir> <out dir> [seeds]: every spec x condition x seed, 4 at a time
set -eu
dir=$1; out=$2; seeds=${3:-"1 2 3 4 5"}
for spec in "$dir"/*.json; do for seed in $seeds; do
  echo "$spec --seed $seed --card none"
  echo "$spec --seed $seed --card S"
  echo "$spec --seed $seed --card S --compact-at 3"
done; done | xargs -P4 -I{} sh -c "uv run python evals/run.py {} --out $out > /dev/null 2>&1 || echo FAILED {}"
uv run python evals/summary.py "$out"
