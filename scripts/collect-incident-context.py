#!/usr/bin/env python3
"""collect-incident-context.py — 알림 뒤에 사람이 로컬에서 돌려 incident-context.json 을 만든다.

원칙
  * AWS 는 읽기 전용만 부른다(describe-/get-/list-/filter-). 수정·삭제·실행 호출 0. 코드에 허용 목록이 있고 시험으로 지킨다.
  * 관측된 사실만 담는다. 원인 판단(root cause)은 하지 않는다 — 그건 분석 단계(Claude Code)의 일이다.
  * 못 모은 증거는 collection_warnings 에 남긴다. 조용한 빈 칸 없음.
  * 계정 ID 는 기본으로 가린다(--no-mask 로 끔). 비밀 모양 문자열은 --no-mask 여도 항상 가린다.
  * 비밀값·환경변수 전체·Lambda/Secrets 는 건드리지 않는다. task definition 의 environment 는 복사하지 않는다.
의존성: python3 (표준 라이브러리만) + aws CLI. AWS_PROFILE / 리전 환경변수를 그대로 쓴다.

종료 코드: 0 = 파일 작성(경고는 파일과 stderr 에 있음) · 3 = 모든 증거 수집 실패(파일은 경고만 담아 작성) · 1 = 사용법/내부 오류
"""
import argparse, datetime as dt, hashlib, json, os, re, subprocess, sys, tempfile

TOOL = "collect-incident-context"
TOOL_VERSION = "0.1"
ALLOWED_PREFIXES = ("describe-", "get-", "list-", "filter-")
ALLOWED_SERVICES = {"cloudwatch", "logs", "ecs", "elbv2"}
DEFAULT_ALARM = "agentic-devops-dev-high-5xx"
DEFAULT_CLUSTER = "agentic-devops-dev-cluster"
DEFAULT_SERVICE = "agentic-devops-dev-app-service"
DEFAULT_LOG_GROUP = "/ecs/agentic-devops-dev-app"
DEFAULT_REGION = "us-east-1"
MAX_LOG_LINES_5XX = 30
MAX_LOG_LINES_OTHER = 20
MAX_LINE_CHARS = 300


class CollectError(Exception):
    pass


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(s):
    if s in (None, "", "now"):
        return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    s = s.strip().replace("Z", "+00:00")
    t = dt.datetime.fromisoformat(s)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc)


class Aws:
    """aws CLI 읽기 전용 래퍼. 허용 목록 밖 호출은 실행 전에 거부한다. --fixture 면 파일에서 읽는다(시험용)."""

    def __init__(self, region, profile=None, fixture_dir=None):
        self.region, self.profile, self.fixture_dir = region, profile, fixture_dir
        self.calls = []

    def call(self, service, verb, args, label=None):
        if service not in ALLOWED_SERVICES or not verb.startswith(ALLOWED_PREFIXES):
            raise CollectError("읽기 전용이 아닌 호출 거부: aws %s %s" % (service, verb))
        self.calls.append("%s %s" % (service, verb))
        if self.fixture_dir:
            name = "%s.%s%s.json" % (service, verb, ("." + label) if label else "")
            path = os.path.join(self.fixture_dir, name)
            if not os.path.isfile(path):
                raise CollectError("fixture 없음: " + name)
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        cmd = ["aws", service, verb, "--region", self.region, "--output", "json", "--no-cli-pager"] + list(args)
        if self.profile:
            cmd += ["--profile", self.profile]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        except FileNotFoundError:
            raise CollectError("aws CLI 를 찾지 못함")
        except subprocess.TimeoutExpired:
            raise CollectError("aws %s %s 시간 초과(90초)" % (service, verb))
        if p.returncode != 0:
            first = (p.stderr.strip().splitlines() or ["(오류 출력 없음)"])[0]
            raise CollectError("aws %s %s 실패 rc=%d: %s" % (service, verb, p.returncode, first[:200]))
        try:
            return json.loads(p.stdout) if p.stdout.strip() else {}
        except ValueError:
            raise CollectError("aws %s %s 출력이 JSON 이 아님" % (service, verb))


