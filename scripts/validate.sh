#!/usr/bin/env bash
# Run this before every terraform plan/apply. Deliberately minimal for
# First Release -- we add tflint/security scanning later, not up front.
set -euo pipefail

# TF_BIN=tofu if you use OpenTofu instead of HashiCorp Terraform.
TF_BIN="${TF_BIN:-terraform}"

cd "$(dirname "$0")/../infra/environments/dev"

"$TF_BIN" fmt -check -recursive
"$TF_BIN" validate
