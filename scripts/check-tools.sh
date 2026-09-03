#!/usr/bin/env bash
# Section 1: confirm the toolchain is ready before we ask an Agent to touch AWS.
set -euo pipefail

missing=0

check() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    echo "✓ $name: $("$name" --version 2>&1 | head -n1)"
  else
    echo "✗ $name: not found"
    missing=1
  fi
}

check git
check terraform
check aws
check python3

if [ "$missing" -ne 0 ]; then
  echo
  echo "One or more required tools are missing. Install them before continuing."
  exit 1
fi

echo
echo "All required tools are present."
