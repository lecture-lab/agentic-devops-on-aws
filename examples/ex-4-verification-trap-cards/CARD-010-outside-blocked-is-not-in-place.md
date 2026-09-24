# 🃏 CARD-010 — ***「밖으로 못 나간다」는 「제자리에 있다」가 아니다***

> 함정 카드 · 재료 · 2026-09-24
> 🔒 밟아야 생기는 함정입니다. ⑤는 **붙여넣어 돌리면 빨강**입니다.
> 🔗 짝 카드 : CARD-009(금지목록 ⊥ 허용형)는 **입력을 무엇으로 거르나** · 이 카드는 **억제를 어디에 대고 재나**

## ① 제목 (기전으로)
**경로 억제 검사의 기준점이 「뿌리 하나」이면 — 뿌리 안에서의 이동은 전부 합법이 된다.**
⇒ 검사는 「탈출 없음」을 정확히 말한다. 그런데 파일이 **선언한 디렉터리에 들어갔는지**는 아무도 안 묻는다.

## ② 겉보기
```
· 모든 파일 쓰기가 ★한 함수를 지나고 · 그 함수가 ★realpath 로 「뿌리 안인가」를 검사한다
· 교과서대로다. 심볼릭 링크·`..` 로 뿌리 밖을 노리면 ★정확히 거부한다
· 자체 시험 ★전부 초록 · 작업도 ★성공으로 끝난다
· ⊥ 작업 기록을 찾으러 ★선언한 디렉터리를 열면 ⇒ ★비어 있다
```

## ③ 기계가 낸 수 (⛔형용사 없음)
```
· 식별자 = `../X` 로 기록 두 개를 씀 (`journal/<id>.log` · `rollback/<id>.bak`)
    뿌리 억제 검사        ⇒ ★통과 2 / 2      (탈출 0 — ★참)
    선언한 journal/ 항목  ⇒ ★0
    선언한 rollback/ 항목 ⇒ ★0
    뿌리 바로 아래 생긴 파일 ⇒ ★2
· 같은 경로를 ★선언한 디렉터리 기준으로 재면 ⇒ 거부 2 / 2
· 재현 rc ★1
```

## ④ 기전
억제 검사는 **「어디에 대고」** 재느냐로 답이 정해진다. 기준점을 뿌리 하나로 두면
그 검사가 답하는 물음은 「밖으로 나갔나」뿐이다. 식별자에 `..` 가 섞이면 파일은 **선언한 칸에서 한 칸 위로**
올라가지만 **여전히 뿌리 안**이라 — 검사는 ★정직하게 통과시킨다. 틀린 건 검사가 아니라 **검사에 준 기준점**이다.
⇒ 🔒 ***검사가 답한 물음과 내가 물었다고 믿은 물음이 다르면, 초록은 내 믿음의 초록이다.***

## ⑤ 재현 (붙여넣어 돌리면 ★빨강)
```python
import os, sys, tempfile

def contained(base, p):                         # realpath 로 base 안인가
    b = os.path.realpath(base); r = os.path.realpath(p)
    return r == b or r.startswith(b + os.sep)

with tempfile.TemporaryDirectory() as root:
    for d in ("journal", "rollback"): os.makedirs(os.path.join(root, d))
    op = "../X"                                 # ★검증 안 된 식별자
    targets = {"journal": os.path.join(root, "journal", op + ".log"),
               "rollback": os.path.join(root, "rollback", op + ".bak")}
    root_ok = ns_ok = 0
    for ns, p in targets.items():
        if contained(root, p):                  # 🔴 기준점 = 뿌리
            root_ok += 1
            with open(p, "w") as f: f.write("record\n")
        if contained(os.path.join(root, ns), p): # ⭕ 기준점 = 선언한 디렉터리
            ns_ok += 1
    in_journal  = len(os.listdir(os.path.join(root, "journal")))
    in_rollback = len(os.listdir(os.path.join(root, "rollback")))
    at_root = sorted(n for n in os.listdir(root) if n not in ("journal", "rollback"))
    print(f"뿌리 억제 통과 {root_ok}/2 · 선언 디렉터리 기준 통과 {ns_ok}/2")
    print(f"journal/ {in_journal} · rollback/ {in_rollback} · 뿌리 바로 아래 {at_root}")
    lost = root_ok and (in_journal + in_rollback) == 0
    if lost: print("🔴 억제는 통과했는데 선언한 디렉터리가 비었습니다")
    sys.exit(1 if lost else 0)
```
```
[측] 출력 : 뿌리 억제 통과 2/2 · 선언 기준 0/2 · journal/ 0 · rollback/ 0 · 뿌리에 X.log X.bak ⇒ rc ★1
```

## ⑥ 처방
```
① ★식별자는 경로로 만들기 前에 ★문법으로 잰다 — 허용형 하나 (⇐ CARD-009)
② 억제 검사의 기준점을 ***★선언한 디렉터리***로 둔다 — ⛔뿌리 하나로 뭉치지 않는다
③ 뿌리 억제는 ★겹 방어로 남긴다 — ⛔그것을 식별자 검증기로 쓰지 않는다
④ 경로 조립 함수 안에 ★전제를 한 줄로 적는다 — ★적어둔 전제는 검사가 된다
⑤ 쓰기 뒤에 「기대한 칸에 들어갔나」를 ★센다 — ⛔「예외가 안 났다」를 증거로 쓰지 않는다
```
> ⚠️ **이 처방이 쓰는 재료를 다른 검사도 쓰고 있지 않은가**
> ```
> ★기준점을 좁히면 ★공용 경로(잠금 파일·영수증 등)를 쓰는 코드가 ★전부 빨강이 된다.
> ⇒ ★정상이다. 그 경로마다 ★자기 기준점을 따로 선언하면 된다 — ⛔기준점을 다시 뿌리로 넓히지 않는다.
> ```

## ⑦ 이 카드가 주장하지 않는 것
```
⛔ 「뿌리 억제가 무용하다」 — ★뿌리 밖으로는 진짜로 못 나갔다
⛔ 「선언 디렉터리 기준이면 끝」 — ★식별자 문법 검사는 따로 필요하다(①)
⛔ 「자체 시험이 틀렸다」 — ★자체 시험은 자기가 물은 것에 정확했다. ★안 물은 것이 있었다
⛔ 「이 구멍을 내가 찾았다」 — ★남이 대준 반례로 드러났다. 내 시험은 이 물음을 ★한 번도 안 했다
```

---
🔒 **한 줄** : 억제 검사가 초록이면 물어라 — **이 검사는 어디에 대고 쟀는가.**
