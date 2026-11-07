#!/bin/bash
# Expert iteration cycle 1b: sharper retraining on the expert-1 data, then the student without search
# against the plain champion at an AB:2 + F table and a W/VP table.
M=champions/robber-ppo3-r60.pt
E=checkpoints/expert-1b/best.pt
uv run python -m catan_ai.cli.train_imitation --config configs/expert_1b.json --data data/expert-1 \
  --report reports/expert_1b_training.md > runs/logs/expert1b_train.log 2>&1 || { echo "train failed"; exit 1; }
echo "train done $(date +%H:%M)"
uv run python -m catan_ai.cli.compare --candidate model:$E --baseline model:$M \
  --opponents catanatron:AB:2,catanatron:F --label expert-1b-vs-robber-AB-F --workers 10 > runs/logs/expert1b_cmp_ABF.log 2>&1
echo "AB+F: $(grep 'candidate share' runs/logs/expert1b_cmp_ABF.log) $(date +%H:%M)"
uv run python -m catan_ai.cli.compare --candidate model:$E --baseline model:$M \
  --label expert-1b-vs-robber --workers 10 > runs/logs/expert1b_cmp.log 2>&1
echo "W/VP: $(grep 'candidate share' runs/logs/expert1b_cmp.log) $(date +%H:%M)"
