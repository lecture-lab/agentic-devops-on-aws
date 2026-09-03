"""SNS -> Telegram bridge for Section 6 (Real Alerting).

Reads the bot token from AWS Secrets Manager at invoke time (never from
an env var holding the raw value, never from a file). The secret ARN
itself is passed in as an env var -- that's a name, not a value.
"""
import json
import os
import urllib.request

import boto3

SECRET_ARN = os.environ["TELEGRAM_BOT_TOKEN_SECRET_ARN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

_secrets = boto3.client("secretsmanager")


def _bot_token() -> str:
    return _secrets.get_secret_value(SecretId=SECRET_ARN)["SecretString"]


def handler(event, _context):
    for record in event["Records"]:
        message = json.loads(record["Sns"]["Message"])
        text = _format(record["Sns"].get("Subject", "Alert"), message)
        _send(text)
    return {"statusCode": 200}


def _format(subject: str, message: dict) -> str:
    lines = [f"*{subject}*"]
    for key in ("AlarmName", "NewStateValue", "NewStateReason"):
        if key in message:
            lines.append(f"{key}: {message[key]}")
    return "\n".join(lines)


def _send(text: str) -> None:
    token = _bot_token()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
