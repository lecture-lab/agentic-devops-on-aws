#!/usr/bin/env python3
"""collector.py 호출층 시험 — 네트워크·AWS 호출 0.
boto3 판(AwsBoto3)이 실제 서비스 모델 기준으로 «올바른 매개변수»를 보내는지는 botocore Stubber 로 확인한다(요청이 모델에 안 맞으면 Stubber 가 예외).
boto3 가 없는 환경에서는 그 시험만 건너뛴다."""
import datetime as dt, json, os, subprocess, sys, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import collector

try:
    import boto3
    from botocore.stub import Stubber
    HAVE_BOTO3 = True
except ImportError:
    HAVE_BOTO3 = False

REGION = "ap-northeast-2"
ACCT = "123456789012"
NOW = dt.datetime(2026, 10, 20, 12, 0, 0, tzinfo=dt.timezone.utc)
AT = dt.datetime(2026, 10, 20, 11, 0, 0, tzinfo=dt.timezone.utc)
TG_ARN = "arn:aws:elasticloadbalancing:%s:%s:targetgroup/agentic-devops-dev-app-tg/abc123" % (REGION, ACCT)
TD_ARN = "arn:aws:ecs:%s:%s:task-definition/agentic-devops-dev-app:5" % (REGION, ACCT)
ARGS = dict(alarm="agentic-devops-dev-high-5xx", cluster="agentic-devops-dev-cluster",
            service="agentic-devops-dev-app-service", log_group="/ecs/agentic-devops-dev-app")


def ms(t):
    return int(t.timestamp() * 1000)


class FakeClient:
    """verb 이름 → 응답. 부른 기록과 받은 매개변수를 남긴다."""
    def __init__(self, responses):
        self.responses, self.seen = responses, []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        def call(**kw):
            self.seen.append((name, kw))
            r = self.responses[name]
            if isinstance(r, Exception):
                raise r
            return r
        return call


class JsonableTests(unittest.TestCase):
    def test_datetime_becomes_utc_iso_string_and_metadata_dropped(self):
        kst = dt.timezone(dt.timedelta(hours=9))
        out = collector._jsonable({"ResponseMetadata": {"RequestId": "x"}, "t": dt.datetime(2026, 10, 20, 9, 0, tzinfo=kst),
                                   "n": [dt.datetime(2026, 10, 20, 0, 0)], "k": 1})
        self.assertEqual(out, {"t": "2026-10-20T00:00:00+00:00", "n": ["2026-10-20T00:00:00+00:00"], "k": 1})
        json.dumps(out)


class AllowListTests(unittest.TestCase):
    def test_boto3_layer_refuses_non_read_calls_before_touching_a_client(self):
        fake = FakeClient({})
        aws = collector.AwsBoto3(REGION, clients={"ecs": fake, "logs": fake, "cloudwatch": fake, "secretsmanager": fake, "lambda": fake})
        for svc, verb in (("ecs", "update-service"), ("ecs", "run-task"), ("cloudwatch", "put-metric-alarm"), ("logs", "delete-log-group"),
                          ("secretsmanager", "get-secret-value"), ("lambda", "get-function-configuration")):
            with self.assertRaises(collector.CollectError, msg=(svc, verb)):
                aws.call(svc, verb, {})
        self.assertEqual(aws.calls, [])
        self.assertEqual(fake.seen, [])


class ErrorMappingTests(unittest.TestCase):
    def test_error_text_carries_the_code_only(self):
        class Boom(Exception):
            response = {"Error": {"Code": "AccessDeniedException", "Message": "User arn:aws:iam::123456789012:user/x secret=hunter2 is not authorized"}}
        aws = collector.AwsBoto3(REGION, clients={"logs": FakeClient({"filter_log_events": Boom("raw message hunter2")})})
        with self.assertRaises(collector.CollectError) as cm:
            aws.call("logs", "filter-log-events", {"logGroupName": "x"})
        msg = str(cm.exception)
        self.assertIn("AccessDeniedException", msg)
        self.assertNotIn("hunter2", msg); self.assertNotIn(ACCT, msg)

    def test_a_failed_source_becomes_a_warning_not_silence(self):
        class Boom(Exception):
            response = {"Error": {"Code": "ThrottlingException"}}
        clients = {"cloudwatch": FakeClient({"describe_alarms": Boom(), "describe_alarm_history": Boom(), "get_metric_statistics": Boom()}),
                   "logs": FakeClient({"filter_log_events": Boom()}), "ecs": FakeClient({"describe_services": Boom()})}
        ctx, counter = collector.collect_incident_context(collector.AwsBoto3(REGION, clients=clients), region=REGION, now=NOW, at=AT, **ARGS)
        sources = {w["source"]: w["status"] for w in ctx["collection_warnings"]}
        self.assertEqual(sources.get("cloudwatch.alarm"), "error")
        self.assertEqual(sources.get("logs"), "error")
        self.assertEqual(sources.get("ecs.service"), "error")
        json.dumps(ctx)


