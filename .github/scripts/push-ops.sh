#!/usr/bin/env bash
set -euo pipefail

git config user.name extrapcap-bot 2>/dev/null || true
git config user.email extrapcap-bot@users.noreply.github.com 2>/dev/null || true

MAX_RETRIES=5
for ((i=1; i<=MAX_RETRIES; i++)); do
  if git push origin HEAD:ops; then
    exit 0
  fi
  echo "Push to ops failed (attempt $i/$MAX_RETRIES). Fetching origin/ops and rebasing/merging..."
  git fetch origin ops
  if ! git rebase origin/ops; then
    git rebase --abort || true
    if ! git merge --no-edit -X ours origin/ops 2>/dev/null; then
      git checkout HEAD -- logs reports data models 2>/dev/null || true
      git checkout --ours -- . 2>/dev/null || true
      git add -A
      git diff --cached --quiet || git commit --no-edit -m "merge: resolve push conflict with origin/ops"
    fi
  fi
  sleep 1
done

git push origin HEAD:ops

