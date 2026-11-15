#!/bin/bash
# usage: deliver.sh <trial> <sha> <delivered_at>
set -e
cd "$(dirname "$0")"
n=$(python3 -c "import json;print(len(json.load(open('trials.json'))['trials']['$1']['rounds']))")
python3 score_round.py "$1" "$2" "$3" > "runs/$1_r$n.txt" || true
head -2 "runs/$1_r$n.txt"
if grep -q "reviewer message" "runs/$1_r$n.txt"; then
  sed -n '/reviewer message/,$p' "runs/$1_r$n.txt" | tail -n +2 > "runs/$1_feedback$((n+1)).md"
  echo "feedback: runs/$1_feedback$((n+1)).md ($(grep -c '^- ' runs/$1_feedback$((n+1)).md) notes)"
fi
