#!/usr/bin/env bash
# Run this before every terraform plan/apply. Deliberately minimal for
# First Release -- we add tflint/security scanning later, not up front.
set -euo pipefail

cd "$(dirname "$0")/../infra/environments/dev"

terraform fmt -check -recursive
terraform validate
