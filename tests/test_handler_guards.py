"""핸들러·방어 시험 — 가짜 DynamoDB·가짜 Bedrock·가짜 전송. 진짜 AWS 를 부르면 시험이 실패한다."""
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "notifications" / "analysis")]   # 좌석 폴더 · 코스 저장소 둘 다
import analysis_core as A
import guards
import analysis_handler as handler

CTX = json.loads((HERE / "fixtures" / "incident-context.json").read_text(encoding="utf-8"))
LONG_1 = (HERE / "fixtures" / "model-k10b-1.txt").read_text(encoding="utf-8")
ALARM = "agentic-devops-dev-high-5xx"
T0 = dt.datetime(2026, 10, 16, 0, 35, 43, tzinfo=dt.timezone.utc).timestamp()   # 기본 알람 시각 + 45초(기다린 뒤)


def at(sec):
    # T0 기준 sec 초 뒤에 막 바뀐 알람 시각(CloudWatch 본문 형식). 기다림 45초를 빼 둔다.
    return dt.datetime.fromtimestamp(T0 - 45 + sec, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
SECRET = "AKIA" + "ABCDEFGHIJKLMNOP"


def event(state="ALARM", sct="2026-10-16T00:34:58.000+0000", alarm=ALARM):
    return {"v": 1, "alarm_name": alarm, "state": state, "state_change_time": sct,
            "sns_timestamp": "2026-10-16T00:34:59.123Z", "sns_message_id": "m-1", "region": "ap-northeast-2"}


def config(**kw):
    base = dict(enabled=True, alarm_name=ALARM, cooldown_s=900, daily_cap=20, sleep_s=45)
    return handler.Config(**{**base, **kw})


class World:
    """가짜 의존성 묶음. 무엇이 몇 번 불렸는지 기록한다."""
    def __init__(self, model_text=LONG_1, model_error=None, collect_error=None, send_error=None):
        self.store, self.now = guards.MemoryStore(), T0
        self.sent, self.slept, self.collected, self.model_calls = [], [], [], 0
        self.model_text, self.model_error, self.collect_error, self.send_error = model_text, model_error, collect_error, send_error

    def collect(self, ev):
        self.collected.append(ev)
        if self.collect_error:
            raise self.collect_error
        return CTX

    def invoke(self, prompt, max_tokens):
        self.model_calls += 1
        if self.model_error:
            raise self.model_error
        return A.ModelResult(self.model_text)

    def send(self, text):
        if self.send_error:
            raise self.send_error
        self.sent.append(text)

    def deps(self):
        return handler.Deps(store=self.store, collect=self.collect, invoke_model=self.invoke, send=self.send,
                            sleep=self.slept.append, clock=lambda: self.now)


class FakeDynamo:
    """조건부 쓰기 두 가지(put_item·update_item)와 delete_item 만 흉내 낸다."""
    class exceptions:
        class ConditionalCheckFailedException(Exception):
            pass

    def __init__(self):
        self.items = {}

    def put_item(self, TableName, Item, ConditionExpression, ExpressionAttributeValues):
        key, now = Item["pk"]["S"], int(ExpressionAttributeValues[":now"]["N"])
        old = self.items.get(key)
        expired_ok = "expires_at < :now" in ConditionExpression        # 조건식 글자도 본다(돌연변이를 잡으려고)
        if old and not (expired_ok and int(old["expires_at"]) < now):
            raise self.exceptions.ConditionalCheckFailedException()
        self.items[key] = {"expires_at": Item["expires_at"]["N"]}

    def update_item(self, TableName, Key, UpdateExpression, ConditionExpression, ExpressionAttributeValues):
        key, cap = Key["pk"]["S"], int(ExpressionAttributeValues[":cap"]["N"])
        it = self.items.setdefault(key, {"n": 0, "expires_at": ExpressionAttributeValues[":exp"]["N"]})
        if "n < :cap" not in ConditionExpression or it.get("n", 0) >= cap:
            raise self.exceptions.ConditionalCheckFailedException()
        it["n"] = it.get("n", 0) + 1

    def delete_item(self, TableName, Key):
        self.items.pop(Key["pk"]["S"], None)


class HandlerTest(unittest.TestCase):
    def test_alarm_goes_through_wait_collect_analyze_send(self):
        w = World()
        r = handler.run(event(), config(), w.deps())
        self.assertEqual(r["status"], "sent")
        self.assertEqual(w.slept, [45])
        self.assertEqual(w.model_calls, 1)
        self.assertTrue(w.sent[0].startswith(A.HEADER))
        self.assertTrue(w.sent[0].endswith(A.FOOTER))

    def test_only_alarm_state_is_handled(self):
        for st in ("OK", "INSUFFICIENT_DATA"):
            w = World()
            self.assertEqual(handler.run(event(state=st), config(), w.deps())["status"], "ignored")
            self.assertEqual((w.sent, w.collected, w.model_calls), ([], [], 0))

    def test_unknown_alarm_or_shape_is_ignored(self):
        for ev in (event(alarm="other-alarm"), dict(event(), v=2), {}, None, dict(event(), state_change_time="")):
            w = World()
            self.assertEqual(handler.run(ev, config(), w.deps())["status"], "ignored")
            self.assertEqual(w.sent, [])

    def test_stale_alarm_is_skipped_before_touching_anything(self):
        # 킬 스위치로 막혔던 이벤트가 늦게 실행되는 경우(비동기 대기열은 스로틀이면 최대 6시간 재시도)
        w = World()
        w.now += 11 * 60
        self.assertEqual(handler.run(event(), config(), w.deps()), {"status": "skipped", "reason": "stale"})
        self.assertEqual((w.store.d, w.sent, w.model_calls), ({}, [], 0))

    def test_age_boundary_is_ten_minutes(self):
        w = World()
        w.now = T0 - 45 + 600
        self.assertEqual(handler.run(event(), config(), w.deps())["status"], "sent")
        w = World()
        w.now = T0 - 45 + 601
        self.assertEqual(handler.run(event(), config(), w.deps())["reason"], "stale")

    def test_age_limit_comes_from_config(self):
        w = World()
        w.now += 4 * 60
        self.assertEqual(handler.run(event(), config(max_event_age_s=180), w.deps())["reason"], "stale")

    def test_unreadable_time_is_skipped_closed(self):
        for bad in ("t1", "2026-10-16T00:34:58", "어제"):        # 시간대 없는 시각도 나이를 모름
            w = World()
            self.assertEqual(handler.run(event(sct=bad), config(), w.deps()), {"status": "skipped", "reason": "bad_time"})
            self.assertEqual((w.store.d, w.sent), ({}, []))

    def test_other_time_formats_from_cloudwatch_are_read(self):
        for ok in ("2026-10-16T00:34:58.000+0000", "2026-10-16T00:34:58Z", "2026-10-16T00:34:58+00:00"):
            self.assertEqual(handler.event_age_s(ok, T0), 45.0)

    def test_disabled_does_nothing(self):
        w = World()
        self.assertEqual(handler.run(event(), config(enabled=False), w.deps())["status"], "disabled")
        self.assertEqual((w.sent, w.model_calls), ([], 0))

    def test_redelivery_of_same_state_change_is_analyzed_once(self):
        w = World()
        handler.run(event(), config(), w.deps())
        w.now += 300                                   # 늦은 이벤트 창(10분) 안의 재전달은 중복으로 거름
        r = handler.run(event(), config(), w.deps())
        self.assertEqual(r, {"status": "skipped", "reason": "duplicate"})
        self.assertEqual(len(w.sent), 1)

    def test_cooldown_blocks_a_new_alarm_within_15_minutes(self):
        w = World()
        handler.run(event(sct=at(0)), config(), w.deps())
        w.now += 600
        self.assertEqual(handler.run(event(sct=at(600)), config(), w.deps())["reason"], "cooldown")
        w.now += 301
        self.assertEqual(handler.run(event(sct=at(901)), config(), w.deps())["status"], "sent")

    def test_daily_cap(self):
        w = World()
        results = []
        for i in range(22):
            results.append(handler.run(event(sct=at(2 * i)), config(cooldown_s=1), w.deps())["status"])
            w.now += 2
        self.assertEqual(results.count("sent"), 20)
        self.assertEqual(results[-1], "skipped")
        self.assertEqual(w.model_calls, 20)

    def test_second_run_while_one_is_running_is_locked(self):
        w = World()
        w.store.add_once(guards.LOCK_KEY, guards.LOCK_TTL_S, T0)     # 다른 실행이 잠금을 쥔 상태
        self.assertEqual(handler.run(event(), config(), w.deps())["reason"], "locked")
        self.assertEqual(w.model_calls, 0)

    def test_lock_is_released_after_success_and_failure(self):
        for kw in ({}, {"model_error": A.ModelError("x")}, {"collect_error": RuntimeError("x")}, {"send_error": RuntimeError("x")}):
            w = World(**kw)
            handler.run(event(), config(), w.deps())
            self.assertNotIn(guards.LOCK_KEY, w.store.d, kw)

    def test_lock_expires_if_a_run_dies(self):
        w = World()
        w.store.add_once(guards.LOCK_KEY, guards.LOCK_TTL_S, T0)
        w.now += guards.LOCK_TTL_S + 1
        self.assertEqual(handler.run(event(), config(), w.deps())["status"], "sent")

    def test_rejected_by_cooldown_does_not_keep_the_lock(self):
        w = World()
        handler.run(event(sct=at(0)), config(), w.deps())
        handler.run(event(sct=at(1)), config(), w.deps())           # cooldown
        self.assertNotIn(guards.LOCK_KEY, w.store.d)

    def test_collect_failure_sends_failure_message_without_model_call(self):
        w = World(collect_error=RuntimeError(f"AccessDenied {SECRET}"))
        handler.run(event(), config(), w.deps())
        self.assertEqual(w.model_calls, 0)
        self.assertIn("자동 분석 실패(코드: 수집)", w.sent[0])
        self.assertNotIn(SECRET, w.sent[0])
        self.assertTrue(w.sent[0].endswith(A.FOOTER))

    def test_model_failure_message_has_no_secret(self):
        w = World(model_error=A.ModelError(SECRET))
        handler.run(event(), config(), w.deps())
        self.assertIn("코드: 모델", w.sent[0])
        self.assertNotIn(SECRET, w.sent[0])

    def test_little_time_left_skips_model_and_says_timeout(self):
        w = World()
        handler.run(event(), config(), w.deps(), remaining_ms=lambda: 5000)
        self.assertEqual(w.model_calls, 0)
        self.assertIn("코드: 시간초과", w.sent[0])

    def test_send_failure_is_logged_by_name_only(self):
        import io, contextlib
        w = World(send_error=RuntimeError(f"bot token {SECRET}"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r = handler.run(event(), config(), w.deps())
        self.assertEqual(r["status"], "send_failed")
        self.assertNotIn(SECRET, buf.getvalue())

    def test_logs_never_contain_model_text_or_context(self):
        import io, contextlib
        w = World()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            handler.run(event(), config(), w.deps())
        self.assertNotIn("Possible cause", buf.getvalue())
        self.assertNotIn(CTX["service"]["name"], buf.getvalue())

    def test_config_from_env_defaults_off(self):
        c = handler.Config.from_env({})
        self.assertFalse(c.enabled)
        self.assertEqual((c.cooldown_s, c.daily_cap, c.sleep_s, c.max_event_age_s), (900, 20, 45, 600))
        self.assertEqual(handler.Config.from_env({"MAX_EVENT_AGE_MINUTES": "3"}).max_event_age_s, 180)
        self.assertTrue(handler.Config.from_env({"ANALYSIS_ENABLED": " TRUE "}).enabled)


class DynamoStoreTest(unittest.TestCase):
    def test_gate_with_dynamo_store(self):
        s = guards.DynamoStore(FakeDynamo(), "t")
        self.assertEqual(guards.gate(s, ALARM, "t1", 900, 20, now=T0), (True, "ok"))
        s.release(guards.LOCK_KEY)
        self.assertEqual(guards.gate(s, ALARM, "t1", 900, 20, now=T0 + 5), (False, "duplicate"))
        self.assertEqual(guards.gate(s, ALARM, "t2", 900, 20, now=T0 + 5), (False, "cooldown"))
        self.assertNotIn(guards.LOCK_KEY, s.c.items)

    def test_expired_item_can_be_written_again(self):
        s = guards.DynamoStore(FakeDynamo(), "t")
        self.assertEqual([s.add_once("k", 10, T0), s.add_once("k", 10, T0 + 5), s.add_once("k", 10, T0 + 11)], [True, False, True])

    def test_daily_counter_stops_at_cap(self):
        s = guards.DynamoStore(FakeDynamo(), "t")
        self.assertEqual([s.incr_upto("day#x", 2, 60, T0) for _ in range(3)], [True, True, False])


class MakeDepsTest(unittest.TestCase):
    """운영 배선을 가짜 boto3·collector·send_plain 으로 확인한다(진짜 AWS 0)."""
    ENV = {"AWS_REGION": "ap-northeast-2", "MODEL_ID": "m", "TABLE": "tbl", "CLUSTER": "c", "SERVICE": "s",
           "LOG_GROUP": "/lg", "TELEGRAM_CHAT_ID": "42", "TELEGRAM_BOT_TOKEN_SECRET_ARN": "arn:secret"}

    def test_wiring_passes_event_and_env_to_collector_modules(self):
        import types
        from unittest import mock
        seen = {}
        fake_boto3 = types.SimpleNamespace(client=lambda name, **kw: seen.setdefault(f"client:{name}", (name, kw)))
        fake_collector = types.SimpleNamespace(
            AwsBoto3=lambda region: ("aws", region),
            collect_for_alert=lambda *a, **kw: seen.setdefault("collect", (a, kw)) and CTX)
        fake_send = types.SimpleNamespace(send_plain=lambda *a: seen.setdefault("send", a))
        with mock.patch.dict(sys.modules, {"boto3": fake_boto3, "collector": fake_collector, "send_plain": fake_send}):
            deps = handler.make_deps(self.ENV)
            deps.collect(event())
            deps.send("본문")
        a, kw = seen["collect"]
        self.assertEqual(a, (("aws", "ap-northeast-2"), ALARM, "2026-10-16T00:34:58.000+0000", "c", "s", "/lg"))
        self.assertEqual(kw, {"mask": True})
        self.assertEqual(seen["send"][:3], ("본문", "42", "arn:secret"))
        self.assertEqual(deps.store.t, "tbl")
        for name in ("bedrock-runtime", "secretsmanager", "dynamodb"):
            self.assertEqual(seen[f"client:{name}"][1]["region_name"], "ap-northeast-2")


    def test_bedrock_client_makes_exactly_one_attempt(self):
        # 모델 호출은 한 번만(호출당 비용 상한). 진짜 botocore 로 클라이언트를 만들어(네트워크 0) 정규화된 값을 본다.
        try:
            import botocore.session
        except ImportError:
            self.skipTest("botocore 없음")
        import types
        from unittest import mock
        seen = {}
        fake_boto3 = types.SimpleNamespace(client=lambda name, **kw: seen.setdefault(name, kw))
        fake_collector = types.SimpleNamespace(AwsBoto3=lambda region: None, collect_for_alert=lambda *a, **kw: CTX)
        fake_send = types.SimpleNamespace(send_plain=lambda *a: None)
        with mock.patch.dict(sys.modules, {"boto3": fake_boto3, "collector": fake_collector, "send_plain": fake_send}):
            handler.make_deps(self.ENV)
        real = botocore.session.get_session().create_client(
            "bedrock-runtime", region_name="ap-northeast-2", aws_access_key_id="x", aws_secret_access_key="x",
            config=seen["bedrock-runtime"]["config"])
        self.assertEqual(real.meta.config.retries["total_max_attempts"], 1)


class BedrockInvokerTest(unittest.TestCase):
    def test_converse_request_and_result(self):
        class C:
            def converse(self, **kw):
                self.kw = kw
                return {"output": {"message": {"content": [{"text": "가"}, {"text": "나"}]}},
                        "stopReason": "max_tokens", "usage": {"inputTokens": 5, "outputTokens": 7}}
        c = C()
        r = handler.bedrock_invoker(c, "model-x")("질문", 1500)
        self.assertEqual((r.text, r.input_tokens, r.output_tokens, r.stop_reason), ("가나", 5, 7, "max_tokens"))
        self.assertEqual(c.kw["inferenceConfig"], {"maxTokens": 1500})
        self.assertNotIn("toolConfig", c.kw)

    def test_errors_become_model_error_with_code_only(self):
        from botocore.exceptions import ClientError, ReadTimeoutError

        class C:
            def __init__(self, e): self.e = e
            def converse(self, **kw): raise self.e
        denied = ClientError({"Error": {"Code": "AccessDeniedException", "Message": SECRET}}, "Converse")
        with self.assertRaises(A.ModelError) as cm:
            handler.bedrock_invoker(C(denied), "m")("p", 10)
        self.assertEqual(str(cm.exception), "AccessDeniedException")
        with self.assertRaises(A.ModelTimeout):
            handler.bedrock_invoker(C(ReadTimeoutError(endpoint_url="x")), "m")("p", 10)


if __name__ == "__main__":
    unittest.main()
