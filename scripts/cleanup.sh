#!/usr/bin/env bash
# Every lab must have an exit. This script never runs destroy for you --
# it shows you exactly what would be destroyed, and you decide.
set -euo pipefail

cd "$(dirname "$0")/../infra/environments/dev"

echo "== Resources currently in this environment's state =="
terraform state list || echo "(state is empty -- nothing to clean up)"

echo
echo "== What destroying them would look like =="
terraform plan -destroy -out=.cleanup.destroyplan

echo
echo "Review the plan above. To actually destroy these resources, run:"
echo "  terraform apply .cleanup.destroyplan"
echo
echo "This script stops here on purpose -- it does not apply anything for you."
