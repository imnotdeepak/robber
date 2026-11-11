#!/bin/bash
# Opponent-model headroom: rollouts that play the other seats as ValueFunction (the true policy of
# the two F seats; the baseline Robber seat is mismodelled, so this understates the headroom)
# against ordinary self-play rollouts, both 4t8 over expert-1b, F opponents, 800 games.
E=champions/robber-expert-1b.pt
FLAG=runs/logs/keep_awake.flag
touch $FLAG
powershell -NoProfile -ExecutionPolicy Bypass -File runs/logs/keep_awake.ps1 -Flag "$(cygpath -w "$PWD/$FLAG")" &
trap 'rm -f $FLAG' EXIT
echo "start $(date '+%a %H:%M')"
uv run python -m catan_ai.cli.compare --candidate search:4t8-F:model:$E --baseline search:4t8:model:$E \
  --opponents catanatron:F,catanatron:F --label search-4t8-oppF-vs-4t8-expert-1b-F --workers 10 > runs/logs/oppF.log 2>&1
echo "4t8-F vs 4t8: $(grep 'candidate share' runs/logs/oppF.log) $(date '+%a %H:%M')"
