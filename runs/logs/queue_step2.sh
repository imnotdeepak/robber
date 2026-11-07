#!/bin/bash
# Confirm expert-1b at AB:2 + F on fresh boards, then the bigger-search queue.
uv run python -m catan_ai.cli.compare --candidate model:checkpoints/expert-1b/best.pt \
  --baseline model:champions/robber-ppo3-r60.pt --opponents catanatron:AB:2,catanatron:F \
  --seed 510000 --label expert-1b-vs-robber-AB-F-2 --workers 10 > runs/logs/expert1b_cmp_ABF2.log 2>&1
echo "1b AB+F confirm: $(grep 'candidate share' runs/logs/expert1b_cmp_ABF2.log) $(date +%H:%M)"
bash runs/logs/queue_bigsearch.sh
