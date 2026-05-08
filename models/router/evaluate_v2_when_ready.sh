#!/bin/bash
# Auto-evaluate v2 model when training completes
LOG="/home/mike/lucy-v8/models/router/train_v2.log"
CHECKPOINT="/home/mike/lucy-v8/models/router/checkpoints/best"

echo "Waiting for V2 training to complete..."
while ! grep -q "Training complete" "$LOG" 2>/dev/null; do
    sleep 60
done

echo "Training complete! Evaluating..."
cd /home/mike/lucy-v8/models/router
python3 evaluate_model.py --checkpoint "$CHECKPOINT" --config config.yaml > v2_evaluation.txt 2>&1
echo "Evaluation saved to v2_evaluation.txt"
