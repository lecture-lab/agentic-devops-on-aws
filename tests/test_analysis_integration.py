"""통합 시험 — 코스 저장소 안에서 돈다: 진짜 lambda_handler + 진짜 collector.collect_for_alert + 진짜 send_plain.
가짜는 boto3 클라이언트(CloudWatch·Logs·ECS·ELB·Bedrock·Secrets·DynamoDB)와 Telegram 주소(urlopen) 뿐. 실제 AWS·모델·Telegram 0.
놓는 자리: 코스 저장소 tests/ (코어는 notifications/analysis/, 수집기는 scripts/). 이 좌석 폴더에서는 그 둘이 없어 건너뛴다.
"""
import datetime as dt
import importlib
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
ANALYSIS, SCRIPTS = REPO / "notifications" / "analysis", REPO / "scripts"
IN_COURSE_REPO = (ANALYSIS / "analysis_handler.py").exists() and (SCRIPTS / "collector.py").exists()
MODULES = ("collector", "send_plain", "analysis_handler", "analysis_core", "guards")   # 끝에 되돌린다(다른 시험이 같은 이름을 쓸 수 있음)

ALARM = "agentic-devops-dev-high-5xx"
ACCOUNT = "123456789012"
PUBLIC_IP = "1.2.3.4"            # 공인(is_global). 문서용 대역(203.0.113.x)은 수집기가 공인으로 안 봐서 안 가림
TOKEN = "123456:TEST-TOKEN-not-real"
AT = dt.datetime(2026, 10, 16, 0, 34, 58, tzinfo=dt.timezone.utc)
MODEL_TEXT = """[HIGH] agentic-devops-dev-app-service incident
What happened
00:31 에 5XX 6건.
Evidence
- HTTPCode_Target_5XX_Count 6
Possible cause
1. /error 호출
Confidence: MEDIUM
Recommended
1. 로그 확인
Approval required
No action executed."""
ENV = {"ANALYSIS_ENABLED": "true", "AWS_REGION": "ap-northeast-2", "MODEL_ID": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
       "TABLE": "analysis-state", "ALARM_NAME": ALARM, "CLUSTER": "agentic-devops-dev-cluster",
       "SERVICE": "agentic-devops-dev-app-service", "LOG_GROUP": "/ecs/agentic-devops-dev-app",
       "TELEGRAM_CHAT_ID": "42", "TELEGRAM_BOT_TOKEN_SECRET_ARN": f"arn:aws:secretsmanager:ap-northeast-2:{ACCOUNT}:secret:bot",
       "COOLDOWN_MINUTES": "15", "DAILY_CAP": "20", "SLEEP_SECONDS": "0"}


def ms(t):
    return int(t.timestamp() * 1000)


class Fake:
    """verb 이름 → 응답(또는 함수). 부른 기록을 남긴다."""
    def __init__(self, responses):
        self.responses, self.seen = responses, []

    def __getattr__(self, name):
        if name.startswith("_") or name not in self.responses:
            raise AttributeError(name)
        def call(**kw):
            self.seen.append((name, kw))
            r = self.responses[name]
            return r(**kw) if callable(r) else r
        return call


class FakeDynamo:
    class exceptions:
        class ConditionalCheckFailedException(Exception):
            pass

    def __init__(self):
        self.items = {}

    def put_item(self, TableName, Item, ConditionExpression, ExpressionAttributeValues):
        key, now = Item["pk"]["S"], int(ExpressionAttributeValues[":now"]["N"])
        old = self.items.get(key)
        if old and int(old["expires_at"]) >= now:
            raise self.exceptions.ConditionalCheckFailedException()
        self.items[key] = {"expires_at": Item["expires_at"]["N"]}

    def update_item(self, TableName, Key, UpdateExpression, ConditionExpression, ExpressionAttributeValues):
        it = self.items.setdefault(Key["pk"]["S"], {"n": 0})
        if it["n"] >= int(ExpressionAttributeValues[":cap"]["N"]):
            raise self.exceptions.ConditionalCheckFailedException()
        it["n"] += 1

    def delete_item(self, TableName, Key):
        self.items.pop(Key["pk"]["S"], None)