class CliParamsTests(unittest.TestCase):
    def test_cli_layer_sends_the_same_params_dict_through_cli_input_json(self):
        seen = {}
        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")
        with mock.patch.object(collector.subprocess, "run", fake_run):
            params = {"logGroupName": "/ecs/x", "startTime": 1, "endTime": 2, "limit": 500}
            collector.AwsCli(REGION, profile=None).call("logs", "filter-log-events", params)
        cmd = seen["cmd"]
        self.assertEqual(cmd[:3], ["aws", "logs", "filter-log-events"])
        self.assertIn("--no-paginate", cmd)           # 첫 쪽만(limit 500) — 예전 --max-items 500 과 같은 상한
        self.assertEqual(json.loads(cmd[cmd.index("--cli-input-json") + 1]), params)


@unittest.skipUnless(HAVE_BOTO3, "boto3 가 없어 Stubber 시험을 건너뜀")
class StubbedBoto3Tests(unittest.TestCase):
    def setUp(self):
        self.clients, self.stubs = {}, {}
        for svc in ("cloudwatch", "logs", "ecs", "elbv2"):
            c = boto3.client(svc, region_name=REGION, aws_access_key_id="x", aws_secret_access_key="y")
            s = Stubber(c); self.clients[svc], self.stubs[svc] = c, s

    def run_collect(self):
        for s in self.stubs.values():
            s.activate()
        aws = collector.AwsBoto3(REGION, clients=self.clients)
        return collector.collect_incident_context(aws, region=REGION, now=NOW, at=None, **{k: v for k, v in ARGS.items()}), aws

    def test_every_request_matches_the_real_service_model_and_ctx_has_the_cli_shape(self):
        cw, lg, ecs, elb = (self.stubs[k] for k in ("cloudwatch", "logs", "ecs", "elbv2"))
        dims = [{"Name": "LoadBalancer", "Value": "app/agentic-devops-dev-alb/abc"}, {"Name": "TargetGroup", "Value": "targetgroup/agentic-devops-dev-app-tg/abc123"}]
        cw.add_response("describe_alarms", {"MetricAlarms": [{
            "AlarmName": ARGS["alarm"], "StateValue": "ALARM", "StateReason": "Threshold Crossed", "StateUpdatedTimestamp": AT,
            "MetricName": "HTTPCode_Target_5XX_Count", "Namespace": "AWS/ApplicationELB", "ComparisonOperator": "GreaterThanOrEqualToThreshold",
            "Threshold": 1.0, "Period": 60, "EvaluationPeriods": 1, "Statistic": "Sum", "Dimensions": dims}]},
            {"AlarmNames": [ARGS["alarm"]]})
        cw.add_response("describe_alarm_history", {"AlarmHistoryItems": [{"Timestamp": AT, "HistorySummary": "Alarm updated from OK to ALARM"}]},
                        {"AlarmName": ARGS["alarm"], "HistoryItemType": "StateUpdate", "StartDate": "2026-10-20T10:00:00Z",
                         "EndDate": "2026-10-20T11:05:00Z", "MaxRecords": 20})
        for name, v in (("HTTPCode_Target_5XX_Count", 6.0), ("HTTPCode_Target_4XX_Count", 0.0), ("RequestCount", 8.0)):
            cw.add_response("get_metric_statistics", {"Datapoints": [{"Timestamp": AT, "Sum": v}]},
                            {"Namespace": "AWS/ApplicationELB", "MetricName": name, "StartTime": "2026-10-20T10:45:00Z", "EndTime": "2026-10-20T11:05:00Z",
                             "Period": 60, "Statistics": ["Sum"], "Dimensions": dims})
        cw.add_response("get_metric_statistics", {"Datapoints": [{"Timestamp": AT, "Average": 0.18}]},
                        {"Namespace": "AWS/ECS", "MetricName": "CPUUtilization", "StartTime": "2026-10-20T10:45:00Z", "EndTime": "2026-10-20T11:05:00Z",
                         "Period": 60, "Statistics": ["Average"],
                         "Dimensions": [{"Name": "ClusterName", "Value": ARGS["cluster"]}, {"Name": "ServiceName", "Value": ARGS["service"]}]})
        lg.add_response("filter_log_events", {"events": [
            {"timestamp": ms(AT), "message": '10.20.1.5 - - [20/Oct/2026:11:00:00 +0000] "GET /error HTTP/1.1" 500 41 "-" "curl/8.18.0" "8.8.8.8"'}]},
            {"logGroupName": ARGS["log_group"], "startTime": ms(AT - dt.timedelta(minutes=10)), "endTime": ms(AT + dt.timedelta(minutes=5)), "limit": 500})
        ecs.add_response("describe_services", {"services": [{
            "serviceName": ARGS["service"], "status": "ACTIVE", "desiredCount": 2, "runningCount": 2, "pendingCount": 0, "taskDefinition": TD_ARN,
            "deployments": [{"id": "ecs-svc/1", "status": "PRIMARY", "rolloutState": "COMPLETED", "taskDefinition": TD_ARN, "desiredCount": 2,
                             "runningCount": 2, "createdAt": AT - dt.timedelta(minutes=7), "updatedAt": AT}],
            "events": [], "loadBalancers": [{"targetGroupArn": TG_ARN}]}], "failures": []},
            {"cluster": ARGS["cluster"], "services": [ARGS["service"]]})
        ecs.add_response("describe_task_definition", {"taskDefinition": {
            "family": "agentic-devops-dev-app", "revision": 5, "registeredAt": AT - dt.timedelta(minutes=8),
            "containerDefinitions": [{"name": "app", "image": "public.ecr.aws/nginx/nginx:1.30", "command": ["sh"]}]}}, {"taskDefinition": TD_ARN})
        elb.add_response("describe_target_health", {"TargetHealthDescriptions": [{"TargetHealth": {"State": "healthy"}}]}, {"TargetGroupArn": TG_ARN})
        (ctx, counter), aws = self.run_collect()
        for s in self.stubs.values():
            s.assert_no_pending_responses()          # 준비한 일곱 종류 호출이 전부 실제로 나갔다
        self.assertEqual(ctx["trigger"]["state"], "ALARM")
        self.assertIsInstance(ctx["trigger"]["state_updated"], str)      # 시각은 문자열(aws CLI 출력과 같은 모양)
        self.assertEqual(ctx["metrics"]["target_5xx_count"]["summary"]["sum"], 6.0)
        self.assertEqual(ctx["logs_meta"]["http_5xx_path_counts"], {"/error": 1})
        self.assertEqual(ctx["resource_state"]["task_definition"]["revision"], "agentic-devops-dev-app:5")
        self.assertEqual(ctx["resource_state"]["alb_target_health"], {"healthy": 1})
        self.assertIn("<client-ip-1>", json.dumps(ctx))                  # 가리기는 같은 코드
        self.assertNotIn("8.8.8.8", json.dumps(ctx)); self.assertNotIn(ACCT, json.dumps(ctx))
        self.assertEqual(sorted(set(aws.calls)), ["cloudwatch describe-alarm-history", "cloudwatch describe-alarms", "cloudwatch get-metric-statistics",
                                                  "ecs describe-services", "ecs describe-task-definition", "elbv2 describe-target-health",
                                                  "logs filter-log-events"])
        self.assertEqual(ctx["collection_meta"]["tool"], "collect-incident-context")
        json.dumps(ctx)



