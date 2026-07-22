#!/usr/bin/env bash
set -euo pipefail

# The workflow is checked out from ops so generated jobs share one runtime
# state. Pull source changes from main before running the job; generated paths
# are owned by ops and must not be edited by normal code changes. Because main
# intentionally does not contain generated files, restore the current ops tree
# after the merge so source synchronization cannot delete runtime state.
git fetch origin main

before_merge=$(git rev-parse HEAD)
if git merge-base --is-ancestor origin/main HEAD; then
  exit 0
fi

git merge --no-edit --no-ff --no-commit origin/main
git checkout "$before_merge" -- logs reports data models
git commit --no-edit
