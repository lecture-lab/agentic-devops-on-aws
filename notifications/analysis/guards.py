"""guards.py — 자동 분석이 폭주하거나 겹치지 않게 막는 장치. 모두 DynamoDB 조건부 쓰기 한 번씩.

  * 중복 차단: 같은 알람 상태 변화(StateChangeTime)는 한 번만 분석한다(재전달에도 이 시각은 안 바뀜).
  * 단일 실행 잠금: 분석은 한 번에 하나만. 서울 계정 Lambda 동시성 한도가 10이라 예약 동시성을 못 써서 표로 잠근다.
  * 쿨다운: 같은 알람은 15분에 한 번.
  * 일일 상한: 하루(UTC) 20회. 넘으면 그날은 분석하지 않는다(비용 보호).
표: 파티션 키 pk(문자열) · TTL 속성 expires_at. 상시 Agent 의 표와 같은 모양.
"""
import time

LOCK_KEY = "analysis-lock"
LOCK_TTL_S = 150              # Lambda 타임아웃(120초)보다 길게. 죽어도 150초 뒤 풀린다.
DEDUP_TTL_S = 7 * 86400


class MemoryStore:
    """시험용 저장소. DynamoStore 와 같은 세 함수."""
    def __init__(self):
        self.d = {}

    def add_once(self, key, ttl_s, now):
        exp = self.d.get(key)
        if exp is not None and exp > now:
            return False
        self.d[key] = now + ttl_s
        return True

    def incr_upto(self, key, cap, ttl_s, now):
        n, exp = self.d.get(key, (0, now + ttl_s))
        if n >= cap:
            return False
        self.d[key] = (n + 1, exp)
        return True

    def release(self, key):
        self.d.pop(key, None)


class DynamoStore:
    """client = boto3.client("dynamodb")."""
    def __init__(self, client, table):
        self.c, self.t = client, table

    def add_once(self, key, ttl_s, now):
        # 없거나 만료된 항목일 때만 쓴다. 이미 있으면 False.
        try:
            self.c.put_item(TableName=self.t,
                            Item={"pk": {"S": key}, "expires_at": {"N": str(int(now + ttl_s))}},
                            ConditionExpression="attribute_not_exists(pk) OR expires_at < :now",
                            ExpressionAttributeValues={":now": {"N": str(int(now))}})
            return True
        except self.c.exceptions.ConditionalCheckFailedException:
            return False

    def incr_upto(self, key, cap, ttl_s, now):
        # cap 미만이면 1 더한다. 키에 날짜가 있어 날이 바뀌면 새로 센다.
        try:
            self.c.update_item(TableName=self.t, Key={"pk": {"S": key}},
                               UpdateExpression="ADD n :one SET expires_at = if_not_exists(expires_at, :exp)",
                               ConditionExpression="attribute_not_exists(n) OR n < :cap",
                               ExpressionAttributeValues={":one": {"N": "1"}, ":cap": {"N": str(cap)},
                                                          ":exp": {"N": str(int(now + ttl_s))}})
            return True
        except self.c.exceptions.ConditionalCheckFailedException:
            return False

    def release(self, key):
        self.c.delete_item(TableName=self.t, Key={"pk": {"S": key}})


def gate(store, alarm_name, state_change_time, cooldown_s, daily_cap, now=None):
    """분석해도 되면 (True, "ok"). 아니면 (False, 이유). True 면 잠금을 쥐고 있으니 끝에 release(LOCK_KEY)."""
    now = time.time() if now is None else now
    if not store.add_once(f"analysis#{alarm_name}#{state_change_time}", DEDUP_TTL_S, now):
        return False, "duplicate"
    if not store.add_once(LOCK_KEY, LOCK_TTL_S, now):
        return False, "locked"
    if not store.add_once(f"cool#{alarm_name}", cooldown_s, now):
        store.release(LOCK_KEY)
        return False, "cooldown"
    day = time.strftime("%Y%m%d", time.gmtime(now))
    if not store.incr_upto(f"day#{day}", daily_cap, 2 * 86400, now):
        store.release(LOCK_KEY)
        return False, "daily_cap"
    return True, "ok"