class CollectForAlertTests(unittest.TestCase):
    """Lambda 입구: 이벤트의 StateChangeTime 문자열을 사건 시각으로 쓰고 ctx 딕셔너리만 돌려준다."""

    def clients(self):
        class Boom(Exception):
            response = {"Error": {"Code": "ResourceNotFoundException"}}
        return {"cloudwatch": FakeClient({"describe_alarms": {"MetricAlarms": []}, "describe_alarm_history": {"AlarmHistoryItems": []},
                                          "get_metric_statistics": {"Datapoints": []}}),
                "logs": FakeClient({"filter_log_events": {"events": []}}), "ecs": FakeClient({"describe_services": Boom()})}

    def test_returns_a_dict_and_uses_the_cloudwatch_state_change_time_format(self):
        aws = collector.AwsBoto3(REGION, clients=self.clients())
        ctx = collector.collect_for_alert(aws, ARGS["alarm"], "2026-10-20T11:00:00.000+0000", ARGS["cluster"], ARGS["service"], ARGS["log_group"], now=NOW)
        self.assertIsInstance(ctx, dict)
        self.assertEqual(ctx["timestamp"], "2026-10-20T11:00:00Z")
        self.assertEqual(ctx["incident_id"], "inc-20261020T110000Z")
        self.assertEqual(ctx["collection_meta"]["region"], REGION)
        self.assertTrue(ctx["collection_meta"]["masking"]["account_id_masked"])
        self.assertIn("collection_warnings", ctx)
        json.dumps(ctx)

    def test_empty_state_change_time_is_refused(self):
        aws = collector.AwsBoto3(REGION, clients=self.clients())
        for bad in ("", None):
            with self.assertRaises(ValueError):
                collector.collect_for_alert(aws, ARGS["alarm"], bad, ARGS["cluster"], ARGS["service"], ARGS["log_group"], now=NOW)

if __name__ == "__main__":
    unittest.main()