def aws_world():
    tg = f"arn:aws:elasticloadbalancing:ap-northeast-2:{ACCOUNT}:targetgroup/agentic-devops-dev-app-tg/abc"
    log_line = f'{PUBLIC_IP} - - [16/Oct/2026:00:31:09 +0000] "GET /error HTTP/1.1" 500 21 "-" "curl/8.18.0"'
    bedrock_prompts = []

    def converse(**kw):
        bedrock_prompts.append(kw["messages"][0]["content"][0]["text"])
        return {"output": {"message": {"content": [{"text": MODEL_TEXT}]}}, "stopReason": "end_turn",
                "usage": {"inputTokens": 5000, "outputTokens": 300}}

    clients = {
        "cloudwatch": Fake({
            "describe_alarms": {"MetricAlarms": [{"AlarmName": ALARM, "StateValue": "ALARM", "MetricName": "HTTPCode_Target_5XX_Count",
                                                  "Namespace": "AWS/ApplicationELB", "Threshold": 1.0, "Period": 60,
                                                  "Dimensions": [{"Name": "LoadBalancer", "Value": "app/lb/1"},
                                                                 {"Name": "TargetGroup", "Value": "targetgroup/tg/abc"}]}]},
            "describe_alarm_history": {"AlarmHistoryItems": [{"Timestamp": AT, "HistorySummary": "Alarm updated from OK to ALARM"}]},
            "get_metric_statistics": {"Datapoints": [{"Timestamp": AT - dt.timedelta(minutes=4), "Sum": 6.0, "Average": 0.18}]}}),
        "logs": Fake({"filter_log_events": {"events": [{"timestamp": ms(AT - dt.timedelta(minutes=3)), "message": log_line}] * 6}}),
        "ecs": Fake({"describe_services": {"services": [{"serviceName": ENV["SERVICE"], "status": "ACTIVE", "desiredCount": 2,
                                                         "runningCount": 2, "taskDefinition": f"arn:aws:ecs:ap-northeast-2:{ACCOUNT}:task-definition/app:5",
                                                         "loadBalancers": [{"targetGroupArn": tg}], "deployments": [], "events": []}]},
                     "describe_task_definition": {"taskDefinition": {"family": "app", "revision": 5, "containerDefinitions": []}}}),
        "elbv2": Fake({"describe_target_health": {"TargetHealthDescriptions": [{"TargetHealth": {"State": "healthy"}}]}}),
        "bedrock-runtime": Fake({"converse": converse}),
        "secretsmanager": Fake({"get_secret_value": {"SecretString": TOKEN}}),
        "dynamodb": FakeDynamo(),
    }
    fake_boto3 = types.SimpleNamespace(client=lambda name, **kw: clients[name])
    return fake_boto3, clients, bedrock_prompts


class Telegram:
    """send_plain 의 urlopen 자리. 보낸 요청을 모은다."""
    def __init__(self):
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append((req.full_url, json.loads(req.data.decode("utf-8"))))
        return mock.MagicMock(__enter__=lambda s: s, __exit__=lambda *a: False, read=lambda: b'{"ok":true}')


