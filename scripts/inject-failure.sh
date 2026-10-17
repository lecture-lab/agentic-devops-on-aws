#!/usr/bin/env bash
# Section 6-7 (Real Alerting / Capstone): deliberately cause a small, known,
# harmless failure so you can watch the alert pipeline catch it for real.
#
# What it does: calls the deployed app's /error route a few times. That
# route returns HTTP 500 on purpose (app/web/nginx.conf). The ALB counts the
# 5xx, the CloudWatch alarm agentic-devops-dev-high-5xx goes to ALARM, and
# the alert reaches Telegram -- if you opened the alert window first (see
# the Section 6 steps: telegram_alerts_enabled / ..._after_epoch).
# It touches nothing else: no AWS API calls, no resource changes.
#
# Recovery needs no script: stop calling /error. With no new 5xx the alarm
# returns to OK by itself, and an OK message follows. In our test runs (Seoul
# and N. Virginia) that took about 6 to 7 minutes, so wait several minutes
# before worrying.
#
# Usage:
#   ./scripts/inject-failure.sh            # 5 requests, 10 s apart
#   ./scripts/inject-failure.sh 3 5        # 3 requests, 5 s apart
#   ALB_URL=http://<alb-dns-name> ./scripts/inject-failure.sh
# SHOW_URL=1 prints the load balancer address in the output.
# TF_BIN selects the CLI used to read the ALB name (default: terraform;
# set TF_BIN=tofu if you use OpenTofu).
set -euo pipefail

COUNT="${1:-5}"
INTERVAL="${2:-10}"
TF_BIN="${TF_BIN:-terraform}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v curl >/dev/null 2>&1 || { echo "curl is required." >&2; exit 1; }
[[ "$COUNT" =~ ^[0-9]+$ && "$INTERVAL" =~ ^[0-9]+$ && "$COUNT" -ge 1 ]] || {
  echo "Usage: $0 [count>=1] [interval-seconds]" >&2; exit 1; }

if [[ -z "${ALB_URL:-}" ]]; then
  command -v "$TF_BIN" >/dev/null 2>&1 || { echo "$TF_BIN not found; set ALB_URL=http://<alb-dns-name> instead." >&2; exit 1; }
  ALB_DNS="$("$TF_BIN" -chdir="$ROOT/infra/environments/dev" output -raw alb_dns_name)"
  ALB_URL="http://${ALB_DNS}"
fi

# Show the load balancer address only on request (it is a live public
# endpoint; keep it out of recordings and screenshots by default).
if [[ "${SHOW_URL:-0}" == "1" ]]; then SHOWN="${ALB_URL}/error"; else SHOWN="the app's /error URL"; fi
echo "inject-failure.sh: calling ${SHOWN} ${COUNT} time(s), ${INTERVAL}s apart."
echo "It only requests that one URL. Nothing else is changed."

five_xx=0
for ((i = 1; i <= COUNT; i++)); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${ALB_URL}/error" || true)"
  echo "  [$i/$COUNT] HTTP ${code}"
  if [[ "$code" == 5* ]]; then five_xx=$((five_xx + 1)); fi
  if [[ "$code" == "404" ]]; then
    echo "  /error returned 404: this container does not have the course nginx.conf" >&2
    echo "  (the public nginx image needs inject_nginx_conf = true in infra/environments/dev)." >&2
    exit 2
  fi
  if (( i < COUNT )); then sleep "$INTERVAL"; fi
done

if (( five_xx == 0 )); then
  echo "No 5xx was returned, so the alarm will not fire. Check the app's /health URL first (run with SHOW_URL=1 to print the address)." >&2
  exit 3
fi
echo "Done: ${five_xx} request(s) returned 5xx. Stop here -- the alarm returns to OK on its own once the errors stop."
