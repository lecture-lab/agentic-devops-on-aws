#!/usr/bin/env python3
"""collect-incident-context.py 시험 — 네트워크·AWS 호출 0. 합성 fixture 를 임시 폴더에 만들어 --fixture 로 돌린다."""
import importlib.util, json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "collect-incident-context.py")
spec = importlib.util.spec_from_file_location("cic", SCRIPT)
cic = importlib.util.module_from_spec(spec); spec.loader.exec_module(cic)

ACCT = "123456789012"            # 합성 계정 ID
FAKE_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"   # 합성 비밀 모양(실제 키 아님)
NOW = "2026-10-08T12:00:00Z"
ALARM_AT = "2026-10-08T11:00:00+00:00"

def j(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)

def ms(s):
    import datetime as dt
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)

def write_fixtures(d, drop=(), logs=None, td_env=None):
    files = {
        "cloudwatch.describe-alarms.alarm": {"MetricAlarms": [{
            "AlarmName": "agentic-devops-dev-high-5xx", "StateValue": "ALARM", "StateReason": "Threshold Crossed: 1 datapoint [32.0] >= 1",
            "StateUpdatedTimestamp": ALARM_AT, "MetricName": "HTTPCode_Target_5XX_Count", "Namespace": "AWS/ApplicationELB",
            "ComparisonOperator": "GreaterThanOrEqualToThreshold", "Threshold": 1.0, "Period": 60, "EvaluationPeriods": 1, "Statistic": "Sum",
            "Dimensions": [{"Name": "LoadBalancer", "Value": "app/agentic-devops-dev-alb/abc123"}, {"Name": "TargetGroup", "Value": "targetgroup/agentic-devops-dev-app-tg/def456"}]}]},
        "cloudwatch.describe-alarm-history.history": {"AlarmHistoryItems": [{"Timestamp": ALARM_AT, "HistorySummary": "Alarm updated from OK to ALARM"}]},
        "cloudwatch.get-metric-statistics.target_5xx_count": {"Datapoints": [{"Timestamp": "2026-10-08T10:59:00Z", "Sum": 12.0}, {"Timestamp": "2026-10-08T11:00:00Z", "Sum": 20.0}]},
        "cloudwatch.get-metric-statistics.target_4xx_count": {"Datapoints": [{"Timestamp": "2026-10-08T11:00:00Z", "Sum": 3.0}]},
        "cloudwatch.get-metric-statistics.request_count": {"Datapoints": [{"Timestamp": "2026-10-08T10:59:00Z", "Sum": 40.0}, {"Timestamp": "2026-10-08T11:00:00Z", "Sum": 55.0}]},
        "cloudwatch.get-metric-statistics.ecs_cpu": {"Datapoints": [{"Timestamp": "2026-10-08T11:00:00Z", "Average": 4.5}]},
        "logs.filter-log-events.logs": {"events": logs if logs is not None else (
            [{"timestamp": ms("2026-10-08T10:59:%02dZ" % i), "message": '10.20.1.5 - - [08/Oct/2026:10:59:%02d +0000] "GET /error HTTP/1.1" 500 41 "-" "curl/8.0"' % i} for i in range(1, 33)]
            + [{"timestamp": ms("2026-10-08T10:58:00Z"), "message": '10.20.1.5 - - [08/Oct/2026:10:58:00 +0000] "GET / HTTP/1.1" 200 3 "-" "ELB-HealthChecker/2.0"'},
               {"timestamp": ms("2026-10-08T10:58:30Z"), "message": '10.20.1.5 - - [08/Oct/2026:10:58:30 +0000] "GET /nope HTTP/1.1" 404 153 "-" "curl/8.0"'},
               {"timestamp": ms("2026-10-08T10:58:40Z"), "message": 'debug token %s account %s' % (FAKE_KEY, ACCT)}])},
        "ecs.describe-services.service": {"services": [{
            "serviceName": "agentic-devops-dev-app-service", "status": "ACTIVE", "desiredCount": 2, "runningCount": 2, "pendingCount": 0,
            "taskDefinition": "arn:aws:ecs:us-east-1:%s:task-definition/agentic-devops-dev-app:7" % ACCT,
            "deployments": [{"id": "ecs-svc/1", "status": "PRIMARY", "rolloutState": "COMPLETED", "desiredCount": 2, "runningCount": 2,
                             "taskDefinition": "arn:aws:ecs:us-east-1:%s:task-definition/agentic-devops-dev-app:7" % ACCT,
                             "createdAt": "2026-10-08T10:54:00+00:00", "updatedAt": "2026-10-08T10:56:00+00:00"}],
            "events": [{"createdAt": "2026-10-08T10:56:00+00:00", "message": "(service agentic-devops-dev-app-service) has reached a steady state."}],
            "loadBalancers": [{"targetGroupArn": "arn:aws:elasticloadbalancing:us-east-1:%s:targetgroup/agentic-devops-dev-app-tg/def456" % ACCT}]}], "failures": []},
        "ecs.describe-task-definition.taskdef": {"taskDefinition": {"family": "agentic-devops-dev-app", "revision": 7, "registeredAt": "2026-10-08T10:53:30+00:00",
            "containerDefinitions": [{"name": "app", "image": "public.ecr.aws/nginx/nginx:1.30", "command": ["sh", "-c", "x"],
                                      "environment": td_env or [{"name": "NGINX_CONF", "value": "server {}"}, {"name": "DB_PASSWORD", "value": "hunter2-not-a-real-password"}]}]}},
        "elbv2.describe-target-health.targets": {"TargetHealthDescriptions": [{"TargetHealth": {"State": "healthy"}}, {"TargetHealth": {"State": "healthy"}}]},
    }
    for name, obj in files.items():
        if name in drop:
            continue
        j(os.path.join(d, name + ".json"), obj)

