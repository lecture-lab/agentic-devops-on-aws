#!/usr/bin/env python3
"""collector.py — 사건 증거를 읽기 전용으로 모아 incident-context 딕셔너리를 만드는 모듈.

사람이 터미널에서 돌리는 collect-incident-context.py(aws CLI 호출층)와, 알림 뒤 자동 1차 분석 Lambda(boto3 호출층)가
이 모듈 하나를 함께 쓴다. 증거를 모으고 가리는 코드(마스킹·요약·경고)는 한 벌만 있고, AWS 를 부르는 층만 바꿔 끼운다.

원칙
  * AWS 는 읽기 전용만 부른다(describe-/get-/list-/filter-). 호출층이 실행 전에 허용 목록으로 거른다.
  * 관측된 사실만 담는다. 원인 판단(root cause)은 하지 않는다.
  * 못 모은 증거는 collection_warnings 에 남긴다. 조용한 빈 칸 없음.
  * 계정 ID 와 클라이언트(공인) IP 주소는 기본으로 가린다. 비밀 모양 문자열은 끄더라도 항상 가린다.
  * 비밀값·환경변수 전체·Lambda/Secrets 는 건드리지 않는다. task definition 의 environment 는 복사하지 않는다.
"""
import datetime as dt, hashlib, ipaddress, json, os, re, subprocess, sys

TOOL = "collect-incident-context"
TOOL_VERSION = "0.3"
ALLOWED_PREFIXES = ("describe-", "get-", "list-", "filter-")
ALLOWED_SERVICES = {"cloudwatch", "logs", "ecs", "elbv2"}
DEFAULT_ALARM = "agentic-devops-dev-high-5xx"
DEFAULT_CLUSTER = "agentic-devops-dev-cluster"
DEFAULT_SERVICE = "agentic-devops-dev-app-service"
DEFAULT_LOG_GROUP = "/ecs/agentic-devops-dev-app"
DEFAULT_REGION = "ap-northeast-2"  # 한국어 판 기본(서울). 영문 판은 AWS_REGION=us-east-1 로 바꾼다.
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


def _check_read_only(service, verb):
    if service not in ALLOWED_SERVICES or not verb.startswith(ALLOWED_PREFIXES):
        raise CollectError("읽기 전용이 아닌 호출 거부: aws %s %s" % (service, verb))


def _fixture_read(fixture_dir, service, verb, label):
    name = "%s.%s%s.json" % (service, verb, ("." + label) if label else "")
    path = os.path.join(fixture_dir, name)
    if not os.path.isfile(path):
        raise CollectError("fixture 없음: " + name)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class AwsCli:
    """aws CLI 읽기 전용 호출층. 허용 목록 밖 호출은 실행 전에 거부한다. --fixture 면 파일에서 읽는다(시험용).
    params 는 API 매개변수 딕셔너리(boto3 와 같은 이름)이고 --cli-input-json 으로 넘긴다."""

    def __init__(self, region, profile=None, fixture_dir=None):
        self.region, self.profile, self.fixture_dir = region, profile, fixture_dir
        self.calls = []

    def call(self, service, verb, params, label=None):
        _check_read_only(service, verb)
        self.calls.append("%s %s" % (service, verb))
        if self.fixture_dir:
            return _fixture_read(self.fixture_dir, service, verb, label)
        cmd = ["aws", service, verb, "--region", self.region, "--output", "json", "--no-cli-pager", "--no-paginate"]
        if params:
            cmd += ["--cli-input-json", json.dumps(params)]
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


Aws = AwsCli   # 예전 이름(시험·다른 코드가 쓰던 것)


def _jsonable(obj):
    """boto3 응답을 aws CLI 출력과 같은 모양(시각은 ISO 문자열, 응답 메타 제거)으로 바꾼다."""
    if isinstance(obj, dt.datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=dt.timezone.utc)
        return obj.astimezone(dt.timezone.utc).isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items() if k != "ResponseMetadata"}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    return obj


