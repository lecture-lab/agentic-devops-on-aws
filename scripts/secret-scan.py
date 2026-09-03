#!/usr/bin/env python3
"""Secret scanner for this repo (reviewer F5).

A zero-hit result is not proof of absence -- so this script also carries
a self-test that proves the patterns actually fire. The self-test builds
its known-bad sample strings *in memory, from fragments, at runtime* --
not from a committed fixture file. An earlier version of this script
used a committed fixture containing literal secret-shaped strings; once
committed, `scan_history()` (which greps the full `git log -p --all`)
would find them forever, since deleting the file in a later commit does
not remove it from prior commits. Building the samples in memory means
no tracked file, and no git commit, ever contains a contiguous
secret-shaped string -- there is nothing for history-scanning to poison
itself with.

Modes:
  secret-scan.py --staged   scan tracked + staged + untracked candidate
                             files only (no history). Fast; this is what
                             the pre-commit hook runs, so it gates *new*
                             secrets without being permanently blocked by
                             something already in past history.
  secret-scan.py --full     everything --staged does, plus full git
                             history. Slower, and history-poisoning is
                             one-way: once a secret-shaped string is
                             committed, this will keep flagging it in
                             every future run until history itself is
                             rewritten (a deliberate, separately-authorized
                             action -- not something this script does).
                             Meant for manual/periodic audits, not as a
                             commit gate.
  secret-scan.py --self-test
                             build known-bad samples in memory and assert
                             every pattern fires at least once. Exit 1 if
                             the scanner is not actually working.

No CI is wired up for this repo yet -- `core.hooksPath .githooks` is
local git config, not something a fresh clone inherits automatically.
See README.md for the one-time bootstrap step.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

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


def scan_files(paths: set[Path]) -> dict[str, list[str]]:
    findings = {}
    for path in paths:
        if not path.is_file():
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


def _known_bad_samples() -> dict[str, str]:
    """Assembled from short fragments so no contiguous secret-shaped
    substring exists anywhere in this file's own source text."""
    return {
        "aws_access_key": "AKIA" + "A" * 16,
        "telegram_bot_token": "1" * 9 + ":" + "A" * 35,
        "github_token": "gh" + "p" + "_" + "A" * 36,
        "private_key": "-----BEGIN " + "RSA PRIVATE KEY" + "-----",
        "jwt": ("eyJ" + "A" * 12) + "." + ("A" * 12) + "." + ("A" * 12),
        "credential_bearing_url": "https" + "://" + "user" + ":" + "p" * 12 + "@" + "example.invalid/",
        "generic_assignment": "password" + " = " + '"' + "x" * 12 + '"',
    }


def self_test() -> int:
    samples = _known_bad_samples()
    missing = [name for name, pattern in PATTERNS.items() if not pattern.search(samples.get(name, ""))]
    if missing:
        print(f"FAIL: patterns that did NOT fire on the in-memory known-bad samples: {sorted(missing)}", file=sys.stderr)
        return 1
    print(f"OK: all {len(PATTERNS)} patterns fired on in-memory known-bad samples (nothing written to disk or git).")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    full = "--full" in sys.argv
    if not full and "--staged" not in sys.argv:
        print("usage: secret-scan.py --staged | --full | --self-test", file=sys.stderr)
        return 2

    findings = scan_files(candidate_files())
    scope = "tracked/staged/untracked files"
    if full:
        findings.update(scan_history())
        scope += " and git history"

    if findings:
        print("Possible secrets found:", file=sys.stderr)
        for location, hits in findings.items():
            print(f"  {location}: {', '.join(hits)}", file=sys.stderr)
        return 1

    print(f"No secret-shaped strings found in {scope}.")
    print("(A zero-hit result is not proof of absence -- see docstring.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
