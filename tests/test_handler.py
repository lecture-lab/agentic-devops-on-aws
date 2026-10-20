"""Focused tests for review findings A3/A4 -- fail-closed gating and exception
redaction. No AWS credentials or network access required: these tests
monkeypatch the secret-fetch and HTTP-send calls to raise if they're ever
reached, so a bug that would fetch a real secret or call real Telegram
fails the test instead of silently doing it.
"""
import importlib
import json as _json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "notifications" / "telegram"))


def _reload_handler(*, enabled: str, after_epoch: str = "", analysis_arn: str = ""):
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ["TELEGRAM_BOT_TOKEN_SECRET_ARN"] = "arn:aws:secretsmanager:us-east-1:000000000000:secret:test"
    os.environ["TELEGRAM_CHAT_ID"] = "0"
    os.environ["ALERTS_ENABLED"] = enabled
    os.environ["ALERTS_ENABLED_AFTER_EPOCH"] = after_epoch
    os.environ["ANALYSIS_FUNCTION_ARN"] = analysis_arn
    if "handler" in sys.modules:
        return importlib.reload(sys.modules["handler"])
    return importlib.import_module("handler")


VALID_MESSAGE = {
    "AlarmName": "agentic-devops-dev-high-5xx",
    "NewStateValue": "ALARM",
}
# The SNS envelope's own publish timestamp -- what should_send() actually
# gates on, not anything inside the alarm body (which a retried/replayed
# delivery would still carry unchanged from the original event).
VALID_SNS_TIMESTAMP = "2026-09-03T07:00:00.000Z"


class ShouldSendTests(unittest.TestCase):
    def test_alerts_disabled_blocks_everything(self):
        h = _reload_handler(enabled="false", after_epoch="0")
        ok, reason = h.should_send(VALID_MESSAGE, VALID_SNS_TIMESTAMP)
        self.assertFalse(ok)
        self.assertEqual(reason, "alerts disabled")

    def test_unknown_alarm_blocked(self):
        h = _reload_handler(enabled="true", after_epoch="0")
        msg = {**VALID_MESSAGE, "AlarmName": "some-other-alarm-not-ours"}
        ok, reason = h.should_send(msg, VALID_SNS_TIMESTAMP)
        self.assertFalse(ok)
        self.assertEqual(reason, "unknown alarm")

    def test_disallowed_state_blocked(self):
        h = _reload_handler(enabled="true", after_epoch="0")
        msg = {**VALID_MESSAGE, "NewStateValue": "SOMETHING_WEIRD"}
        ok, reason = h.should_send(msg, VALID_SNS_TIMESTAMP)
        self.assertFalse(ok)
        self.assertEqual(reason, "disallowed state")

    def test_missing_activation_cutoff_blocks_everything(self):
        # Empty/unset cutoff must fail closed (+inf), not open (0 / past).
        h = _reload_handler(enabled="true", after_epoch="")
        ok, reason = h.should_send(VALID_MESSAGE, VALID_SNS_TIMESTAMP)
        self.assertFalse(ok)
        self.assertEqual(reason, "stale pre-activation event")

    def test_event_before_cutoff_blocked(self):
        h = _reload_handler(enabled="true", after_epoch="9999999999")  # far future
        ok, reason = h.should_send(VALID_MESSAGE, VALID_SNS_TIMESTAMP)
        self.assertFalse(ok)
        self.assertEqual(reason, "stale pre-activation event")

    def test_unparsable_sns_timestamp_blocked(self):
        h = _reload_handler(enabled="true", after_epoch="0")
        ok, reason = h.should_send(VALID_MESSAGE, "not-a-timestamp")
        self.assertFalse(ok)
        self.assertEqual(reason, "stale pre-activation event")

    def test_replayed_event_with_old_body_but_reused_sns_envelope_still_gated_by_envelope_time(self):
        # A retried SNS delivery keeps the original alarm body untouched;
        # the gate must key off the envelope timestamp, not body content.
        h = _reload_handler(enabled="true", after_epoch="9999999999")
        stale_looking_body = {**VALID_MESSAGE}  # body itself carries no timestamp anymore
        ok, reason = h.should_send(stale_looking_body, VALID_SNS_TIMESTAMP)
        self.assertFalse(ok)
        self.assertEqual(reason, "stale pre-activation event")

    def test_valid_event_after_cutoff_allowed(self):
        h = _reload_handler(enabled="true", after_epoch="0")  # epoch 0 = well before any real event
        ok, reason = h.should_send(VALID_MESSAGE, VALID_SNS_TIMESTAMP)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_handler_skips_without_touching_secrets_or_network(self):
        h = _reload_handler(enabled="false", after_epoch="0")
        with mock.patch.object(h, "_secrets") as fake_secrets, \
             mock.patch("urllib.request.urlopen") as fake_urlopen:
            fake_secrets.get_secret_value.side_effect = AssertionError("must not fetch secret")
            fake_urlopen.side_effect = AssertionError("must not call network")
            event = {
                "Records": [{
                    "Sns": {
                        "Message": _json.dumps(VALID_MESSAGE),
                        "Timestamp": VALID_SNS_TIMESTAMP,
                    }
                }]
            }
            result = h.handler(event, None)
            self.assertEqual(result, {"statusCode": 200})