class AwsBoto3:
    """boto3 읽기 전용 호출층(Lambda 용). AwsCli 와 같은 call() 모양·같은 허용 목록·같은 반환 모양.
    오류는 예외 원문 대신 오류 코드만 담은 CollectError 로 바꾼다(요청 값·토큰이 로그에 새지 않게)."""

    def __init__(self, region, session=None, clients=None):
        self.region, self._session = region, session
        self._clients = clients if clients is not None else {}
        self.calls = []

    def _client(self, service):
        if service not in self._clients:
            import boto3  # Lambda 런타임에 들어 있음. CLI 쪽 시험은 이 줄까지 오지 않는다.
            self._clients[service] = (self._session or boto3).client(service, region_name=self.region)
        return self._clients[service]

    def call(self, service, verb, params, label=None):
        _check_read_only(service, verb)
        self.calls.append("%s %s" % (service, verb))
        try:
            return _jsonable(getattr(self._client(service), verb.replace("-", "_"))(**(params or {})))
        except CollectError:
            raise
        except Exception as e:
            code = ((getattr(e, "response", None) or {}).get("Error") or {}).get("Code") or type(e).__name__
            raise CollectError("aws %s %s 실패: %s" % (service, verb, code))


def warn(warnings, source, status, detail):
    warnings.append({"source": source, "status": status, "detail": detail})


# ---------- 수집기 ----------
def collect_alarm(aws, alarm_name, at, warnings):
    out = {"name": alarm_name}
    try:
        r = aws.call("cloudwatch", "describe-alarms", {"AlarmNames": [alarm_name]}, label="alarm")
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
                     {"AlarmName": alarm_name, "HistoryItemType": "StateUpdate",
                      "StartDate": iso(start), "EndDate": iso(end), "MaxRecords": 20}, label="history")
        items = [{"at": h.get("Timestamp"), "summary": h.get("HistorySummary")} for h in r.get("AlarmHistoryItems", [])]
        if not items:
            warn(warnings, "cloudwatch.alarm_history", "empty", "지난 60분 상태 변화 기록 없음")
        return items
    except CollectError as e:
        warn(warnings, "cloudwatch.alarm_history", "error", str(e))
        return []


def metric_points(aws, ns, name, dims, stat, start, end, label, warnings, source):
    try:
        params = {"Namespace": ns, "MetricName": name, "StartTime": iso(start), "EndTime": iso(end), "Period": 60,
                  "Statistics": [stat], "Dimensions": [{"Name": k, "Value": v} for k, v in dims.items()]}
        r = aws.call("cloudwatch", "get-metric-statistics", params, label=label)
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
                     {"logGroupName": log_group, "startTime": int(start.timestamp() * 1000),
                      "endTime": int(end.timestamp() * 1000), "limit": 500}, label="logs")
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
        r = aws.call("ecs", "describe-services", {"cluster": cluster, "services": [service]}, label="service")
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
            r = aws.call("ecs", "describe-task-definition", {"taskDefinition": svc["taskDefinition"]}, label="taskdef")
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
                    r = aws.call("elbv2", "describe-target-health", {"TargetGroupArn": tg}, label="targets")
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


# 클라이언트(공인) IP 가리기. 사설·루프백·링크로컬 주소(ALB·VPC 안쪽 주소)는 진단에 필요하므로 남기고,
# 공인(global) 주소만 «<client-ip-N>» 로 바꾼다. 같은 주소는 같은 번호라서 «한 곳에서 여섯 번» 같은 분석은 유지된다.
IPV4_RE = re.compile(r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])")
IPV6_RE = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")


def _mask_ips(s, counter):
    ips = counter.setdefault("_ip_index", {})

    def sub(m):
        try:
            ip = ipaddress.ip_address(m.group(0))
        except ValueError:
            return m.group(0)  # 시각(00:31:09)·버전 번호 같은 것은 IP 가 아님
        if not ip.is_global:
            return m.group(0)  # 사설·루프백·링크로컬은 남긴다
        key = str(ip)
        if key not in ips:
            ips[key] = len(ips) + 1
        counter["client_ip_replacements"] += 1
        return "<client-ip-%d>" % ips[key]

    s = IPV4_RE.sub(sub, s)
    return IPV6_RE.sub(sub, s)


def scrub(obj, mask_account, counter):
    if isinstance(obj, str):
        s = obj
        for rx in SECRET_RES:
            s, n = rx.subn("<redacted-secret-shape>", s)
            counter["secret_shapes"] += n
        if mask_account:
            s, n = ACCOUNT_RE.subn("<account-id>", s)
            counter["account_ids"] += n
            s = _mask_ips(s, counter)
        return s
    if isinstance(obj, list):
        return [scrub(x, mask_account, counter) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub(v, mask_account, counter) for k, v in obj.items()}
    return obj


