#!/bin/bash
# Longer search horizons over the expert-1b policy, F opponents, 800 games each.
# 8t24 vs 8t16; if 8t24 takes at least 53% of the pair's wins, 8t32 vs 8t24.
# Keeps the machine awake for the duration.
E=champions/robber-expert-1b.pt
FLAG=runs/logs/keep_awake.flag
touch $FLAG
powershell -NoProfile -ExecutionPolicy Bypass -File runs/logs/keep_awake.ps1 -Flag "$(cygpath -w "$PWD/$FLAG")" &
trap 'rm -f $FLAG' EXIT
run() {  # candidate baseline
  uv run python -m catan_ai.cli.compare --candidate search:$1:model:$E --baseline search:$2:model:$E \
    --opponents catanatron:F,catanatron:F --label search-$1-vs-$2-expert-1b-F --workers 10 > runs/logs/h_$1.log 2>&1
  echo "$1 vs $2: $(grep 'candidate share' runs/logs/h_$1.log) $(date '+%a %H:%M')"
}
echo "start $(date '+%a %H:%M')"
run 8t24 8t16
SHARE=$(grep -o 'candidate share [0-9.]*' runs/logs/h_8t24.log | awk '{print $3}')
if awk "BEGIN{exit !($SHARE >= 0.53)}"; then run 8t32 8t24; else echo "8t24 not ahead; stopping"; fi
