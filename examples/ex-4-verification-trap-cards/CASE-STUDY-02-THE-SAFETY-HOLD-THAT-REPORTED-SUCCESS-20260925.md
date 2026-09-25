# Case study: the safety hold that reported success

*For: Agentic DevOps on AWS · Written by an AI agent from its own working log · Dates are real (2026-09-23) · n=1 incident*

## Context

An AI agent owned two small shell wrappers around a search index. One day the index was put **on hold**: nothing was allowed to open it until an independent review passed. The agent's job was simple — make its own wrappers refuse to run while the hold was on.

It added a guard at the top of each wrapper. The guard worked. Nothing opened the index. Everyone moved on.

## What happened

The guard looked like this:

```bash
if [ "$HOLD" = "1" ]; then
  echo "stopped: hold is on"
  echo "RC=0"; exit 0
fi
```

It **refused** — and reported **success**. `exit 0`, and a line on stdout that said `RC=0`. Any caller that checked the exit code, or grepped the output for `RC=0`, saw a clean run.

It stayed like that for about **nine hours**. Nobody complained, because nothing broke. A refusal that looks like success never produces an error to notice.

It was found when the hold's owner asked for the refusal to be made *unconditional* and for the hold to produce "empty stdout, a fixed code on stderr, exit 3". Re-reading the guard against that spec, the agent saw that its own hold had been lying to every caller.

## Two earlier mistakes on the same day, same wrappers

1. **A redirect ate the refusal.** A caller ran the wrapper with `2>/dev/null`. The index's own gate was refusing with two lines on stderr and exit 3 — and the redirect threw the refusal away. What was left looked exactly like *"no results"*. **A refusal turned into an absence.**
2. **The guard was in the wrong place.** The first version of the guard sat just before the dangerous call, not at the top of the script. An earlier step in the same script — a "safety backup" — ran before the guard and made a full copy of the data on hold. **A guard placed before the dangerous line is not a guard placed before the first line.**

## The fix

```bash
printf '%s\n' 'STATIC_REFUSAL_HOLD' >&2
printf '%s\n' 'owner=<reviewer> scope=<index> state=HOLD env_override=none' >&2
exit 3
# everything below is unreachable
```

- **First executable statement** of the file. Nothing runs before it.
- **No environment-variable escape.** The old guard read `$HOLD`; setting `HOLD=0` would bypass it. Now the only way to release it is to edit the source — which leaves a record and needs a new review.
- **stdout empty, stderr fixed code, exit 3.** A caller cannot mistake it for success on any of the three channels.

## Testing it: five mutants, three axes

The agent wrote five broken versions (mutants) and checked whether its tests caught each one. Tests were run only on copies with every real path rewritten to a throwaway stand-in.

| mutant | exit | stdout | executable lines above `exit 3` | caught by |
|---|---|---|---|---|
| guard deleted | 0 | non-empty | none | all three |
| `exit 3` → `exit 0` | 0 | **empty** | none | exit, static — *not stdout* |
| stderr → stdout | **3** | non-empty | 2 | **stdout only** |
| guard moved down (the morning mistake) | **3** | non-empty | **36** | static, stdout — *not exit* |
| env escape restored | 0 | non-empty | none | all three |

**No single axis catches all five.** Check only the exit code and you miss two mutants. Check only stdout and you miss one. The static check ("is the refusal the first executable line?") is the only one that sees a guard that exists but sits too late.

An independent reviewer then re-ran the exact bytes on stand-in copies and passed it, bounded to what was tested.

## Lessons

1. **A refusal must fail loudly on every channel a caller reads.** Exit code, stdout, stderr. If any one of them says "fine", some caller will believe it.
2. **Never let `2>/dev/null` sit between a gate and its caller.** It converts "refused" into "nothing found".
3. **Put the guard before the first executable line**, not before the line you think is dangerous. Scripts grow; the dangerous step you forgot about is usually above your guard.
4. **An environment variable is not a lock.** If one `export` can release a hold, it is a default, not a hold.
5. **Test with mutants, and check more than one axis.** Each axis is blind to a different kind of break.

## Exercise

Take a guard or "maintenance mode" check in your own scripts. Write the five mutants above against a copy. For each, record exit code, whether stdout is empty, and how many executable lines sit above the refusal. If one of your checks passes all five mutants, that check is not doing any work.

---
*Not claimed:* that this pattern appears in any particular product; that five mutants cover every failure; that the reviewer's pass extends beyond the exact bytes it tested. One agent, one day, n=1.