def build_context(aws, alarm, cluster, service, log_group, now, at=None):
    """증거를 모아 (ctx, warnings) 를 돌려준다. 아직 가리기 전의 원본이다. at 이 없으면 알람 상태 변경 시각(ALARM 일 때) 또는 now."""
    warnings = []
    # 1) 알람(사건 시각을 정하려면 먼저 필요)
    alarm_obj_out, alarm_raw = collect_alarm(aws, alarm, now, warnings)
    if at is None:
        su = alarm_obj_out.get("state_updated")
        try:
            at = parse_time(su) if (su and alarm_obj_out.get("state") == "ALARM") else now
        except ValueError:
            at = now
    history = collect_alarm_history(aws, alarm, at, warnings)
    metrics = collect_metrics(aws, alarm_obj_out if alarm_raw else None, cluster, service, at, warnings)
    logs, logs_meta = collect_logs(aws, log_group, at, warnings)
    state, changes = collect_resource_state(aws, cluster, service, at, warnings)
    if (now - at) < dt.timedelta(minutes=5):
        warn(warnings, "logs", "lag", "사건이 5분 안이라 CloudWatch Logs 가 아직 다 도착하지 않았을 수 있음 — «로그에 없다»는 «일어나지 않았다»가 아님")
    state_value = alarm_obj_out.get("state")
    severity = "HIGH" if state_value == "ALARM" else "UNKNOWN"
    ctx = {
        "incident_id": "inc-" + at.strftime("%Y%m%dT%H%M%SZ"),
        "timestamp": iso(at),
        "severity": severity,
        "severity_basis": "고정 규칙: 알람 상태 ALARM 이면 HIGH, 그 외 UNKNOWN. 평가가 아니라 매핑이다.",
        "service": {"name": service, "environment": "dev"},
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


def build(args, aws, now):
    """CLI 용 얇은 껍데기(예전 이름 유지)."""
    at = parse_time(args.at) if args.at else None
    return build_context(aws, args.alarm, args.cluster, args.service, args.log_group, now, at)


def source_sha16(*paths):
    """이 도구를 이루는 파일들의 sha256 앞 16자 — 어떤 코드로 모았는지 ctx 에 남긴다."""
    h = hashlib.sha256()
    for p in paths:
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def finalize(ctx, aws, region, now, mask, source_hash):
    """가리기 + collection_meta 를 붙인다. (ctx, counter) 를 돌려준다."""
    counter = {"account_ids": 0, "secret_shapes": 0, "client_ip_replacements": 0}
    ctx = scrub(ctx, mask, counter)
    ctx["collection_meta"] = {"tool": TOOL, "version": TOOL_VERSION, "script_sha256_16": source_hash, "read_only": True,
                              "region": region, "collected_at": iso(now),
                              "aws_calls": sorted(set(aws.calls)), "masking": {"account_id_masked": mask,
                                                                               "client_ip_masked": mask,
                                                                               "distinct_client_ips": len(counter.get("_ip_index", {})),
                                                                               "replaced": {k: v for k, v in counter.items() if not k.startswith("_")}}}
    return ctx, counter


def collect_incident_context(aws, alarm, cluster, service, log_group, region, now, at=None, mask=True):
    """Lambda 용 한 번 호출: 모으고, 가리고, meta 를 붙여 (ctx, counter) 를 돌려준다."""
    ctx, _ = build_context(aws, alarm, cluster, service, log_group, now, at)
    return finalize(ctx, aws, region, now, mask, source_sha16(os.path.abspath(__file__)))


def collect_for_alert(aws, alarm_name, state_change_time, cluster, service, log_group, mask=True, now=None):
    """알림 Lambda 가 넘긴 이벤트로 한 번 호출하는 Lambda 용 입구: ctx(딕셔너리)만 돌려준다.
    state_change_time 은 알람 본문의 StateChangeTime(예: 2026-10-16T00:34:58.000+0000)이고 사건 시각으로 쓴다."""
    if not state_change_time:
        raise ValueError("state_change_time 이 비어 있음")
    at = parse_time(state_change_time)
    now = now or dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    ctx, _ = collect_incident_context(aws, alarm_name, cluster, service, log_group, aws.region, now, at=at, mask=mask)
    return ctx
