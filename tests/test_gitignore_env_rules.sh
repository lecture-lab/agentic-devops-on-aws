#!/usr/bin/env bash
# Focused test for reviewer A2: proves .env and .env.local are ignored,
# and .env.example is NOT ignored (i.e. actually tracked). A prose claim
# isn't evidence -- this is.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

fail=0

assert_ignored() {
  if git check-ignore -q "$1"; then
    echo "OK: $1 is ignored"
  else
    echo "FAIL: $1 is NOT ignored (expected it to be)"
    fail=1
  fi
}

assert_not_ignored() {
  if git check-ignore -q "$1"; then
    echo "FAIL: $1 IS ignored (expected it to be tracked)"
    fail=1
  else
    echo "OK: $1 is not ignored"
  fi
}

assert_ignored ".env"
assert_ignored ".env.local"
assert_ignored ".env.production"
assert_not_ignored ".env.example"

if [ "$fail" -ne 0 ]; then
  echo "gitignore env-rule test FAILED"
  exit 1
fi
echo "gitignore env-rule test PASSED"