def warn(warnings, source, status, detail):
    warnings.append({"source": source, "status": status, "detail": detail})


# ---------- 수집기 ----------
def collect_alarm(aws, alarm_name, at, warnings):
    out = {"name": alarm_name}
    try:
        r = aws.call("cloudwatch", "describe-alarms", ["--alarm-names", alarm_name], label="alarm")
        alarms = r.get("MetricAlarms", [])
        if not alarms:
            warn(warnings, "cloudwatch.alarm", "missing", "알람 %s 이(가) 없음" % alarm_name)
            return out, None
        a = alarms[0]
        out.update({"type": "cloudwatch_alarm", "state": a.get("StateValue"), "state_reason": a.get("StateReason"),
                    "state_updated": a.get("StateUpdatedTimestamp"), "metric": a.get("MetricName"),
                    "namespace": a.get("Namespace"), "comparison": a.get("ComparisonOperator"),
                    "threshold": a.get("Threshold"), "period_seconds": a.get("Period"),
                    "evaluation_periods": a.get("EvaluationPeriods"), "statistic": a.get("Statistic")})
        dims = {d["Name"]: d["Value"] for d in a.get("Dimensions", [])}
        out["dimensions"] = dims
        return out, a
    except CollectError as e:
        warn(warnings, "cloudwatch.alarm", "error", str(e))
        return out, None


def collect_alarm_history(aws, alarm_name, at, warnings):
    try:
        start, end = at - dt.timedelta(minutes=60), at + dt.timedelta(minutes=5)
        r = aws.call("cloudwatch", "describe-alarm-history",
                     ["--alarm-name", alarm_name, "--history-item-type", "StateUpdate",
                      "--start-date", iso(start), "--end-date", iso(end), "--max-records", "20"], label="history")
        items = [{"at": h.get("Timestamp"), "summary": h.get("HistorySummary")} for h in r.get("AlarmHistoryItems", [])]
        if not items:
            warn(warnings, "cloudwatch.alarm_history", "empty", "지난 60분 상태 변화 기록 없음")
        return items
    except CollectError as e:
        warn(warnings, "cloudwatch.alarm_history", "error", str(e))
        return []


def metric_points(aws, ns, name, dims, stat, start, end, label, warnings, source):
    try:
        args = ["--namespace", ns, "--metric-name", name, "--start-time", iso(start), "--end-time", iso(end),
                "--period", "60", "--statistics", stat, "--dimensions"] + ["Name=%s,Value=%s" % (k, v) for k, v in dims.items()]
        r = aws.call("cloudwatch", "get-metric-statistics", args, label=label)
        pts = sorted(({"t": p.get("Timestamp"), "v": p.get(stat)} for p in r.get("Datapoints", [])), key=lambda x: x["t"] or "")
        if not pts:
            warn(warnings, source, "empty", "%s 데이터 포인트 없음(%s~%s) — 0 이라는 뜻이 아님" % (name, iso(start), iso(end)))
        return pts
    except CollectError as e:
        warn(warnings, source, "error", str(e))
        return None


def summarize(pts):
    if not pts:
        return None
    vals = [p["v"] for p in pts if p["v"] is not None]
    return {"points": len(pts), "sum": sum(vals), "max": max(vals)} if vals else None


