#!/usr/bin/env bash
set -euo pipefail

# All generated writers use the shared concurrency group. Keep the explicit
# ref here so a detached Actions checkout can publish to the operational branch
# without ever updating main.
git push origin HEAD:ops
