#!/usr/bin/env bash
set -euo pipefail

# The workflow is checked out from ops so generated jobs share one runtime
# state. Pull source changes from main before running the job; generated paths
# are owned by ops and must not be edited by normal code changes.
git fetch origin main
git merge --no-edit origin/main
