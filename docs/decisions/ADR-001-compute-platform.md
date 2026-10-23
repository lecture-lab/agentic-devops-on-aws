# ADR-001 — First Release AWS Architecture

## Status

Accepted for Course MVP

---

## Context

Agentic DevOps on AWS 과정에서는 다음 전체 Cycle을 학습해야 한다.

Natural Language Requirement → Architecture → Infrastructure as Code → Validation → Human Approval → Deployment → Observability → Incident Detection → Agent Analysis → Notification

동시에 First Release 강좌이므로 다음을 통제해야 한다.

- 수강 난이도
- AWS 비용
- Resource 생성 시간
- 장애 실습 난이도
- Cleanup 난이도
- 지나친 Kubernetes/OS 운영 지식 요구

---

# Decision

## Region

AWS Seoul (`ap-northeast-2`)

## Network

하나의 VPC (`10.20.0.0/16`), 2 Availability Zones. 각 AZ: Public Subnet / Application Private Subnet / Database Private Subnet.

## Entry Layer

Application Load Balancer — HTTP Traffic Entry, Health Check, ECS Target Distribution. First Lab: HTTP. Production Extension: HTTPS + ACM.

## Compute

Amazon ECS on AWS Fargate. Desired Count 2.

선택 이유: EC2 OS 관리 제거, Kubernetes 운영 복잡도 제거, Container 학습 가능, ALB 연동 가능, Health Check 가능, Scaling/Failure 실습 가능, CloudWatch 연동 가능, Terraform Resource가 충분히 풍부함.

## Database

Amazon RDS PostgreSQL. Training Default: Single-AZ 또는 비용 절감 설정. Production Extension: Multi-AZ, Backup Policy, Encryption, Secrets Management.

## Internet Egress

교육용 기본 구성에서는 가장 이해하기 쉬운 방식으로 구현하되 NAT 관련 지속 비용을 명확히 설명한다.

## Security Groups

Internet → ALB SG → Application SG → Database SG. Database는 Internet에 직접 노출하지 않는다.

## Observability

Amazon CloudWatch (ALB/ECS/Application Metrics, Logs, Alarm). 후속 확장: OpenTelemetry.

## Incident Flow

Cloud Event → Alarm → Context Collection → Agent Analysis → Structured Incident Summary → Telegram → Email.

---

## Alternatives Considered

**EC2 + Auto Scaling Group** — 제외 이유: AMI/OS/Patch/User Data 설명이 강의 중심축을 분산시킴. 후속 AWS Infrastructure 과정 후보.

**EKS** — 제외 이유: Kubernetes 자체 학습량이 커서 첫 강좌 범위를 지나치게 확대함. 후속 강좌 후보(Agentic Platform Engineering).

**Lambda** — 제외 이유: Container Service 운영/Load Balancer/Long-running Application/Task 장애 교육 경험이 줄어듦. Automation Component에는 활용 가능.

---

## Consequences

Production-shaped, Training-sized: Production 설계 개념은 유지하되 교육용 Resource Size와 Availability Option을 사용한다. 모든 유료 Resource에는 생성 시점·비용 주의·유지 필요 여부·Cleanup 방법을 명확히 표시한다.

## Revisit When

Kubernetes/EKS 중심 과정, Enterprise Production 과정, Multi-Region 과정, Fully Autonomous Operations, Platform Engineering 과정, Serverless 중심 과정을 만들 때.
