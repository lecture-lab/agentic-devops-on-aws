# EX-3 — 다른 알람 조건 추가하기 (Latency p99)

Section 6(Real Alerting) 직후 실습. 스펙: `docs/curriculum/example-projects-v0.1.md` §EX-3.

`alarm.tf`는 `infra/environments/dev/alarms.tf`의 기존 `aws_cloudwatch_metric_alarm.high_5xx`와 같은 SNS 토픽(`aws_sns_topic.alerts`)·같은 ALB/Target Group을 참조하되, 지표만 5xx 카운트 대신 `TargetResponseTime`의 p99로 바꾼 것이다.

## 검증 상태 (2026-09-10)

- `terraform fmt`/`terraform validate` 통과 확인(course-repo dev 환경에 임시로 넣고 검증 후 이 파일로 분리).
- **실AWS 배포는 아직 안 함** — ALB/ECS/RDS 전체 스택을 띄워야 하는데 비용이 발생하는 리소스(NAT Gateway, RDS)라, 이 알람 하나 확인하자고 전체 스택을 새로 배포하는 건 비용 대비 실익이 낮다고 판단해서 보류했다. 대신 기존 `high_5xx`와 구조가 완전히 동일(같은 리소스 타입·같은 dimensions 참조·같은 SNS 액션)해서, 문법·타입 검증만으로도 "붙었을 때 작동할 것"이라는 근거는 충분하다고 판단.
- 학생이 실습할 때는 실제로 캡스톤/Section 6 스택이 이미 떠 있는 상태이므로, 이 코드를 그대로 `infra/environments/dev/`에 추가해서 apply하면 된다 — 그때가 진짜 살아있는 검증이다.

## 사용법

학생 실습 시: 이 디렉터리의 `alarm.tf` 내용을 Agent에게 자연어로 요청하게 하거나(스펙 참고), 참고 정답으로 `infra/environments/dev/alarms.tf`에 이어붙여 `terraform plan`으로 기존 `high_5xx`가 안 건드려지는지 확인한다.