def run(extra=(), drop=(), logs=None, td_env=None, now=NOW, env=None):
    d = tempfile.mkdtemp(prefix="cic-fx-")
    write_fixtures(d, drop=drop, logs=logs, td_env=td_env)
    out = os.path.join(d, "out", "incident-context.json")
    e = dict(os.environ); e.update(env or {})
    p = subprocess.run([sys.executable, SCRIPT, "--fixture", d, "--out", out, "--now", now] + list(extra), capture_output=True, text=True, encoding="utf-8", errors="replace", env=e)
    ctx = None
    if os.path.isfile(out):
        with open(out, encoding="utf-8") as fh:
            ctx = json.load(fh)
    return p, ctx, d

class T(unittest.TestCase):
    def tearDown(self):
        for d in getattr(self, "dirs", []):
            shutil.rmtree(d, ignore_errors=True)
    def r(self, **kw):
        p, c, d = run(**kw); self.dirs = getattr(self, "dirs", []) + [d]; return p, c

    def test_english_windows_console_does_not_crash(self):
        # 영문 Windows 콘솔(cp1252)은 한국어 print 를 인코딩하지 못해 죽을 수 있다 — 종료 코드 0 이어야 하고 JSON 은 써져야 한다
        p, c = self.r(env={"PYTHONIOENCODING": "cp1252"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIsNotNone(c)

    def test_happy_path_facts_only(self):
        p, c = self.r()
        self.assertEqual(p.returncode, 0, p.stderr)
        for k in ("incident_id", "timestamp", "severity", "service", "trigger", "metrics", "logs", "resource_state", "recent_changes", "collection_warnings"):
            self.assertIn(k, c)
        self.assertEqual(c["severity"], "HIGH")
        self.assertEqual(c["timestamp"], "2026-10-08T11:00:00Z")
        self.assertEqual(c["metrics"]["target_5xx_count"]["summary"]["sum"], 32.0)
        self.assertEqual(c["logs_meta"]["http_status_counts"], {"500": 32, "200": 1, "404": 1})
        self.assertEqual(c["logs_meta"]["http_5xx_path_counts"], {"/error": 32})
        self.assertEqual(c["resource_state"]["ecs_service"]["running"], 2)
        self.assertEqual(c["collection_warnings"], [])
        self.assertTrue(any(ch["type"] == "deployment" for ch in c["recent_changes"]))
        self.assertNotIn("root_cause", json.dumps(c).lower())  # 원인 판단 필드 없음

    def test_temp_key_id_shape_is_scrubbed(self):
        # CloudTrail 출력에는 임시 키 ID(ASIA...)가 나온다 — AKIA 와 같이 항상 가려져야 한다
        temp_key = "ASIA" + "ABCDEFGHIJKLMNOP"
        counter = {"account_ids": 0, "secret_shapes": 0}
        out = cic.scrub({"userIdentity": {"accessKeyId": temp_key}}, True, counter)
        self.assertNotIn(temp_key, json.dumps(out))
        self.assertGreater(counter["secret_shapes"], 0)

    def test_secret_key_and_session_token_scrubbed_but_git_hash_kept(self):
        # 이름이 붙은 비밀 액세스 키(40자)·STS 세션 토큰은 가리고, 이름 없는 40자(git 해시)는 그대로 둔다
        secret = "A" * 20 + "b" * 20                       # 합성 40자(실제 키 아님)
        sts = "IQoJb3JpZ2lu" + "C" * 50                       # 합성 세션 토큰 모양
        git_hash = "0123456789abcdef0123456789abcdef01234567"  # 40자 git 해시
        counter = {"account_ids": 0, "secret_shapes": 0}
        out = json.dumps(cic.scrub({"a": '"SecretAccessKey": "%s"' % secret, "b": sts,
                                    "c": "aws_session_token=%s" % ("D" * 44), "d": "commit " + git_hash}, True, counter))
        self.assertNotIn(secret, out); self.assertNotIn(sts, out); self.assertNotIn("D" * 44, out)
        self.assertIn(git_hash, out)
        self.assertGreaterEqual(counter["secret_shapes"], 3)

    def test_masking_default_and_no_mask(self):
        p, c = self.r()
        s = json.dumps(c)
        self.assertNotIn(ACCT, s); self.assertNotIn(FAKE_KEY, s)
        self.assertGreater(c["collection_meta"]["masking"]["replaced"]["account_ids"], 0)
        self.assertGreater(c["collection_meta"]["masking"]["replaced"]["secret_shapes"], 0)
        p2, c2 = self.r(extra=["--no-mask"])
        s2 = json.dumps(c2)
        self.assertIn(ACCT, s2)            # 계정 ID 는 --no-mask 면 보임
        self.assertNotIn(FAKE_KEY, s2)     # 비밀 모양은 항상 가려짐

    def test_environment_never_copied(self):
        p, c = self.r()
        s = json.dumps(c)
        self.assertNotIn("hunter2-not-a-real-password", s); self.assertNotIn("DB_PASSWORD", s); self.assertNotIn("NGINX_CONF", s)
        self.assertTrue(c["resource_state"]["task_definition"]["command_overridden"])

    def test_read_only_allowlist(self):
        aws = cic.Aws("us-east-1")
        for svc, verb in (("ecs", "update-service"), ("ecs", "run-task"), ("cloudwatch", "put-metric-alarm"), ("logs", "delete-log-group"),
                          ("secretsmanager", "get-secret-value"), ("lambda", "get-function-configuration")):
            with self.assertRaises(cic.CollectError, msg=(svc, verb)):
                aws.call(svc, verb, [])
        self.assertEqual(aws.calls, [])    # 거부된 호출은 실행 기록에도 없음
        p, c = self.r()
        for call in c["collection_meta"]["aws_calls"]:
            self.assertTrue(call.split()[1].startswith(cic.ALLOWED_PREFIXES), call)

    def test_missing_source_is_a_warning_not_silence(self):
        p, c = self.r(drop=("logs.filter-log-events.logs",))
        self.assertEqual(p.returncode, 0)
        self.assertTrue(any(w["source"] == "logs" and w["status"] == "error" for w in c["collection_warnings"]))
        self.assertIn("부분 수집", p.stderr)
        self.assertEqual(c["metrics"]["target_5xx_count"]["summary"]["sum"], 32.0)   # 다른 증거는 그대로

    def test_empty_logs_is_not_clean(self):
        p, c = self.r(logs=[])
        w = [x for x in c["collection_warnings"] if x["source"] == "logs"]
        self.assertTrue(w and w[0]["status"] == "empty")

    def test_everything_missing_exits_3(self):
        d = tempfile.mkdtemp(prefix="cic-empty-"); self.dirs = [d]
        out = os.path.join(d, "o", "ctx.json")
        p = subprocess.run([sys.executable, SCRIPT, "--fixture", d, "--out", out, "--now", NOW], capture_output=True, text=True)
        self.assertEqual(p.returncode, 3)
        with open(out, encoding="utf-8") as fh:
            c = json.load(fh)
        self.assertGreater(len(c["collection_warnings"]), 3)    # 파일은 경고를 담아 작성됨

    def test_recent_incident_warns_about_log_lag(self):
        p, c = self.r(now="2026-10-08T11:02:00Z")
        self.assertTrue(any(w["status"] == "lag" for w in c["collection_warnings"]))

    def test_5xx_lines_kept_first_when_logs_are_many(self):
        many = [{"timestamp": ms("2026-10-08T10:58:00Z") + i, "message": '10.0.0.1 - - "GET / HTTP/1.1" 200 3'} for i in range(200)] \
             + [{"timestamp": ms("2026-10-08T10:59:00Z") + i, "message": '10.0.0.1 - - "GET /error HTTP/1.1" 500 41'} for i in range(5)]
        p, c = self.r(logs=many)
        self.assertEqual(sum(1 for x in c["logs"] if '" 500 ' in x["message"]), 5)
        self.assertLessEqual(len(c["logs"]), cic.MAX_LOG_LINES_5XX + cic.MAX_LOG_LINES_OTHER)

if __name__ == "__main__":
    unittest.main(verbosity=2)
