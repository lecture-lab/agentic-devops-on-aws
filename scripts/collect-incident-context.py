#!/usr/bin/env python3
"""collect-incident-context.py — 알림 뒤에 사람이 로컬에서 돌려 incident-context.json 을 만든다.

원칙
  * AWS 는 읽기 전용만 부른다(describe-/get-/list-/filter-). 수정·삭제·실행 호출 0. 코드에 허용 목록이 있고 시험으로 지킨다.
  * 관측된 사실만 담는다. 원인 판단(root cause)은 하지 않는다 — 그건 분석 단계(Claude Code)의 일이다.
  * 못 모은 증거는 collection_warnings 에 남긴다. 조용한 빈 칸 없음.
  * 계정 ID 와 클라이언트(공인) IP 주소는 기본으로 가린다(--no-mask 로 끔). 비밀 모양 문자열은 --no-mask 여도 항상 가린다.
  * 비밀값·환경변수 전체·Lambda/Secrets 는 건드리지 않는다. task definition 의 environment 는 복사하지 않는다.
의존성: python3 (표준 라이브러리만) + aws CLI. AWS_PROFILE / 리전 환경변수를 그대로 쓴다.

종료 코드: 0 = 파일 작성(경고는 파일과 stderr 에 있음) · 3 = 모든 증거 수집 실패(파일은 경고만 담아 작성) · 1 = 사용법/내부 오류
"""
import argparse, datetime as dt, json, os, sys, tempfile

# 증거를 모으고 가리는 코드는 같은 폴더의 collector.py 에 있다(알림 뒤 자동 분석 Lambda 도 같은 모듈을 쓴다).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collector

globals().update({k: v for k, v in vars(collector).items() if not k.startswith("__")})   # 시험·예전 코드가 쓰던 이름 그대로 노출


def main(argv=None):
    ap = argparse.ArgumentParser(description="Incident 증거를 읽기 전용으로 모아 incident-context.json 을 만든다.")
    ap.add_argument("--alarm", default=DEFAULT_ALARM)
    ap.add_argument("--cluster", default=DEFAULT_CLUSTER)
    ap.add_argument("--service", default=DEFAULT_SERVICE)
    ap.add_argument("--log-group", default=DEFAULT_LOG_GROUP)
    ap.add_argument("--region", default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or DEFAULT_REGION)
    ap.add_argument("--profile", default=None, help="지정 안 하면 AWS_PROFILE 환경변수를 aws CLI 가 그대로 사용")
    ap.add_argument("--at", default=None, help="사건 시각(ISO8601). 기본: 알람이 ALARM 이면 그 상태 변경 시각, 아니면 지금")
    ap.add_argument("--out", default=None, help="기본: <repo>/agent/context/incident-context.json")
    ap.add_argument("--no-mask", action="store_true", help="계정 ID·클라이언트 IP 가리기를 끔(비밀 모양 문자열은 항상 가림)")
    ap.add_argument("--fixture", default=None, help="시험용: aws 호출 대신 이 폴더의 JSON 을 읽음")
    ap.add_argument("--now", default=None, help="시험용: 현재 시각 고정")
    for _s in (sys.stdout, sys.stderr):  # 영문 Windows(cp1252) 콘솔에서 한국어 출력이 UnicodeEncodeError 로 죽지 않게
        try:
            _s.reconfigure(errors="replace")
        except Exception:
            pass
    args = ap.parse_args(argv)
    now = parse_time(args.now) if args.now else dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    out_path = args.out or os.path.join(root, "agent", "context", "incident-context.json")
    aws = AwsCli(args.region, args.profile, args.fixture)
    ctx, warnings = build(args, aws, now)
    me = source_sha16(os.path.abspath(__file__), collector.__file__)   # 이 파일 + collector.py
    ctx, counter = finalize(ctx, aws, args.region, now, not args.no_mask, me)
    m = ctx["metrics"]
    got = [ctx["trigger"].get("state") is not None,
           any((m.get(k) or {}).get("summary") for k in ("target_5xx_count", "target_4xx_count", "request_count", "ecs_cpu_average_percent")),
           bool(ctx["logs"]), bool(ctx["resource_state"])]
    all_failed = not any(got)  # 증거를 하나도 못 모았다
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(out_path), prefix=".incident-context.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(ctx, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, out_path)
    n = len(ctx["collection_warnings"])
    print("incident-context.json 작성: %s" % out_path)
    print("사건 시각 %s · 경고 %d건 · 가린 것: 계정ID %d, 비밀모양 %d, 클라이언트 IP %d(서로 다른 주소 %d)" % (
        ctx["timestamp"], n, counter["account_ids"], counter["secret_shapes"], counter["client_ip_replacements"], len(counter.get("_ip_index", {}))))
    if n:
        print("⚠️ 부분 수집 — 아래 증거는 비었거나 못 모았습니다. 분석은 불완전할 수 있습니다:", file=sys.stderr)
        for w in ctx["collection_warnings"]:
            print("  - [%s/%s] %s" % (w["source"], w["status"], w["detail"]), file=sys.stderr)
    return 3 if all_failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CollectError as e:
        print("오류: %s" % e, file=sys.stderr)
        sys.exit(1)
