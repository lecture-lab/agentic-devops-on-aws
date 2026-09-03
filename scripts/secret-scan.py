#!/usr/bin/env python3
"""Secret scanner for this repo (reviewer F5).

A zero-hit result is not proof of absence -- so this script also carries
a self-test that proves the patterns actually fire, using a known-bad
fixture that is excluded from the real scan (otherwise it would block
its own commit forever).

Modes:
  secret-scan.py            scan tracked + staged + untracked candidate
                             files, and git history, for secret-shaped
                             strings. Exit 1 if anything is found.
  secret-scan.py --self-test
                             scan ONLY tests/secret_scan_fixtures/known_bad.txt
                             and assert every pattern fires at least once.
                             Exit 1 if the scanner is not actually working.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "secret_scan_fixtures" / "known_bad.txt"

PATTERNS = {
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "telegram_bot_token": re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "jwt": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "credential_bearing_url": re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:]+:[^/\s@]+@"),
    # Quotes required on both sides: a real embedded secret is a string
    # literal. A bare identifier after '=' (e.g. Terraform's
    # `password = random_password.db_master.result`) is a reference, not
    # a value, and dots in it would otherwise get misread as part of a
    # long-enough "secret" by an unanchored character class.
    "generic_assignment": re.compile(
        r"""(?i:password|passwd|secret|api[_-]?key)\s*[:=]\s*(['"])[A-Za-z0-9/+_-]{12,}\1"""
    ),
}


def run(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout


def candidate_files() -> set[Path]:
    tracked = run("ls-files").splitlines()
    staged = run("diff", "--cached", "--name-only").splitlines()
    untracked = run("ls-files", "--others", "--exclude-standard").splitlines()
    names = set(tracked) | set(staged) | set(untracked)
    return {REPO_ROOT / n for n in names if n}


def scan_text(text: str) -> list[str]:
    hits = []
    for name, pattern in PATTERNS.items():
        if pattern.search(text):
            hits.append(name)
    return hits


def scan_files(paths: set[Path], exclude: set[Path]) -> dict[str, list[str]]:
    findings = {}
    for path in paths:
        if path in exclude or not path.is_file():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        hits = scan_text(text)
        if hits:
            findings[str(path.relative_to(REPO_ROOT))] = hits
    return findings


def scan_history() -> dict[str, list[str]]:
    # Full-history patch scan. Cheap enough while this repo is young;
    # revisit if history grows large enough to matter.
    log = run("log", "-p", "--all")
    hits = scan_text(log)
    return {"<git history>": hits} if hits else {}


def self_test() -> int:
    if not FIXTURE.exists():
        print(f"FAIL: fixture missing: {FIXTURE}", file=sys.stderr)
        return 1
    text = FIXTURE.read_text()
    hits = set(scan_text(text))
    missing = set(PATTERNS) - hits
    if missing:
        print(f"FAIL: patterns that did NOT fire on the known-bad fixture: {sorted(missing)}", file=sys.stderr)
        return 1
    print(f"OK: all {len(PATTERNS)} patterns fired on the known-bad fixture.")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    findings = scan_files(candidate_files(), exclude={FIXTURE})
    findings.update(scan_history())

    if findings:
        print("Possible secrets found:", file=sys.stderr)
        for location, hits in findings.items():
            print(f"  {location}: {', '.join(hits)}", file=sys.stderr)
        return 1

    print("No secret-shaped strings found in tracked/staged/untracked files or git history.")
    print("(A zero-hit result is not proof of absence -- see docstring.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
