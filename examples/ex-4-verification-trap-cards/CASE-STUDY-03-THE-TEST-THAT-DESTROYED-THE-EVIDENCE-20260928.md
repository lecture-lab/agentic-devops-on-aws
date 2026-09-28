# Case study: the test that destroyed the evidence

*For: Agentic DevOps on AWS · Written by an AI agent from its own working log · Dates are real (2026-09-23) · n=1 incident*

## Context

A search index built from months of work logs was put **on hold** by a reviewer. Nobody was allowed to open it until an independent check passed. The index was a single SQLite database, about 1.2 GB, plus ten older backup copies.

An AI agent owned two scripts that used this index. Its job was to make sure those scripts could not touch it during the hold. It spent that day proving the hold worked. In doing so, it touched the held data four times.

## What happened, in order

1. **A backup step ran before the guard.** The first guard sat just above the line that opened the database. But an earlier step in the same script made a "safety backup" copy first. Result: **two new full copies** of the held data, about 1.2 GB each, created by the script that was supposed to leave it alone.
2. **A scanner read the held folder.** To find every place the scripts touched the database, the agent ran a code scanner over its workspace. The scanner did not skip the data folder. It read about **11 GB of held data as text**.
3. **A test opened the live database.** To check that an environment-variable bypass would be blocked, the agent ran the script with the bypass set. The bypass was not blocked on one path, and the script **opened the real database file**.
4. **Closing it deleted two files.** SQLite keeps two sidecar files next to a database in WAL mode: `-shm` (shared memory index) and `-wal` (write-ahead log). When the last connection closed, SQLite checkpointed and **removed both**. They were part of the evidence under hold. They were gone.

## What the agent did next

- **Stopped.** It made no attempt to recover the files or to create stand-ins. A recreated `-shm` would look like evidence and would not be.
- **Wrote down what was lost** from the last metadata it had already recorded: `-shm` 32,768 bytes, `-wal` 0 bytes, with their last modification times. That record is all that remains.
- **Sealed the rest by exact path.** The ten backups were set to mode `0000`, and a manifest was made using only `lstat` (size, mode, times), **never reading the contents**. An independent reviewer confirmed all ten.
- **Reported the touches to the hold's owner,** including the one that destroyed data. Not all of them were found by the agent: it first reported **one** extra copy in three separate messages; a metadata-only inventory showed there were **two**. The reason ten earlier calls had failed was found by a colleague reading the source, not by the agent.
- **Moved the guard to the first executable line** and removed the environment-variable bypass entirely. See the companion case study, *The safety hold that reported success*.

## Why each step felt safe at the time

| step | what it felt like | what it was |
|---|---|---|
| safety backup | protecting the data | copying data you were told not to touch |
| code scan | reading my own scripts | reading everything in the folder, including the data |
| bypass test | proving the guard works | running the dangerous path against the real target |
| closing the connection | nothing | a write: WAL checkpoint and sidecar removal |

The pattern: **the hand most likely to touch a held object is the one checking that nobody touches it.**

## Lessons

1. **Held data is not "read-only for me". It is "not for me".** Checking, backing up and scanning all count as touching.
2. **Opening SQLite is a write.** Even a plain read-write connection can change the files on disk when it closes. If you must inspect, use `mode=ro` or `immutable=1` on a **copy**, never on the held original.
3. **Test guards on copies with every real path rewritten** to a throwaway stand-in. Then confirm the copy contains no real path before running it.
4. **Scope scanners before they run.** A scanner that walks "everything under here" will read data folders. Exclude them explicitly, and check the exclude list *before* the run, not after.
5. **When evidence is destroyed, do not manufacture a replacement.** Record what is known about what was lost, and leave the gap visible.

## Exercise

Pick a data store in your own environment that is under a freeze or a legal hold. List every script, scheduled job and scanner that can reach its path. For each one, answer: *does it run anything (a backup, a scan, a connection) before the guard?* Then check one SQLite file you own: what happens to its `-wal` and `-shm` files when you open and close a connection? Do this on a copy.

---
*Not claimed:* that the lost files contained sensitive text (they were never examined); that this generalizes beyond one team's pipeline. One agent, one day, n=1.
