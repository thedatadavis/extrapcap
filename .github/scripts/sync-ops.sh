#!/usr/bin/env bash
set -euo pipefail

# The workflow is checked out from ops so generated jobs share one runtime
# state. Pull source changes from main before running the job; generated paths
# are owned by ops and must not be edited by normal code changes. Because main
# intentionally does not contain generated files, restore the current ops tree
# after the merge so source synchronization cannot delete runtime state.
git fetch origin main ops || true
git config user.name extrapcap-bot
git config user.email extrapcap-bot@users.noreply.github.com

before_merge=$(git rev-parse HEAD)
if git merge-base --is-ancestor origin/main HEAD; then
  exit 0
fi

# Merge main into ops using -X ours to automatically resolve hunk-level conflicts in favor of ops state.
# If structural conflicts occur, restore code/config files from main and operational paths from ops.
if ! git merge --no-edit --no-ff --no-commit -X ours origin/main 2>/dev/null; then
  git checkout origin/main -- . 2>/dev/null || true
  git checkout "$before_merge" -- logs reports data models 2>/dev/null || true
  git add -A
else
  git checkout "$before_merge" -- logs reports data models 2>/dev/null || true
  git add -A
fi

if git rev-parse -q --verify MERGE_HEAD >/dev/null; then
  git commit --no-edit -m "merge: sync source changes from main into ops"
elif ! git diff --cached --quiet; then
  git commit -m "merge: sync source changes from main into ops"
fi