class ExceptionRedactionTests(unittest.TestCase):
    def test_send_failure_never_leaks_url_or_token(self):
        h = _reload_handler(enabled="true", after_epoch="0")
        sentinel_token = "SENTINEL-TOKEN-MUST-NOT-LEAK-1234567890"

        with mock.patch.object(h, "_bot_token", return_value=sentinel_token), \
             mock.patch("urllib.request.urlopen") as fake_urlopen:
            fake_urlopen.side_effect = urllib.error.URLError(
                f"connection refused for https://api.telegram.org/bot{sentinel_token}/sendMessage"
            )
            with self.assertRaises(RuntimeError) as ctx:
                h._send("test message")

            raised_text = str(ctx.exception)
            self.assertNotIn(sentinel_token, raised_text)
            self.assertIsNone(ctx.exception.__cause__)  # `from None` -- no chained original exception



ANALYSIS_ARN = "arn:aws:lambda:us-east-1:000000000000:function:analysis"
ALARM_BODY = {"AlarmName": "agentic-devops-dev-high-5xx", "NewStateValue": "ALARM",
              "StateChangeTime": "2026-10-16T00:34:58.000+0000", "NewStateReason": "Threshold Crossed: secret-ish detail"}


def _event(message):
    return {"Records": [{"Sns": {"Message": _json.dumps(message), "Timestamp": VALID_SNS_TIMESTAMP, "MessageId": "m-1"}}]}


class AnalysisStartTests(unittest.TestCase):
    """알림 발송에 성공한 ALARM 뒤에만 분석 Lambda 를 비동기로 부른다."""

    def test_alarm_after_a_successful_send_starts_the_analysis_with_a_minimal_payload(self):
        h = _reload_handler(enabled="true", after_epoch="0", analysis_arn=ANALYSIS_ARN)
        with mock.patch.object(h, "_send") as fake_send, mock.patch.object(h, "_lambda") as fake_lambda:
            self.assertEqual(h.handler(_event(ALARM_BODY), None), {"statusCode": 200})
        fake_send.assert_called_once()
        fake_lambda.invoke.assert_called_once()
        kw = fake_lambda.invoke.call_args.kwargs
        self.assertEqual(kw["FunctionName"], ANALYSIS_ARN)
        self.assertEqual(kw["InvocationType"], "Event")
        payload = _json.loads(kw["Payload"].decode("utf-8"))
        self.assertEqual(payload["v"], 1)
        self.assertEqual(payload["alarm_name"], "agentic-devops-dev-high-5xx")
        self.assertEqual(payload["state_change_time"], "2026-10-16T00:34:58.000+0000")
        self.assertEqual(payload["sns_message_id"], "m-1")
        self.assertNotIn("NewStateReason", _json.dumps(payload))          # 알림 본문 원문은 넘기지 않는다
        self.assertNotIn("secret-ish", _json.dumps(payload))

    def test_ok_state_sends_the_notice_but_never_starts_an_analysis(self):
        h = _reload_handler(enabled="true", after_epoch="0", analysis_arn=ANALYSIS_ARN)
        with mock.patch.object(h, "_send") as fake_send, mock.patch.object(h, "_lambda") as fake_lambda:
            h.handler(_event({**ALARM_BODY, "NewStateValue": "OK"}), None)
        fake_send.assert_called_once()
        fake_lambda.invoke.assert_not_called()

    def test_failed_send_means_no_analysis(self):
        h = _reload_handler(enabled="true", after_epoch="0", analysis_arn=ANALYSIS_ARN)
        with mock.patch.object(h, "_send", side_effect=RuntimeError("telegram send failed")), mock.patch.object(h, "_lambda") as fake_lambda:
            with self.assertRaises(RuntimeError):
                h.handler(_event(ALARM_BODY), None)
        fake_lambda.invoke.assert_not_called()

    def test_gated_off_alerts_never_start_an_analysis(self):
        h = _reload_handler(enabled="false", after_epoch="0", analysis_arn=ANALYSIS_ARN)
        with mock.patch.object(h, "_send") as fake_send, mock.patch.object(h, "_lambda") as fake_lambda:
            h.handler(_event(ALARM_BODY), None)
        fake_send.assert_not_called()
        fake_lambda.invoke.assert_not_called()

    def test_without_an_arn_nothing_is_called(self):
        h = _reload_handler(enabled="true", after_epoch="0", analysis_arn="")
        with mock.patch.object(h, "_send"), mock.patch.object(h, "_lambda") as fake_lambda:
            h.handler(_event(ALARM_BODY), None)
        fake_lambda.invoke.assert_not_called()

    def test_a_failing_invoke_does_not_break_the_notice_and_leaks_nothing(self):
        h = _reload_handler(enabled="true", after_epoch="0", analysis_arn=ANALYSIS_ARN)
        with mock.patch.object(h, "_send") as fake_send, mock.patch.object(h, "_lambda") as fake_lambda:
            fake_lambda.invoke.side_effect = Exception("AccessDenied for " + ANALYSIS_ARN)
            with self.assertLogs(level="ERROR") as logs:
                self.assertEqual(h.handler(_event(ALARM_BODY), None), {"statusCode": 200})
        fake_send.assert_called_once()
        self.assertNotIn(ANALYSIS_ARN, "\n".join(logs.output))
        self.assertIn("Analysis start failed", "\n".join(logs.output))

if __name__ == "__main__":
    unittest.main()
