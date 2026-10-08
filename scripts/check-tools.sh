#!/usr/bin/env bash
# Section 1: confirm the toolchain is ready before we ask an Agent to touch AWS.
set -euo pipefail

# TF_BIN=tofu if you use OpenTofu instead of HashiCorp Terraform.
TF_BIN="${TF_BIN:-terraform}"

missing=0

check() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    echo "✓ $name: $("$name" --version 2>&1 | head -n1 | cut -c1-80)"
  else
    echo "✗ $name: not found"
    missing=1
  fi
}

# Optional tools only warn; they never make the script fail.
check_optional() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    echo "✓ $name (optional): $("$name" --version 2>&1 | head -n1 | cut -c1-80)"
  else
    echo "! $name (optional): not found -- nice to have, not required"
  fi
}

check git
check "$TF_BIN"
check aws
check python3
check curl
check claude
check_optional tree

# Python scripts in this repository use type hints such as list[str].
if command -v python3 >/dev/null 2>&1 && ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "✗ python3 is older than 3.9: the scripts in this repository need Python 3.9 or newer."
  missing=1
fi

if [ "$TF_BIN" = "terraform" ] && ! command -v terraform >/dev/null 2>&1 && command -v tofu >/dev/null 2>&1; then
  echo "  note: 'tofu' was found. Run the scripts with TF_BIN=tofu (for example: TF_BIN=tofu ./scripts/validate.sh)."
fi

if [ "$missing" -ne 0 ]; then
  echo
  echo "One or more required tools are missing. Install them before continuing."
  exit 1
fi

echo
echo "All required tools are present."

# Hints only: nothing below changes the exit code, and nothing below calls AWS
# (so no account ID is ever printed by this script).
echo
echo "AWS profile hint:"
if [ -n "${AWS_PROFILE:-}" ]; then
  echo "  AWS_PROFILE is set to '$AWS_PROFILE'."
else
  echo "  AWS_PROFILE is not set. The course uses a profile named 'agentic-devops':"
  echo "    export AWS_PROFILE=agentic-devops"
fi
profiles="$(aws configure list-profiles 2>/dev/null || true)"
case $'\n'"$profiles"$'\n' in
  *$'\n'agentic-devops$'\n'*) echo "  Profile 'agentic-devops' exists." ;;
  *)
    echo "  No profile named 'agentic-devops' was found yet. Create it as described"
    echo "  in the environment setup guide, then check it with:"
    echo "    aws sts get-caller-identity --profile agentic-devops"
    echo "  (that output contains your account ID -- never share it or screenshot it)."
    ;;
esac
