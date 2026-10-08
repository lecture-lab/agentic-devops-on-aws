"""SNS -> Telegram bridge for Section 6 (Real Alerting).

Reads the bot token from AWS Secrets Manager at invoke time (never from
an env var holding the raw value, never from a file, never as a CLI
argument -- provisioning is a manual AWS Console step, see telegram.tf).
The secret ARN itself is passed in as an env var -- that's a name, not a
value.

Data minimization (review finding F4): the outbound message is built from a
fixed, known-safe allowlist, not a passthrough of whatever CloudWatch
put in the SNS message. Raw NewStateReason text is never forwarded.

Fail-closed gating (review finding A3, refined in the F2-F6 recheck): SNS
retries failed/throttled Lambda deliveries for a long time (AWS: many
attempts over roughly three weeks). Simply un-throttling this function
after a hold is not safe on its own -- a stale, already-queued event can
still arrive and fire. should_send() is a pure decision function (no
I/O, directly unit-testable) gated on: a known alarm, an allowed state
value, ALERTS_ENABLED explicitly true, and the *SNS envelope's own
publish timestamp* (not the alarm body's self-reported StateChangeTime,
which a replayed/retried delivery would still carry unchanged) being
newer than an explicit activation cutoff. Any one of these failing means
no secret fetch and no send.

Accepted, documented (not fixed): SNS-to-Lambda delivery is at-least-once
(AWS's own guarantee), and this handler does no deduplication by SNS
MessageId. A given alarm state change can plausibly cause more than one
Telegram message. For this course's scope -- a single bounded alerting
demo, not a paging system with on-call fatigue stakes -- an occasional
duplicate message is a cosmetic annoyance, not a safety issue, so
idempotency logic (a dedup table, a TTL cache) isn't built here. Revisit
if this pattern is ever reused somewhere duplicate delivery would matter.
"""
import datetime
import json
import logging
import os
import urllib.error
import urllib.request

import boto3

SECRET_ARN = os.environ["TELEGRAM_BOT_TOKEN_SECRET_ARN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
ALERTS_ENABLED = os.environ.get("ALERTS_ENABLED", "false").strip().lower() == "true"

try:
    # Unset/invalid -> +inf, so "event is older than cutoff" is always
    # true and nothing passes. Fail closed, not open.
    ENABLED_AFTER_EPOCH = float(os.environ.get("ALERTS_ENABLED_AFTER_EPOCH", ""))
except ValueError:
    ENABLED_AFTER_EPOCH = float("inf")

MAX_MESSAGE_CHARS = 500
ALLOWED_STATES = {"ALARM", "OK", "INSUFFICIENT_DATA"}

# Explicit allowlist: internal CloudWatch alarm name -> safe outward-facing
# label. An alarm not in this table is refused, not forwarded generically.
ALARM_ALIASES = {
    "agentic-devops-dev-high-5xx": "High error rate (5xx) on the app",
}

log = logging.getLogger()
log.setLevel(logging.INFO)

_secrets = boto3.client("secretsmanager")


def _parse_epoch(iso_ts: str) -> float:
    try:
        return datetime.datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError, TypeError):
        return float("-inf")  # unparsable -> arbitrarily old -> blocked by the cutoff check


def should_send(message: dict, sns_timestamp: str) -> tuple[bool, str]:
    """Pure decision: no AWS/network calls, so this is directly testable.

    `sns_timestamp` is the SNS envelope's own publish timestamp
    (record["Sns"]["Timestamp"]) -- not anything inside the alarm body,
    which a retried/replayed delivery would still carry unchanged from
    the original event.
    """
    if not ALERTS_ENABLED:
        return False, "alerts disabled"
    if message.get("AlarmName") not in ALARM_ALIASES:
        return False, "unknown alarm"
    if message.get("NewStateValue") not in ALLOWED_STATES:
        return False, "disallowed state"
    if _parse_epoch(sns_timestamp) < ENABLED_AFTER_EPOCH:
        return False, "stale pre-activation event"
    return True, "ok"


def _format(message: dict) -> str:
    label = ALARM_ALIASES[message["AlarmName"]]
    state = message["NewStateValue"]
    text = f"*{label}*\nState: {state}\nDetails: see CloudWatch console."
    return text[:MAX_MESSAGE_CHARS]


def _bot_token() -> str:
    return _secrets.get_secret_value(SecretId=SECRET_ARN)["SecretString"]


def handler(event, _context):
    for record in event["Records"]:
        sns = record["Sns"]
        message = json.loads(sns["Message"])
        ok, reason = should_send(message, sns.get("Timestamp", ""))
        if not ok:
            log.info("Skipping SNS record: %s", reason)
            continue
        _send(_format(message))
    return {"statusCode": 200}


def _send(text: str) -> None:
    token = _bot_token()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except urllib.error.URLError:
        # Log a fixed safe message, and raise a brand-new exception with
        # `from None` -- not a bare re-raise. The caught exception (and
        # its string form, which embeds the request URL, which embeds the
        # bot token) must never reach the platform's own unhandled-error
        # logging, which a re-raise or `raise ... from exc` would risk.
        log.error("Telegram send failed (token/URL withheld from logs)")
        raise RuntimeError("telegram send failed") from None
