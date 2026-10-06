#!/usr/bin/env bash
# One-time setup after cloning: turns on the tracked pre-commit secret scan.
# `git config core.hooksPath` is local config and is NOT copied by `git clone`,
# so a fresh clone has no hook until this runs. Safe to re-run.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
python3 scripts/secret-scan.py --self-test
echo "OK: core.hooksPath=$(git config core.hooksPath) -- commits are now scanned by scripts/secret-scan.py --staged"
