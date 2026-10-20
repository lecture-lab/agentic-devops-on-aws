"""평문 Telegram 전송 — 자동 1차 분석 Lambda 용.

notifications/telegram/handler.py 의 _send 와 같은 토큰 취급(Secrets Manager 에서 호출 때 읽고, 값은 로그·예외에 남기지 않음)에
parse_mode 만 뺐다. 모델이 쓴 글에 _ * ` 가 있어도 Markdown 해석 오류(400)로 죽지 않게 하려는 것이다.
secrets_client 는 밖에서 넣는다(Lambda 에서는 boto3 클라이언트, 시험에서는 가짜).
"""
import json
import logging
import urllib.error
import urllib.request

# Telegram 한 메시지 상한(4096자) 안쪽으로 자른다 [추: 공식 문서는 이번에 열지 않음].
MAX_CHARS = 4000
CUT_MARK = "\n…(생략)"

log = logging.getLogger()


def send_plain(text, chat_id, secret_arn, secrets_client, timeout=10):
    token = secrets_client.get_secret_value(SecretId=secret_arn)["SecretString"]
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS - len(CUT_MARK)] + CUT_MARK
    url = "https://api.telegram.org/bot%s/sendMessage" % token
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")   # parse_mode 없음 = 평문
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except urllib.error.URLError:
        # 예외 문자열에는 요청 주소(= 토큰)가 들어 있다. 고정 문구만 남기고 원 예외는 잇지 않는다.
        log.error("Telegram send failed (token/URL withheld from logs)")
        raise RuntimeError("telegram send failed") from None