def collect_metrics(aws, alarm_obj, cluster, service, at, warnings):
    start, end = at - dt.timedelta(minutes=15), at + dt.timedelta(minutes=5)
    res = {"window": {"start": iso(start), "end": iso(end), "period_seconds": 60}}
    dims = (alarm_obj or {}).get("dimensions") or {}
    alb = {k: dims[k] for k in ("LoadBalancer", "TargetGroup") if k in dims}
    if len(alb) == 2:
        for key, name in (("target_5xx_count", "HTTPCode_Target_5XX_Count"), ("target_4xx_count", "HTTPCode_Target_4XX_Count"),
                          ("request_count", "RequestCount")):
            pts = metric_points(aws, "AWS/ApplicationELB", name, alb, "Sum", start, end, key, warnings, "metrics." + key)
            res[key] = {"series": pts, "summary": summarize(pts)} if pts is not None else None
    else:
        warn(warnings, "metrics.alb", "missing", "알람 dimension 에서 LoadBalancer/TargetGroup 을 얻지 못해 ALB 지표를 건너뜀")
    ecs_dims = {"ClusterName": cluster, "ServiceName": service}
    pts = metric_points(aws, "AWS/ECS", "CPUUtilization", ecs_dims, "Average", start, end, "ecs_cpu", warnings, "metrics.ecs_cpu")
    res["ecs_cpu_average_percent"] = {"series": pts, "summary": summarize(pts)} if pts is not None else None
    return res


STATUS_RE = re.compile(r'"\s*(?:GET|POST|PUT|DELETE|HEAD|PATCH|OPTIONS)\s+(\S+)[^"]*"\s+(\d{3})\b')


def collect_logs(aws, log_group, at, warnings):
    start, end = at - dt.timedelta(minutes=10), at + dt.timedelta(minutes=5)
    try:
        r = aws.call("logs", "filter-log-events",
                     ["--log-group-name", log_group, "--start-time", str(int(start.timestamp() * 1000)),
                      "--end-time", str(int(end.timestamp() * 1000)), "--max-items", "500"], label="logs")
    except CollectError as e:
        warn(warnings, "logs", "error", str(e))
        return [], None
    events = r.get("events", [])
    if not events:
        warn(warnings, "logs", "empty", "로그 창(%s~%s)에 이벤트 없음 — 로그가 아직 안 도착했을 수 있고, 일어나지 않았다는 뜻이 아님" % (iso(start), iso(end)))
    by_status, by_path_5xx = {}, {}
    five, other = [], []
    for ev in events:
        msg = (ev.get("message") or "").rstrip("\n")
        m = STATUS_RE.search(msg)
        item = {"t": iso(dt.datetime.fromtimestamp(ev.get("timestamp", 0) / 1000, dt.timezone.utc)) if ev.get("timestamp") else None,
                "message": msg[:MAX_LINE_CHARS]}
        if m:
            code = m.group(2)
            by_status[code] = by_status.get(code, 0) + 1
            if code.startswith("5"):
                by_path_5xx[m.group(1)] = by_path_5xx.get(m.group(1), 0) + 1
                five.append(item)
                continue
        other.append(item)
    chosen = five[:MAX_LOG_LINES_5XX] + other[:MAX_LOG_LINES_OTHER]
    chosen.sort(key=lambda x: x["t"] or "")
    meta = {"window": {"start": iso(start), "end": iso(end)}, "log_group": log_group, "events_seen": len(events),
            "returned": len(chosen), "http_status_counts": by_status, "http_5xx_path_counts": by_path_5xx,
            "selection": "5xx 줄 우선(최대 %d) + 그 외 최대 %d, 줄당 %d자 절단" % (MAX_LOG_LINES_5XX, MAX_LOG_LINES_OTHER, MAX_LINE_CHARS)}
    if r.get("NextToken") or r.get("nextToken"):
        meta["truncated"] = True
        warn(warnings, "logs", "truncated", "로그가 500건 상한에서 잘림 — 아래 건수는 앞 500건 기준")
    return chosen, meta


