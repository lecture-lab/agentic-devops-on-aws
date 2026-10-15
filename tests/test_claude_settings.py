#!/usr/bin/env python3
"""Claude Code 시작 권한 모드 고정 시험 — 네트워크·AWS 호출 0.

이 강좌는 항상 «먼저 허락을 묻는 모드»(Manual, 설정값 `default`)로 진행한다.
Claude Code v2.1.283 이상은 아무것도 정하지 않으면 대화형 터미널/VS Code에서
auto 모드(분류기가 대신 검토)로 시작하므로, 저장소의 .claude/settings.json 이
`permissions.defaultMode = "default"` 를 고정해 둔다.
원문: code.claude.com/docs/en/permission-modes (Which mode a session starts in).
`auto` 와 `bypassPermissions` 는 프로젝트 설정 파일에서 효력이 없고 `default` 는 있다.
"""
import json, os, subprocess, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SETTINGS = os.path.join(ROOT, ".claude", "settings.json")


class ClaudeSettings(unittest.TestCase):
    def test_file_exists_and_is_json(self):
        self.assertTrue(os.path.isfile(SETTINGS), ".claude/settings.json 이 없다")
        with open(SETTINGS, encoding="utf-8") as f:
            json.load(f)

    def test_default_mode_is_manual(self):
        with open(SETTINGS, encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg.get("permissions", {}).get("defaultMode"), "default")

    def test_no_permissive_rules(self):
        """시작 모드만 고정하는 파일이다. 허용 규칙·우회 설정을 슬쩍 넣지 못하게 한다."""
        with open(SETTINGS, encoding="utf-8") as f:
            cfg = json.load(f)
        perms = cfg.get("permissions", {})
        self.assertEqual(set(cfg), {"permissions"}, "permissions 밖의 키가 있다")
        self.assertEqual(set(perms), {"defaultMode"}, "defaultMode 밖의 권한 키가 있다")

    def test_not_gitignored(self):
        try:
            r = subprocess.run(["git", "check-ignore", "-q", "--no-index", ".claude/settings.json"], cwd=ROOT)
        except FileNotFoundError:
            self.skipTest("git 이 없다")
        self.assertEqual(r.returncode, 1, ".claude/settings.json 이 .gitignore 에 걸린다(추적되어야 함)")


if __name__ == "__main__":
    unittest.main()
