#!/usr/bin/env python3
"""Compute a comparable signature for a `terraform show -json <plan>` document.

Used by preflight-fingerprint-check.sh Layer 2 to detect whether a fresh
plan differs meaningfully from the approved plan.

FIX 2026-09-01 (per review of the first Layer-2 fix):
comparing only (address, actions) catches drift that changes WHAT happens
(create/update/delete) but misses drift that keeps the same action while
changing WHAT VALUE is applied -- e.g. someone edits a .tf source after
approval (tag value, ACL, etc.) without touching the approved plan FILE.
Layer 1 (plan-file sha256) doesn't catch this either, since the approved
plan file itself is untouched -- only the newly-generated plan differs.

So the signature now includes each change's `after` values, with any
`after_unknown` leaf stripped out (values only known post-apply, e.g.
generated ARNs/ids, must not be compared -- they legitimately differ
between two independently-generated plans of the same config).

NOTE (review, 2026-09-01, low-risk / not urgent): known `after`
values are JSON-serialized as-is into the diff output on BLOCKED. Fine for
this course's resources, but if this pattern is ever reused for a resource
carrying sensitive values (e.g. an RDS master password), that value would
be printed verbatim in the BLOCKED diff. Revisit (e.g. mask fields Terraform
itself marks `sensitive` in the schema) before pointing this at such a
resource -- not needed for anything in this repo today.
"""
import json
import sys


def strip_unknown(after, unknown):
    if isinstance(unknown, bool):
        return None if unknown else after
    if isinstance(after, dict) and isinstance(unknown, dict):
        return {k: strip_unknown(v, unknown.get(k, False)) for k, v in after.items()}
    if isinstance(after, list) and isinstance(unknown, list):
        return [
            strip_unknown(v, unknown[i] if i < len(unknown) else False)
            for i, v in enumerate(after)
        ]
    return after


def signature(doc):
    out = []
    for c in doc.get("resource_changes", []):
        change = c["change"]
        known_after = strip_unknown(
            change.get("after") or {}, change.get("after_unknown") or {}
        )
        out.append(
            (
                c["address"],
                tuple(change["actions"]),
                json.dumps(known_after, sort_keys=True),
            )
        )
    return sorted(out)


if __name__ == "__main__":
    doc = json.load(sys.stdin)
    print(signature(doc))
