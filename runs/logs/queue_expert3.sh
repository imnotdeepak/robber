#!/bin/bash
# Expert iteration cycle 3 (teacher search 8t16 over expert-1b), then the student without search
# against expert-1b at AB:2 + F and W/VP. Keeps the machine awake for the duration.
E=champions/robber-expert-1b.pt
FLAG=runs/logs/keep_awake.flag
touch $FLAG
powershell -NoProfile -ExecutionPolicy Bypass -File runs/logs/keep_awake.ps1 -Flag "$(cygpath -w "$PWD/$FLAG")" &
trap 'rm -f $FLAG' EXIT
echo "start $(date '+%a %H:%M')"
uv run python -m catan_ai.cli.imitation_data --config configs/expert_3.json --workers 10 \
  --feature-version 3 > runs/logs/expert3_data.log 2>&1 || { echo "data failed"; exit 1; }
echo "data done $(date '+%a %H:%M')"
uv run python -m catan_ai.cli.train_imitation --config configs/expert_3.json \
  --report reports/expert_3_training.md > runs/logs/expert3_train.log 2>&1 || { echo "train failed"; exit 1; }
echo "train done $(date '+%a %H:%M')"
for O in "catanatron:AB:2,catanatron:F AB-F" "catanatron:W,catanatron:VP WVP"; do set -- $O
  uv run python -m catan_ai.cli.compare --candidate model:checkpoints/expert-3/best.pt --baseline model:$E \
    --opponents $1 --label expert-3-vs-expert-1b-$2 --workers 10 > runs/logs/expert3_cmp_$2.log 2>&1
  echo "$2: $(grep 'candidate share' runs/logs/expert3_cmp_$2.log) $(date '+%a %H:%M')"
done