def collect_resource_state(aws, cluster, service, at, warnings):
    state, changes = {}, []
    svc = None
    try:
        r = aws.call("ecs", "describe-services", ["--cluster", cluster, "--services", service], label="service")
        if r.get("failures"):
            warn(warnings, "ecs.service", "missing", "서비스 조회 실패: %s" % (r["failures"][0].get("reason") or r["failures"][0])[:200])
        elif r.get("services"):
            svc = r["services"][0]
            state["ecs_service"] = {"name": svc.get("serviceName"), "status": svc.get("status"), "desired": svc.get("desiredCount"),
                                    "running": svc.get("runningCount"), "pending": svc.get("pendingCount"),
                                    "task_definition": (svc.get("taskDefinition") or "").split("/")[-1]}
            state["ecs_deployments"] = [{"id": d.get("id"), "status": d.get("status"), "rollout_state": d.get("rolloutState"),
                                         "task_definition": (d.get("taskDefinition") or "").split("/")[-1], "desired": d.get("desiredCount"),
                                         "running": d.get("runningCount"), "created_at": d.get("createdAt"), "updated_at": d.get("updatedAt")}
                                        for d in svc.get("deployments", [])]
            state["ecs_recent_events"] = [{"at": e.get("createdAt"), "message": (e.get("message") or "")[:MAX_LINE_CHARS]}
                                          for e in svc.get("events", [])[:5]]
        else:
            warn(warnings, "ecs.service", "empty", "describe-services 가 서비스를 돌려주지 않음")
    except CollectError as e:
        warn(warnings, "ecs.service", "error", str(e))
    if svc and svc.get("taskDefinition"):
        try:
            r = aws.call("ecs", "describe-task-definition", ["--task-definition", svc["taskDefinition"]], label="taskdef")
            td = r.get("taskDefinition", {})
            cd = (td.get("containerDefinitions") or [{}])[0]
            # environment 는 복사하지 않는다(비밀이 들어 있을 수 있음). 이미지와 command 유무만.
            state["task_definition"] = {"revision": "%s:%s" % (td.get("family"), td.get("revision")), "image": cd.get("image"),
                                        "command_overridden": bool(cd.get("command")), "registered_at": td.get("registeredAt")}
            if td.get("registeredAt"):
                changes.append({"type": "task_definition_registered", "at": td.get("registeredAt"), "ref": state["task_definition"]["revision"]})
        except CollectError as e:
            warn(warnings, "ecs.task_definition", "error", str(e))
    if svc:
        for lb in svc.get("loadBalancers", [])[:1]:
            tg = lb.get("targetGroupArn")
            if tg:
                try:
                    r = aws.call("elbv2", "describe-target-health", ["--target-group-arn", tg], label="targets")
                    states = {}
                    for d in r.get("TargetHealthDescriptions", []):
                        s = d.get("TargetHealth", {}).get("State")
                        states[s] = states.get(s, 0) + 1
                    state["alb_target_health"] = states
                except CollectError as e:
                    warn(warnings, "elbv2.target_health", "error", str(e))
        cutoff = at - dt.timedelta(minutes=60)
        for d in state.get("ecs_deployments", []):
            ca = d.get("created_at")
            try:
                t = parse_time(ca) if ca else None
            except ValueError:
                t = None
            if t and cutoff <= t <= at + dt.timedelta(minutes=5):
                changes.append({"type": "deployment", "at": ca, "minutes_ago": round((at - t).total_seconds() / 60, 1),
                                "ref": d.get("task_definition"), "rollout_state": d.get("rollout_state")})
    return state, changes


# ---------- 가리기 ----------
ACCOUNT_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
SECRET_RES = [re.compile(p) for p in (r"(?:AKIA|ASIA)[0-9A-Z]{16}", r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}", r"sk-[A-Za-z0-9]{20,}",
                                       r"gh[pousr]_[A-Za-z0-9]{30,}", r"github_pat_[A-Za-z0-9_]{22,}", r"xox[baprs]-[0-9A-Za-z\-]{10,}",
                                       # 비밀 액세스 키(40자)는 이름이 앞에 붙을 때만 가린다 — 맨 40자를 다 가리면 git 해시 같은 정상 값까지 가려진다.
                                       r"(?i)(?:aws_secret_access_key|secret_access_key|secretaccesskey)[\"'\s:=]+[A-Za-z0-9/+=]{40}",
                                       r"(?i)(?:aws_session_token|session_token|sessiontoken|x-amz-security-token)[\"'\s:=]+[A-Za-z0-9/+=]{40,}",
                                       r"(?:IQoJb3JpZ2lu|FwoGZXIvYXdz)[A-Za-z0-9/+=]{40,}")]


