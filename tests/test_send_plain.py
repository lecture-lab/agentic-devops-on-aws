#!/usr/bin/env python3
"""notifications/analysis/send_plain.py 시험 — 네트워크·AWS 호출 0."""
import json, os, sys, unittest, urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "notifications", "analysis"))
import send_plain as sp

TOKEN = "123456:FAKE-TOKEN-not-real"


class FakeSecrets:
    def __init__(self):
        self.asked = []

    def get_secret_value(self, SecretId):
        self.asked.append(SecretId)
        return {"SecretString": TOKEN}


class FakeResp:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return b"{}"


class SendPlainTests(unittest.TestCase):
    def test_payload_has_no_parse_mode_and_goes_to_the_bot_url(self):
        seen = {}
        def fake_open(req, timeout=None):
            seen["url"], seen["body"], seen["timeout"] = req.full_url, json.loads(req.data.decode()), timeout
            return FakeResp()
        sec = FakeSecrets()
        with mock.patch.object(sp.urllib.request, "urlopen", fake_open):
            sp.send_plain("안녕 _밑줄_ *별* `코드`", "42", "arn:secret", sec)
        self.assertEqual(sec.asked, ["arn:secret"])
        self.assertEqual(seen["body"], {"chat_id": "42", "text": "안녕 _밑줄_ *별* `코드`"})   # parse_mode 키 자체가 없다
        self.assertTrue(seen["url"].endswith("/sendMessage"))
        self.assertEqual(seen["timeout"], 10)

    def test_long_text_is_cut_to_the_limit_with_a_mark(self):
        seen = {}
        def fake_open(req, timeout=None):
            seen["text"] = json.loads(req.data.decode())["text"]
            return FakeResp()
        with mock.patch.object(sp.urllib.request, "urlopen", fake_open):
            sp.send_plain("가" * 6000, "42", "arn:secret", FakeSecrets())
        self.assertEqual(len(seen["text"]), sp.MAX_CHARS)
        self.assertTrue(seen["text"].endswith(sp.CUT_MARK))

    def test_short_text_is_untouched(self):
        seen = {}
        def fake_open(req, timeout=None):
            seen["text"] = json.loads(req.data.decode())["text"]
            return FakeResp()
        with mock.patch.object(sp.urllib.request, "urlopen", fake_open):
            sp.send_plain("x" * sp.MAX_CHARS, "42", "arn:secret", FakeSecrets())
        self.assertEqual(seen["text"], "x" * sp.MAX_CHARS)

    def test_failure_never_leaks_the_token_into_the_exception_or_the_log(self):
        def boom(req, timeout=None):
            raise urllib.error.URLError("failed for " + req.full_url)   # 실제 URLError 도 주소를 담는다
        with mock.patch.object(sp.urllib.request, "urlopen", boom):
            with self.assertLogs(level="ERROR") as logs:
                with self.assertRaises(RuntimeError) as cm:
                    sp.send_plain("x", "42", "arn:secret", FakeSecrets())
        self.assertNotIn(TOKEN, str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)
        self.assertTrue(cm.exception.__suppress_context__)
        self.assertNotIn(TOKEN, "\n".join(logs.output))
        self.assertNotIn("api.telegram.org", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
