#!/bin/bash
# Bigger search budgets (colonist.io allows one minute per turn): each budget against the
# 4t8 search champion, F opponents, 800 games on the standard compare boards.
V=champions/robber-ppo3-r60-value-ppo3.pt
for B in 16t8 8t16; do
  uv run python -m catan_ai.cli.compare --candidate search:$B:model:$V --baseline search:4t8:model:$V \
    --opponents catanatron:F,catanatron:F --label search-$B-vs-4t8-F --workers 10 > runs/logs/big_$B.log 2>&1
  echo "$B: $(grep 'candidate share' runs/logs/big_$B.log) $(date +%H:%M)"
done
