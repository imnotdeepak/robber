#!/bin/bash
# Search over the expert-1b policy vs the search champion at equal budget, then expert iteration cycle 2.
V=champions/robber-ppo3-r60-value-ppo3.pt
E=champions/robber-expert-1b.pt
uv run python -m catan_ai.cli.compare --candidate search:4t8:model:$E --baseline search:4t8:model:$V \
  --opponents catanatron:F,catanatron:F --label search-4t8-expert-1b-vs-value-ppo3-F --workers 10 > runs/logs/s_e1b.log 2>&1
echo "search e1b vs vppo3: $(grep 'candidate share' runs/logs/s_e1b.log) $(date +%H:%M)"
uv run python -m catan_ai.cli.imitation_data --config configs/expert_2.json --workers 10 \
  --feature-version 3 > runs/logs/expert2_data.log 2>&1 || { echo "data failed"; exit 1; }
echo "data done $(date +%H:%M)"
uv run python -m catan_ai.cli.train_imitation --config configs/expert_2.json \
  --report reports/expert_2_training.md > runs/logs/expert2_train.log 2>&1 || { echo "train failed"; exit 1; }
echo "train done $(date +%H:%M)"
for O in "catanatron:AB:2,catanatron:F AB-F" "catanatron:W,catanatron:VP WVP"; do set -- $O
  uv run python -m catan_ai.cli.compare --candidate model:checkpoints/expert-2/best.pt --baseline model:$E \
    --opponents $1 --label expert-2-vs-expert-1b-$2 --workers 10 > runs/logs/expert2_cmp_$2.log 2>&1
  echo "$2: $(grep 'candidate share' runs/logs/expert2_cmp_$2.log) $(date +%H:%M)"
done
