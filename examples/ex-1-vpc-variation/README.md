# EX-1 — AI가 만든 변경을 읽어라 (미니 VPC 변형)

Section 2(Terraform for Agentic Infrastructure) 직후 실습.

## 시작 상태

`infra/environments/dev/main.tf`의 원본 그대로: `locals.azs = ["<region>a", "<region>c"]`, `aws_subnet.public/private` count=2.

## 정상 버전 — 새 AZ를 끝에 추가

```hcl
locals {
  azs = ["${var.aws_region}a", "${var.aws_region}c", "${var.aws_region}b"]
}
# count 2 -> 3 (public/private/route_table_association 전부)
```
기존 `[0]`·`[1]`은 인덱스도 AZ 값도 그대로라 `plan`이 `3 to add, 0 to change, 0 to destroy`로 깨끗하게 나온다.

## 함정 버전(`trap.tf.snippet`) — 중간에 끼워 넣기

```hcl
locals {
  azs = ["${var.aws_region}a", "${var.aws_region}b", "${var.aws_region}c"]
}
```
새 AZ(`b`)를 리스트 **중간**에 넣으면 기존 `[1]`이 가리키던 AZ가 `c`→`b`로 바뀐다. `availability_zone`은 ForceNew라 Terraform이 그 subnet을 destroy 후 재생성해야 한다.

## ✅ 실AWS 라이브 검증 완료 (2026-09-10)

course-repo dev 환경에 base(무료 리소스 9개: VPC/IGW/subnet 4개/route table/association 2개)를 실제로 apply한 뒤 함정 버전을 적용해서 `terraform plan` 실행, 결과:

```
# aws_subnet.public[1] must be replaced        (AZ c -> b, ForceNew)
# aws_subnet.private[1] must be replaced       (AZ c -> b, ForceNew)
# aws_route_table_association.public[1] must be replaced   (연쇄 -- subnet_id가 바뀜)
# aws_subnet.public[2] / private[2] / route_table_association.public[2] will be created
Plan: 6 to add, 0 to change, 3 to destroy.
```

가설 그대로 확인됨. Route table association까지 연쇄로 replace되는 건 미리 예상 못 했던 디테일 — 학생 성공기준에 "association도 왜 같이 replace되는지"까지 설명하게 하면 더 좋다. 검증 직후 base 리소스는 destroy, `main.tf`는 원본으로 원복(현재 이 저장소의 `infra/environments/dev/main.tf`는 손 안 댄 원본 상태).

## 완료 (2026-09-11)

- `normal.tf.snippet` / `trap.tf.snippet` — 둘 다 `terraform validate` 통과 확인(course-repo dev 환경에 임시로 넣고 검증 후 이 파일들로 분리, main.tf는 원본 그대로 원복).
- `grading-checklist.md` — 실측값(위 라이브 검증 결과) 기준. "destroy 개수만 맞으면 통과"가 아니라 "어떤 리소스가 destroy되는지"까지 보게 설계 — receipt-discipline 원칙(개수만 보는 체크는 false-green 위험) 적용.
