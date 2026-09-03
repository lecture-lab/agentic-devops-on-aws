"""SNS -> Telegram bridge for Section 6 (Real Alerting).

Reads the bot token from AWS Secrets Manager at invoke time (never from
an env var holding the raw value, never from a file). The secret ARN
itself is passed in as an env var -- that's a name, not a value.

Data minimization (reviewer F4): this is the one hop that leaves AWS, so
the outbound message is built from a fixed, known-safe allowlist -- not
a straight passthrough of whatever CloudWatch put in the SNS message.
CloudWatch's own auto-generated NewStateReason text is never forwarded
verbatim (we have no scrub contract proving it's always safe); we send
a fixed pointer to the console instead. Alarm names are mapped through
an explicit alias table rather than forwarded raw, so this file is also
the one place that has to be updated when a new alarm is wired up.
"""
import json
import logging
import os
import urllib.error
import urllib.request

import boto3

SECRET_ARN = os.environ["TELEGRAM_BOT_TOKEN_SECRET_ARN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MAX_MESSAGE_CHARS = 500

# Explicit allowlist: internal CloudWatch alarm name -> safe outward-facing
# label. Anything not in this table falls back to a generic label rather
# than forwarding the raw (possibly resource-identifying) alarm name.
ALARM_ALIASES = {
    "agentic-devops-dev-high-5xx": "High error rate (5xx) on the app",
}

log = logging.getLogger()
log.setLevel(logging.INFO)

_secrets = boto3.client("secretsmanager")


def _bot_token() -> str:
    return _secrets.get_secret_value(SecretId=SECRET_ARN)["SecretString"]


def handler(event, _context):
    for record in event["Records"]:
        message = json.loads(record["Sns"]["Message"])
        text = _format(message)
        _send(text)
    return {"statusCode": 200}


def _format(message: dict) -> str:
    alarm_name = message.get("AlarmName", "")
    label = ALARM_ALIASES.get(alarm_name, "Course infra alert")
    state = message.get("NewStateValue", "UNKNOWN")

    # NewStateReason is CloudWatch-generated free text -- not forwarded
    # verbatim (reviewer F4). A fixed pointer is enough for this course's
    # scope; anyone who needs the detail has console access.
    text = f"*{label}*\nState: {state}\nDetails: see CloudWatch console."
    return text[:MAX_MESSAGE_CHARS]


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
        # Never log the exception object directly here -- its default
        # string form can include the request URL, and the URL contains
        # the bot token. Log only what's safe to know from CloudWatch Logs.
        log.error("Telegram send failed (token/URL withheld from logs)")
        raise
