"""analysis_handler.py — 분석 Lambda 입구. 알림 Lambda 가 Telegram 발송에 성공한 뒤 비동기로 부른다.

흐름: 입력 확인 → gate(중복·잠금·쿨다운·일일 상한) → 기다림(로그 도착) → 수집 → 분석 → 평문 전송.
  * ALARM 만 처리한다. 모르는 알람·모르는 입력 모양은 아무것도 안 하고 끝낸다.
  * 수집·모델·전송은 주입한다. 시험은 가짜로, 운영은 make_deps() 의 진짜로.
  * 로그에는 상태 낱말만 남긴다. 맥락·모델 글·오류 원문은 남기지 않는다.
의존성: python3 표준 라이브러리 + boto3(Lambda 런타임 내장).
"""
import dataclasses
import json
import os
import time
from typing import Callable

import analysis_core
import guards

MIN_MS_FOR_MODEL = 30000      # 남은 시간이 이보다 적으면 모델을 부르지 않고 «시간초과»로 알린다


@dataclasses.dataclass
class Config:
    enabled: bool
    alarm_name: str
    cooldown_s: int
    daily_cap: int
    sleep_s: int

    @classmethod
    def from_env(cls, env):
        return cls(enabled=env.get("ANALYSIS_ENABLED", "false").strip().lower() == "true",
                   alarm_name=env.get("ALARM_NAME", ""),
                   cooldown_s=int(env.get("COOLDOWN_MINUTES", "15")) * 60,
                   daily_cap=int(env.get("DAILY_CAP", "20")),
                   sleep_s=int(env.get("SLEEP_SECONDS", "45")))


@dataclasses.dataclass
class Deps:
    store: object                         # guards.DynamoStore / MemoryStore
    collect: Callable[[dict], dict]       # event -> incident context
    invoke_model: Callable                # (prompt, max_tokens) -> analysis_core.ModelResult
    send: Callable[[str], None]           # 평문 한 통 보내기
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.time


def log(status, **kw):
    print(json.dumps({"status": status, **kw}, ensure_ascii=False))


def valid_event(event, cfg):
    return (isinstance(event, dict) and event.get("v") == 1 and event.get("state") == "ALARM"
            and event.get("alarm_name") == cfg.alarm_name and bool(event.get("state_change_time")))


def run(event, cfg, deps, remaining_ms=lambda: 10**9):
    if not cfg.enabled:
        log("disabled"); return {"status": "disabled"}
    if not valid_event(event, cfg):
        log("ignored"); return {"status": "ignored"}
    ok, reason = guards.gate(deps.store, cfg.alarm_name, event["state_change_time"],
                             cfg.cooldown_s, cfg.daily_cap, now=deps.clock())
    if not ok:
        log("skipped", reason=reason); return {"status": "skipped", "reason": reason}
    try:
        deps.sleep(cfg.sleep_s)
        try:
            ctx = deps.collect(event)
        except Exception:
            text = analysis_core.failure_message("수집")
        else:
            if remaining_ms() < MIN_MS_FOR_MODEL:
                text = analysis_core.failure_message("시간초과", ctx)
            else:
                text = analysis_core.analyze(ctx, deps.invoke_model)
        try:
            deps.send(text)
        except Exception as e:      # 원문 대신 오류 종류 이름만
            log("send_failed", error=type(e).__name__); return {"status": "send_failed"}
        log("sent"); return {"status": "sent"}
    finally:
        deps.store.release(guards.LOCK_KEY)


def bedrock_invoker(client, model_id):
    # Bedrock Converse 한 번. 도구 없음 · 재시도는 클라이언트 설정에서 끔. 오류는 코드 이름만 올린다.
    from botocore.exceptions import ReadTimeoutError, ConnectTimeoutError, ClientError

    def invoke(prompt, max_tokens):
        try:
            r = client.converse(modelId=model_id, messages=[{"role": "user", "content": [{"text": prompt}]}],
                                inferenceConfig={"maxTokens": max_tokens})
        except (ReadTimeoutError, ConnectTimeoutError):
            raise analysis_core.ModelTimeout("timeout")
        except ClientError as e:
            raise analysis_core.ModelError(e.response.get("Error", {}).get("Code", "ClientError"))
        texts = [c["text"] for c in r["output"]["message"]["content"] if "text" in c]
        u = r.get("usage", {})
        return analysis_core.ModelResult("".join(texts), u.get("inputTokens", 0), u.get("outputTokens", 0),
                                         r.get("stopReason", ""))
    return invoke


def make_deps(env):
    # 운영용 진짜 의존성. collector·send_plain 은 별도 모듈(같은 zip 에 평평하게 들어감).
    import boto3
    from botocore.config import Config as BotoConfig
    import collector
    from send_plain import send_plain

    region = env["AWS_REGION"]                     # Lambda 런타임이 넣어 줌
    br = boto3.client("bedrock-runtime", region_name=region,
                      config=BotoConfig(retries={"max_attempts": 1}, read_timeout=60, connect_timeout=10))
    secrets = boto3.client("secretsmanager", region_name=region)

    def collect(event):
        return collector.collect_for_alert(collector.AwsBoto3(region), event["alarm_name"], event["state_change_time"],
                                           env["CLUSTER"], env["SERVICE"], env["LOG_GROUP"], mask=True)

    def send(text):
        send_plain(text, env["TELEGRAM_CHAT_ID"], env["TELEGRAM_BOT_TOKEN_SECRET_ARN"], secrets)

    return Deps(store=guards.DynamoStore(boto3.client("dynamodb", region_name=region), env["TABLE"]), collect=collect,
                invoke_model=bedrock_invoker(br, env["MODEL_ID"]), send=send)


def lambda_handler(event, context):
    cfg = Config.from_env(os.environ)
    if not cfg.enabled:
        log("disabled"); return {"status": "disabled"}
    return run(event, cfg, make_deps(os.environ), remaining_ms=context.get_remaining_time_in_millis)
