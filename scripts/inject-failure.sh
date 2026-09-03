#!/usr/bin/env bash
# Section 6 (Real Alerting): deliberately break something small and known,
# so you can watch the observability pipeline built in Section 5 actually
# catch it -- instead of taking the lecture's word for it.
#
# This is a placeholder until Section 4-6 wire up the real service.
# It will call the deployed app's /error endpoint to force HTTP 5xx.
set -euo pipefail

echo "inject-failure.sh: not wired up yet."
echo "This will hit the deployed application's /error endpoint once"
echo "Section 4 (deployment) has actually shipped something to hit."
exit 1