@unittest.skipUnless(IN_COURSE_REPO, "코스 저장소 밖(좌석 폴더)에서는 건너뜀")
class AnalysisIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.boto3, self.clients, self.prompts = aws_world()
        self.tg = Telegram()
        self.patches = [mock.patch.dict(os.environ, ENV), mock.patch.dict(sys.modules, {"boto3": self.boto3})]
        for p in self.patches:
            p.start()
        self.saved_path, self.saved_modules = list(sys.path), {n: sys.modules.pop(n) for n in MODULES if n in sys.modules}
        sys.path[:0] = [str(ANALYSIS), str(SCRIPTS)]
        self.handler = importlib.import_module("analysis_handler")
        self.core = importlib.import_module("analysis_core")
        mock.patch.object(importlib.import_module("send_plain").urllib.request, "urlopen", self.tg).start()
        self.addCleanup(mock.patch.stopall)
        self.ctx = types.SimpleNamespace(get_remaining_time_in_millis=lambda: 110000)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        sys.path[:] = self.saved_path
        for n in MODULES:
            sys.modules.pop(n, None)
        sys.modules.update(self.saved_modules)

    def event(self, sct="2026-10-16T00:34:58.000+0000"):
        return {"v": 1, "alarm_name": ALARM, "state": "ALARM", "state_change_time": sct,
                "sns_timestamp": "2026-10-16T00:34:59.123Z", "sns_message_id": "m-1", "region": "ap-northeast-2"}

    def test_one_alarm_end_to_end(self):
        r = self.handler.lambda_handler(self.event(), self.ctx)
        self.assertEqual(r, {"status": "sent"})
        # 수집기가 실제로 돌았다(이벤트 시각으로)
        self.assertEqual(self.clients["cloudwatch"].seen[0][0], "describe_alarms")
        self.assertEqual(len(self.clients["logs"].seen), 1)
        # 모델에 간 프롬프트: 맥락이 들어 있고, 계정 ID·공인 IP 는 가려져 있다
        self.assertEqual(len(self.prompts), 1)
        self.assertIn("GET /error", self.prompts[0])
        self.assertNotIn(ACCOUNT, self.prompts[0])
        self.assertNotIn(PUBLIC_IP, self.prompts[0])
        # Telegram: 평문 한 통 · 머리말 · 안전 문구 · 토큰은 주소에만
        self.assertEqual(len(self.tg.requests), 1)
        url, body = self.tg.requests[0]
        self.assertNotIn("parse_mode", body)
        self.assertEqual(body["chat_id"], "42")
        self.assertTrue(body["text"].startswith(self.core.HEADER))
        self.assertTrue(body["text"].endswith(self.core.FOOTER))
        self.assertIn("[HIGH] agentic-devops-dev-app-service incident", body["text"])
        self.assertNotIn(TOKEN, body["text"])

    def test_collection_warnings_reach_the_top_without_the_model(self):
        self.clients["logs"].responses["filter_log_events"] = {"events": []}     # 로그가 아직 안 옴
        self.handler.lambda_handler(self.event(), self.ctx)
        lines = self.tg.requests[0][1]["text"].splitlines()
        self.assertEqual(lines[0], self.core.HEADER)
        self.assertTrue(any(ln.startswith("수집 경고(logs · empty)") for ln in lines[1:4]))

    def test_redelivery_is_skipped_and_nothing_is_sent_twice(self):
        self.handler.lambda_handler(self.event(), self.ctx)
        r = self.handler.lambda_handler(self.event(), self.ctx)
        self.assertEqual(r, {"status": "skipped", "reason": "duplicate"})
        self.assertEqual((len(self.prompts), len(self.tg.requests)), (1, 1))

    def test_empty_state_change_time_is_ignored_before_collecting(self):
        self.assertEqual(self.handler.lambda_handler(self.event(sct=""), self.ctx), {"status": "ignored"})
        self.assertEqual((self.clients["cloudwatch"].seen, self.tg.requests), ([], []))

    def test_bad_time_format_becomes_collect_failure_message(self):
        r = self.handler.lambda_handler(self.event(sct="not-a-time"), self.ctx)
        self.assertEqual(r["status"], "sent")
        self.assertEqual(self.prompts, [])
        self.assertIn("자동 분석 실패(코드: 수집)", self.tg.requests[0][1]["text"])

    def test_disabled_touches_nothing(self):
        with mock.patch.dict(os.environ, {"ANALYSIS_ENABLED": "false"}):
            self.assertEqual(self.handler.lambda_handler(self.event(), self.ctx), {"status": "disabled"})
        self.assertEqual((self.clients["cloudwatch"].seen, self.prompts, self.tg.requests), ([], [], []))


if __name__ == "__main__":
    unittest.main()