def scrub(obj, mask_account, counter):
    if isinstance(obj, str):
        s = obj
        for rx in SECRET_RES:
            s, n = rx.subn("<redacted-secret-shape>", s)
            counter["secret_shapes"] += n
        if mask_account:
            s, n = ACCOUNT_RE.subn("<account-id>", s)
            counter["account_ids"] += n
        return s
    if isinstance(obj, list):
        return [scrub(x, mask_account, counter) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub(v, mask_account, counter) for k, v in obj.items()}
    return obj


def build(args, aws, now):
    warnings = []
    # 1) 알람(사건 시각을 정하려면 먼저 필요)
    alarm_obj_out, alarm_raw = collect_alarm(aws, args.alarm, now, warnings)
    at = parse_time(args.at) if args.at else None
    if at is None:
        su = alarm_obj_out.get("state_updated")
        try:
            at = parse_time(su) if (su and alarm_obj_out.get("state") == "ALARM") else now
        except ValueError:
            at = now
    history = collect_alarm_history(aws, args.alarm, at, warnings)
    metrics = collect_metrics(aws, alarm_obj_out if alarm_raw else None, args.cluster, args.service, at, warnings)
    logs, logs_meta = collect_logs(aws, args.log_group, at, warnings)
    state, changes = collect_resource_state(aws, args.cluster, args.service, at, warnings)
    if (now - at) < dt.timedelta(minutes=5):
        warn(warnings, "logs", "lag", "사건이 5분 안이라 CloudWatch Logs 가 아직 다 도착하지 않았을 수 있음 — «로그에 없다»는 «일어나지 않았다»가 아님")
    state_value = alarm_obj_out.get("state")
    severity = "HIGH" if state_value == "ALARM" else "UNKNOWN"
    ctx = {
        "incident_id": "inc-" + at.strftime("%Y%m%dT%H%M%SZ"),
        "timestamp": iso(at),
        "severity": severity,
        "severity_basis": "고정 규칙: 알람 상태 ALARM 이면 HIGH, 그 외 UNKNOWN. 평가가 아니라 매핑이다.",
        "service": {"name": args.service, "environment": "dev"},
        "trigger": alarm_obj_out,
        "alarm_history": history,
        "metrics": metrics,
        "logs": logs,
        "logs_meta": logs_meta,
        "resource_state": state,
        "recent_changes": sorted(changes, key=lambda c: str(c.get("at"))),
        "collection_warnings": warnings,
    }
    return ctx, warnings


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
    ap.add_argument("--no-mask", action="store_true", help="계정 ID 가리기를 끔(비밀 모양 문자열은 항상 가림)")
    ap.add_argument("--fixture", default=None, help="시험용: aws 호출 대신 이 폴더의 JSON 을 읽음")
    ap.add_argument("--now", default=None, help="시험용: 현재 시각 고정")
    args = ap.parse_args(argv)
    now = parse_time(args.now) if args.now else dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    out_path = args.out or os.path.join(root, "agent", "context", "incident-context.json")
    aws = Aws(args.region, args.profile, args.fixture)
    ctx, warnings = build(args, aws, now)
    counter = {"account_ids": 0, "secret_shapes": 0}
    ctx = scrub(ctx, not args.no_mask, counter)
    me = hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest()[:16]
    ctx["collection_meta"] = {"tool": TOOL, "version": TOOL_VERSION, "script_sha256_16": me, "read_only": True,
                              "region": args.region, "collected_at": iso(now),
                              "aws_calls": sorted(set(aws.calls)), "masking": {"account_id_masked": not args.no_mask,
                                                                               "replaced": counter}}
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
    print("사건 시각 %s · 경고 %d건 · 가린 것: 계정ID %d, 비밀모양 %d" % (ctx["timestamp"], n, counter["account_ids"], counter["secret_shapes"]))
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
