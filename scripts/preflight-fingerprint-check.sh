#!/usr/bin/env bash
# preflight-fingerprint-check.sh
#
# Section 4 "Approval Gate with Fingerprint Verification" — reference implementation.
# Fills the "Unreviewed Diff" line in the Pre-flight Check from
# Safe-Deployment-Workflow-design.md (§5, §9).
#
# Two layers, run in order — either one failing blocks apply:
#   Layer 1 (tamper check): has the saved plan FILE been modified since approval?
#   Layer 2 (drift check):  has the ACTUAL infrastructure changed since the plan
#                            was generated? (someone click-ops'd in the console,
#                            another pipeline ran, etc.) `terraform apply tfplan`
#                            alone does not reliably catch this in all cases —
#                            a fresh `plan -detailed-exitcode` right before apply does.
#
# Usage:
#   ./preflight-fingerprint-check.sh <plan-file> <approval-packet.md>
#
# Exit codes:
#   0 = READY (safe to apply)
#   1 = BLOCKED (do not apply — see stderr for reason)
#   2 = usage / missing-file error (not a security finding, just bad invocation)

set -euo pipefail

PLAN_FILE="${1:-}"
APPROVAL_PACKET="${2:-}"

if [[ -z "$PLAN_FILE" || -z "$APPROVAL_PACKET" ]]; then
  echo "usage: $0 <plan-file> <approval-packet.md>" >&2
  exit 2
fi

if [[ ! -f "$PLAN_FILE" ]]; then
  echo "PRE-FLIGHT CHECK"
  echo ""
  echo "Plan File        FAIL (not found: $PLAN_FILE)"
  echo ""
  echo "RESULT: BLOCKED"
  exit 1
fi

if [[ ! -f "$APPROVAL_PACKET" ]]; then
  echo "PRE-FLIGHT CHECK"
  echo ""
  echo "Approval Packet  FAIL (not found: $APPROVAL_PACKET)"
  echo ""
  echo "RESULT: BLOCKED"
  exit 1
fi

# --- Layer 0: was this plan actually approved? -----------------------------
# The Approval Packet template (safe-deployment-workflow-design.md §2) has a
# checkbox section. We look for the literal "- [x] APPROVED" (case-insensitive
# on the x). This is intentionally dumb/literal — a human ticks a box, we read
# the box. No inference about intent.
if ! grep -qiE '^\s*-\s*\[x\]\s*APPROVED\s*$' "$APPROVAL_PACKET"; then
  echo "PRE-FLIGHT CHECK"
  echo ""
  echo "Approval Status  FAIL (no '- [x] APPROVED' line found in $APPROVAL_PACKET)"
  echo ""
  echo "RESULT: BLOCKED"
  exit 1
fi

# --- Layer 1: plan file tamper check ----------------------------------------
# Expect a fingerprint recorded alongside the approval, e.g. a file
# named "<approval-packet>.sha256" written at approval time by plan.sh.
# If it's missing, that's itself a finding (approval happened without a
# recorded fingerprint — treat as BLOCKED, not as "skip this check").
FINGERPRINT_FILE="${APPROVAL_PACKET}.sha256"

if [[ ! -f "$FINGERPRINT_FILE" ]]; then
  echo "PRE-FLIGHT CHECK"
  echo ""
  echo "Plan Fingerprint FAIL (no recorded fingerprint: $FINGERPRINT_FILE)"
  echo ""
  echo "RESULT: BLOCKED"
  exit 1
fi

RECORDED_HASH="$(cat "$FINGERPRINT_FILE")"
CURRENT_HASH="$(sha256sum "$PLAN_FILE" | awk '{print $1}')"

if [[ "$RECORDED_HASH" != "$CURRENT_HASH" ]]; then
  echo "PRE-FLIGHT CHECK"
  echo ""
  echo "Plan Fingerprint FAIL"
  echo "  recorded: $RECORDED_HASH"
  echo "  current:  $CURRENT_HASH"
  echo "  ⇒ the plan file changed after approval. A changed file after"
  echo "    approval invalidates that approval (Safe Deployment Workflow §3)."
  echo ""
  echo "RESULT: BLOCKED"
  exit 1
fi

# --- Layer 2: live drift check ----------------------------------------------
# FIX 2026-09-01 (found by actually running this against real AWS
# on a first-ever apply -- see docs/production/dual-session-tooling.md history):
# `-detailed-exitcode` returning 2 means "there are pending changes", which is
# ALSO true, correctly, the very first time a brand-new plan is applied (nothing
# exists yet, so of course a fresh plan shows the same N resources to add).
# Treating exit-2-always-as-drift made the gate BLOCK every first apply, not
# just real drift. What actually matters is whether the fresh plan's resource
# changes differ from the APPROVED plan's resource changes -- so we diff the
# two plans' JSON resource_changes, not just the exit code.
#
# FIX 2026-09-01 #2 (review catch, reproduced against real AWS):
# comparing only (address, actions) misses a post-approval SOURCE EDIT that
# keeps the same action/address but changes a value (e.g. a tag) -- Layer 1
# doesn't catch this either, since the approved plan FILE is untouched.
# scripts/lib/plan-signature.py includes known `after` values in the
# signature (after_unknown leaves excluded, since those legitimately differ
# between two independently-generated plans).
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib"
set +e
terraform plan -out=/tmp/preflight-drift-check.$$.tfplan -input=false -lock=false >/tmp/preflight-drift-check.$$.log 2>&1
PLAN_EXIT=$?
set -e

if [[ "$PLAN_EXIT" -ne 0 ]]; then
  echo "PRE-FLIGHT CHECK"
  echo ""
  echo "Unreviewed Diff  FAIL (terraform plan errored — see /tmp/preflight-drift-check.$$.log)"
  echo ""
  echo "RESULT: BLOCKED"
  exit 1
fi

APPROVED_CHANGES="$(terraform show -json "$PLAN_FILE" | python3 "$LIB_DIR/plan-signature.py")"
FRESH_CHANGES="$(terraform show -json /tmp/preflight-drift-check.$$.tfplan | python3 "$LIB_DIR/plan-signature.py")"

if [[ "$APPROVED_CHANGES" != "$FRESH_CHANGES" ]]; then
  echo "PRE-FLIGHT CHECK"
  echo ""
  echo "Unreviewed Diff  FAIL"
  echo "  ⇒ Re-planning right now produces a DIFFERENT set of resource changes"
  echo "    than the approved plan (console edit, another pipeline run, drift)."
  echo "    Re-run plan.sh and get fresh approval before applying."
  echo "  approved: $APPROVED_CHANGES"
  echo "  fresh:    $FRESH_CHANGES"
  echo ""
  echo "RESULT: BLOCKED"
  exit 1
fi
rm -f "/tmp/preflight-drift-check.$$.tfplan" "/tmp/preflight-drift-check.$$.log"

# --- All layers passed -------------------------------------------------------
echo "PRE-FLIGHT CHECK"
echo ""
echo "Approval Status   PASS"
echo "Plan Fingerprint  PASS"
echo "Unreviewed Diff   PASS"
echo ""
echo "RESULT: READY"
exit 0
