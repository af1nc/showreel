[← Showreel](..)

# 🛡️ Resilient Snapshot Pipeline

![Systems & reliability](https://img.shields.io/badge/Systems_%26_reliability-f59e0b) ![TypeScript](https://img.shields.io/badge/TypeScript-3178c6?logo=typescript&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

A **defense-in-depth** pattern for keeping a dashboard that is fed by a
**rate-limited external API** from ever going blank.

It has two halves that back each other up:

- **Producer** (`progressiveFill.ts`) - collects data across many scheduled runs,
  accumulating partial progress in a staging table and only ever **atomically
  promoting a complete snapshot** to the live table.
- **Consumer** (`failsafe.ts`) - read helpers that refuse to render a partial
  snapshot even if one somehow reaches the live table.

```
rate-limited API ──▶ staging (accumulates)  ──atomic promote when complete──▶  LIVE
                                                                                 │
                                              fail-safe readers ◀───────────────┘
                                              (never surface a partial)
```

## The story it came from

The original bug was a single line of SQL every reader shared:

```sql
WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM snapshots)
```

When the upstream API got rate-limited, one collection run wrote a **partial**
snapshot. Every reader's `MAX(snapshot_date)` immediately selected that partial,
and the dashboard went blank for every entity that run happened to miss. This
module is the fix for that whole class of bug, on both the write and read sides.

## The interesting part

**Producer - progressive fill with atomic promotion:**
- Each run **resumes**: it reads which entities earlier runs already banked for
  today's `snapshot_date` and fetches **only the missing ones** (required first).
  A rate-limited day finishes across many runs instead of restarting from zero.
- It **gates on completeness**: only when every required entity is present does it
  promote - inside a single transaction (`DELETE` live + `INSERT` from staging +
  clear staging), so a reader can never observe the gap and a mid-promote crash
  rolls back to the previous complete snapshot.
- If still incomplete, it **exits cleanly**, leaving the last complete snapshot
  live and untouched. A stale-staging GC stops abandoned days accumulating.

**Consumer - three read strategies, weakest to strongest:**
1. `naiveLatestSnapshot` - the original bug, kept only to contrast against.
2. `latestValidSnapshot` - the newest snapshot passing a
   `HAVING COUNT(DISTINCT entity) >= threshold` completeness gate, with a
   `COALESCE` fallback so a reader never gets `NULL`.
3. `perEntityLatestSnapshot` - the strongest guarantee: each `(entity, period)`
   group resolves to its **own** latest snapshot, so one entity's bad run can
   never blank another. (It groups rather than row-dedups on purpose - one run
   legitimately emits several sub-series rows per entity, and partitioning on the
   sub-series too would silently drop most of them.)

The query builders take table/column names from **code constants only** and
validate them against an identifier allowlist, so they are never a SQL-injection
surface; all values are bound parameters.

## Run it

```bash
npm install
npm run demo
```

The demo runs deterministically (no wall-clock, no randomness) and prints a
two-act story: the producer completing a snapshot across several rate-limited
runs without ever exposing a partial, then the consumer keeping the dashboard
whole after a partial is deliberately injected into the live table.

## What was stubbed for the demo

- **Warehouse → SQLite.** Production used a cloud data warehouse with
  server-side transactions; here it is a single in-memory SQLite database, chosen
  specifically because it gives *real* `BEGIN`/`COMMIT`/`ROLLBACK` - the whole
  point of the atomic promote. It uses Node's built-in
  [`node:sqlite`](https://nodejs.org/api/sqlite.html) (Node 22.5+) so there is
  **nothing to compile and no runtime dependency**; `better-sqlite3` is a drop-in
  swap if you prefer it.
- **Rate-limited API → a synthetic flaky source** (`fakeSource.ts`) that refuses
  a deterministic subset of entities per run and then "recovers", reproducing the
  real failure mode reproducibly.
- The domain (markets, competitor brands, a weekly series) is replaced by generic
  entities (`alpha` through `hotel`) and series.

---

MIT · Part of [Showreel](..), twelve standalone engineering projects.
