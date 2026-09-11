# EX-1 채점 체크리스트

> 근거: 2026-09-10 실AWS 라이브 검증(README.md) — 아래 숫자는 전부 실측값이지 추정값이 아니다.

## 1단계 — 함정을 스스로 재현했는가

- [ ] `terraform plan`을 돌려서 **`Plan: 6 to add, 0 to change, 3 to destroy`**가 정확히 떴다.
- [ ] destroy 대상 3개가 정확히 이것인가: `aws_subnet.public[1]`, `aws_subnet.private[1]`, `aws_route_table_association.public[1]`.
  - ⚠️ **여기서 "숫자만 3이면 통과"로 채점하지 말 것** — 학생이 완전히 다른 실수(예: CIDR을 잘못 적어 기존 subnet과 겹치는 값을 넣었다가 apply가 에러로 막힘)를 해도 우연히 destroy 개수가 같아질 수 있다. **어떤 리소스가 destroy되는지(주소)**까지 확인해야 진짜 채점이다 — 개수만 보는 체크리스트는 통과하기 쉬운 가짜 초록(false-green)이다.
- [ ] Agent에게 "왜 이 리소스가 replace되는지 설명해"라고 물어봤고, 답이 **"AZ 리스트 중간삽입 → count.index 밀림 → availability_zone 값 변경 → ForceNew"** 계열의 설명을 담고 있다(용어가 완전히 똑같을 필요는 없음 — 인과관계를 짚었는지가 핵심).
- [ ] `aws_route_table_association.public[1]`도 같이 replace되는 이유(subnet_id가 바뀌었으므로 연쇄)까지 설명할 수 있다.

## 2단계 — 함정을 고쳐서 destroy 없이 만들었는가

- [ ] `terraform plan`을 다시 돌려서 **`Plan: 3 to add, 0 to change, 0 to destroy`**로 나왔다(`normal.tf.snippet` 방식 — 새 AZ를 리스트 끝에 추가).
- [ ] 기존 `aws_subnet.public[0]`, `[1]`, `aws_subnet.private[0]`, `[1]`이 plan 결과에 **전혀 등장하지 않는다**(등장하면 아직 뭔가 안 건드려야 할 게 건드려진 것).

## 채점자에게 (⛔이 체크리스트 자체의 한계)

- 이 체크리스트는 "숫자가 맞는가"를 넘어 "리소스 주소가 맞는가"까지 보게 설계했지만, 그래도 **완전 자동 채점은 아니다** — Agent의 설명이 그럴듯하게 들리지만 실제로는 틀린 인과관계를 댈 수도 있으니, 마지막 항목("왜"를 설명하게 하는 것)은 사람이 직접 읽고 판단해야 한다.
- 시작 상태(L02-03에서 만든 원본 VPC)가 이미 변형돼 있는 학생이 있을 수 있다 — 채점 전에 `git diff`나 `terraform state list`로 시작점이 맞는지 먼저 확인할 것.
