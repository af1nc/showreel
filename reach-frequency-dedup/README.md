[← Showreel](..)

# 📡 Reach & Frequency Dedup

![Data science & ML](https://img.shields.io/badge/Data_science_%26_ML-3b82f6) ![TypeScript](https://img.shields.io/badge/TypeScript-3178c6?logo=typescript&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

A small, standalone TypeScript library for combining **audience reach** across
media channels correctly, plus a generic **stale-while-revalidate** cache for
serving an expensive computation without ever blocking readers.

If a Display campaign reaches 3,000,000 people and a Video campaign reaches
2,000,000 people **in the same market**, the combined reach is *not* 5,000,000 -
the two audiences overlap, and anyone who saw both ads is one person counted
twice. This library models that overlap and gives you the true deduplicated
**net reach**, then derives **frequency** (average times a reached person saw an
ad) from it.

## The interesting part

### 1. The Sainsbury (random-duplication) net-reach model

Assume each channel reaches a random subset of a fixed population `N` (the
"universe"), independently of the others. The chance a given person is *missed*
by channel `i` is `1 - r_i / N`. Under independence, the chance they are missed
by **every** channel is the product of those terms, so the deduplicated reach is

```
net = N * (1 - PROD_i (1 - r_i / N))
```

Two additivity rules fall out of this, and getting them right is the whole game:

- **Within a market, reach is NOT additive** - audiences overlap, so you must
  dedup with the formula above.
- **Across markets, reach IS additive** - populations are disjoint, so the
  campaign total is simply the sum of per-market net reach. No cross-market
  overlap exists to remove.

**Frequency = impressions / net reach.** Impressions *are* additive (every
exposure counts), so we sum them and divide by the deduplicated reach.

### 2. The log-space underflow trick

Multiplying many terms that are each very close to 1 loses precision (and, with
enough terms, underflows) in floating-point arithmetic. So the product is
computed in **log space** - turning a product of near-1 factors into a sum of
logs, which is numerically stable even with hundreds of channels:

```
net = N * (1 - EXP(SUM_i LN(1 - r_i / N)))
```

Each ratio is clamped just below 1 (a channel can't reach more than the whole
population, and `LN(0)` is `-Infinity`). When there is **no** population universe
available, the model falls back to the largest single-channel reach as a
conservative floor - the true net reach is at least the biggest individual
channel, but without a universe we can't model the overlap of the rest.

### 3. Stale-while-revalidate with a single-flight refresh

The reach computation over a full dataset can be slow (in the system this was
extracted from, a multi-second analytical rebuild). Running it on every read is
a non-starter, so the result is **materialized** and served from cache:

- `get()` returns the cached value **immediately** when one exists - even if it
  is stale. Readers never block on the slow path.
- When the value is stale, `get()` kicks off **at most one** background refresh.
  Concurrent callers that all see a stale cache **share** the same in-flight
  recompute (the "single-flight" guarantee) instead of each starting their own.
- Only the very first call (cold cache - nothing to serve) awaits the compute.
- A failed background refresh never rejects a reader; the last good value keeps
  being served and the next `get()` retries.

The cache is storage-agnostic: the "materialized result" is just an in-process
value here, but you can swap `compute` for a DB write + read-back, a file, or a
remote cache without touching the concurrency logic.

## Run it

```bash
npm install
npm run demo
```

The demo (`src/demo.ts`) uses synthetic data: three markets with disjoint
populations, each with several channels carrying `(reach, impressions)` and a
population universe (the third market has none, to exercise the fallback). It
prints per-market deduplicated net reach + frequency, then the campaign total -
showing that reach is deduped *within* a market but additive *across* markets.
It then runs the SWR cache against a deliberately slow computation, showing
readers being served instantly while a single background refresh runs.

Type-check only:

```bash
npm run typecheck
```

## API

```ts
import {
  computeNetReach,      // (channels, universe) -> deduped reach (log-space Sainsbury)
  computeFrequency,     // (impressions, netReach) -> frequency
  computeMarketReach,   // one market -> full result incl. naive-vs-net contrast
  computeCampaignReach, // many markets -> per-market + additive-across total
} from "./src/reachDedup.js";

import { StaleWhileRevalidate } from "./src/staleWhileRevalidate.js";

const cache = new StaleWhileRevalidate({
  ttlMs: 180_000,
  compute: async () => expensiveRebuild(),
});
const value = await cache.get(); // instant when warm; refreshes in background when stale
```

## What was stubbed

This module is extracted from a production analytics system and re-implemented so
it runs anywhere with no cloud dependencies:

- **BigQuery SQL → in-memory TypeScript.** The original computed the Sainsbury
  maths as a SQL query (`SUM(LN(...))`, `EXP(...)`) over a warehouse table. Here
  the identical math runs as pure functions over in-memory rows - cleaner to read
  and runnable with zero infrastructure.
- **Materialized warehouse table → in-process cache.** The original cached the
  slow query result into a materialized table and rebuilt it on a
  stale-while-revalidate cadence. Here the same pattern is a generic in-process
  `StaleWhileRevalidate<T>` wrapper. The concurrency guarantees (serve stale
  instantly, single-flight background refresh) are identical.
- **Data source & schema.** The real column names, table names, market
  normalization, and row-replication cleanup are specific to the source system
  and are not part of the reusable idea, so they are omitted.

---

MIT · Part of [Showreel](..), twelve standalone engineering projects.
