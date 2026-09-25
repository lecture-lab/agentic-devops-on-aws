# EX-2 — 게이트를 직접 깨봐라 (Fingerprint Verification Gate)

Section 4(Safe Agentic Deployment) 직후 실습. 스펙: `docs/curriculum/example-projects-v0.1.md` §EX-2.

이 게이트(`scripts/preflight-fingerprint-check.sh`)는 새로 만든 게 아니라, infra이 이 강좌 제작 중 실제로 만들고 실AWS에서 검증한 도구를 그대로 재사용한다. 원본은 내부 production repo(`agentic-devops-on-aws/scripts/`)에 있고, 이 학생용 실습을 위해 course-repo로 그대로 포팅했다(2026-09-10, 파일 diff 0 — 한 글자도 안 바뀜).

## 시작 전 준비

1. Section 4까지 완료해서 승인된 plan 파일과 그 `.sha256` fingerprint, 그리고 approval packet(`- [x] APPROVED` 줄이 있는 md)이 있어야 한다.
2. 없다면 최소 재현: `terraform plan -out=tfplan`, `sha256sum tfplan > approval.md.sha256`, `approval.md`에 `- [x] APPROVED` 한 줄만 있어도 게이트가 통과한다(Layer 0 체크는 그 문자열만 본다).

## 3단계 실습

### 1) 정상 경로 확인 (베이스라인)

```bash
./scripts/preflight-fingerprint-check.sh tfplan approval.md
# 기대: RESULT: READY
```

### 2) Layer 1 깨보기 — plan 파일 변조

```bash
# 아무 내용이나 한 바이트 덧붙이기 (에디터로 열었다 저장해도 동일 효과)
echo "" >> tfplan
./scripts/preflight-fingerprint-check.sh tfplan approval.md
# 기대: Plan Fingerprint FAIL (recorded != current)
```

### 3) Layer 2 깨보기 — 실시간 drift

plan 파일은 그대로 두고, 실제 인프라 쪽에서 뭔가 바뀐 상황을 재현한다 — 가장 쉬운 방법은 `.tf` 소스 파일 하나를 approval 이후에 살짝 고치는 것(예: 태그 값 하나 변경)이다. 그러면 스크립트가 내부적으로 다시 `terraform plan`을 돌려서 승인된 plan과 비교하는데, 그 둘이 달라진다.

```bash
# 예: 태그 값 하나 변경 (실제 리소스 존재 여부와 무관하게 재현 가능)
# main.tf의 어느 tags 블록이든 값 하나만 바꾸고 저장
./scripts/preflight-fingerprint-check.sh tfplan approval.md
# 기대: Unreviewed Diff FAIL
```

## 더 깊이 (선택)

이 게이트 같은 "거부하는 스크립트"를 직접 설계할 때 더 조심할 것들 — `../ex-4-verification-trap-cards/CASE-STUDY-02-THE-SAFETY-HOLD-THAT-REPORTED-SUCCESS-20260925.md`. 거부가 exit code·stdout·stderr 중 한 채널에서라도 "성공"처럼 보이면 안 된다는 실제 실패 사례와, mutant 5개로 자기 게이트를 테스트하는 방법.

## 다 끝나면

학생 자신의 말로 정리해보게 한다: "이 게이트는 어떤 몰래-변경을 잡고, 어떤 건 못 잡는가?" — 정답 방향: 파일 변조·인프라 drift는 잡지만, "애초에 승인 자체가 틀린 판단이었다"는 못 잡는다(그건 Section 4의 Human Approval Boundary 원칙이 다루는 문제).

## 실측 이력

- Layer 0/1 로직: infra 원저작, 실AWS에서 검증됨(2026-09-01 전후, 내부 production repo 히스토리).
- Layer 2 signature 로직: 2026-09-01, 실AWS 첫 apply에서 발견된 오탐(exit-code 2가 drift뿐 아니라 첫 apply에도 뜨는 문제) 수정 + infra 리뷰로 잡힌 두 번째 갭(값만 바뀐 리소스 미탐지) 반영.
- **✅ 2026-09-10, 이 학생용 포팅본으로 3단계 전부 직접 재현 완료** (course-repo dev, AWS 리소스는 하나도 안 만듦 — 전부 `terraform plan`은 읽기전용, apply는 한 번도 안 함):
  - 1) 베이스라인 → `RESULT: READY` 확인
  - 2) plan 파일에 빈 줄 하나 추가 → `Plan Fingerprint FAIL` 확인
  - 3) `main.tf`의 VPC 태그 값 하나만 변경(승인된 plan 파일은 안 건드림) → `Unreviewed Diff FAIL` 확인
  - 부수 확인: Layer 2 diff 출력에 RDS `master_password` 필드가 찍히는지 직접 grep해봤는데 `null`(생성 전이라 `after_unknown`으로 처리돼 `strip_unknown`이 지움) — `plan-signature.py` 상단의 accepted-risk 주석("이미 존재하는 민감값 리소스에 재사용하면 평문 노출 가능")이 아직 이 저장소 범위에선 안 터진다는 것도 실측으로 재확인.
