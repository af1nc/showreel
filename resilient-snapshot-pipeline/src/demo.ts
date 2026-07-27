/**
 * Narrated end-to-end demo of the resilient snapshot pipeline.
 *
 * Act 1 (PRODUCER) - a rate-limited source is collected across several "hourly"
 * runs. Partial progress accumulates in staging; the LIVE table is only ever
 * written by an atomic promote once every required entity is present, so it never
 * holds a partial snapshot.
 *
 * Act 2 (CONSUMER) - we then simulate the ORIGINAL bug: a naive producer writes a
 * newer but partial snapshot straight into the LIVE table. We compare the three
 * read strategies to show how the fail-safe readers keep the dashboard whole.
 *
 * Everything is deterministic (no wall-clock, no randomness), so the printed
 * story is identical on every run.
 */

import { openDb, insertRows, LIVE_TABLE } from "./db";
import type { SnapshotRow } from "./db";
import { createFlakySource } from "./fakeSource";
import { ProgressivePipeline } from "./progressiveFill";
import {
  naiveLatestSnapshot,
  latestValidSnapshot,
  perEntityLatestSnapshot,
} from "./failsafe";
import {
  REQUIRED_ENTITIES,
  COMPLETENESS_THRESHOLD,
} from "./config";

const line = (s = "") => console.log(s);
const rule = () => line("-".repeat(72));

/** Distinct entity codes present in a set of rows. */
function entitiesIn(rows: SnapshotRow[]): string[] {
  return [...new Set(rows.map((r) => r.entity))].sort();
}

function describeLive(rows: SnapshotRow[]): string {
  const present = entitiesIn(rows);
  const complete = present.length >= COMPLETENESS_THRESHOLD;
  if (rows.length === 0) return "LIVE is empty (no complete snapshot yet)";
  const snapDates = [...new Set(rows.map((r) => r.snapshot_date))].sort();
  return `${present.length}/${COMPLETENESS_THRESHOLD} required entities ` +
    `[${present.join(", ")}]  snapshot_date(s)=${snapDates.join(",")}  ` +
    (complete ? "COMPLETE ✅" : "PARTIAL ⚠️");
}

function act1(): ReturnType<typeof openDb> {
  line("═".repeat(72));
  line("ACT 1 - PRODUCER: progressive fill over a rate-limited source");
  line("═".repeat(72));
  line(
    "The source refuses ~60% of entities per run (deterministically), then its\n" +
    "quota window clears at run 5. Watch staging accumulate while LIVE stays\n" +
    "either empty or complete - never partial.",
  );

  const db = openDb(); // in-memory
  const source = createFlakySource({
    seed: "demo",
    rateLimitedPercent: 60,
    recoveryRun: 5,
  });
  const pipeline = new ProgressivePipeline(db, source);

  const snapshotDate = "2024-02-01"; // the "day" being collected
  const MAX_RUNS = 6;

  for (let run = 1; run <= MAX_RUNS; run++) {
    const r = pipeline.runCycle(snapshotDate, run);
    rule();
    line(`RUN ${run} (hourly invocation)`);
    line(`  fetched this run : ${r.fetchedThisRun.join(", ") || "(none)"}`);
    line(`  rate-limited     : ${r.rateLimitedThisRun.join(", ") || "(none)"}`);
    line(`  required staged  : ${r.requiredInStaging.length}/${COMPLETENESS_THRESHOLD}` +
      (r.missingRequired.length ? `  (missing ${r.missingRequired.join(", ")})` : ""));
    line(`  promoted?        : ${r.promoted ? "YES - atomic staging→live" : "no"}`);
    line(`  note             : ${r.note}`);
    line(`  LIVE now         : ${describeLive(naiveLatestSnapshot(db))}`);
    if (r.promoted) {
      line();
      line("  ✔ LIVE went straight from empty to COMPLETE. A reader never once");
      line("    saw a partial snapshot, despite 3+ rate-limited runs.");
      return db;
    }
  }
  return db;
}

function act2(db: ReturnType<typeof openDb>): void {
  line();
  line("═".repeat(72));
  line("ACT 2 - CONSUMER: what happens when a PARTIAL lands in LIVE anyway");
  line("═".repeat(72));
  line(
    "Now simulate the original bug: a naive producer writes a NEWER but partial\n" +
    "snapshot (only 2 of 6 required entities) directly into LIVE. Compare the\n" +
    "three read strategies.",
  );

  // Fault injection: a non-flaky source used only to mint rows, written straight
  // to LIVE (bypassing the safe promote) to reproduce the partial-snapshot bug.
  const minter = createFlakySource({ seed: "inject", rateLimitedPercent: 0, recoveryRun: 1 });
  const partialDate = "2024-02-02"; // newer than the complete snapshot
  const partialEntities = REQUIRED_ENTITIES.slice(0, 2); // alpha, bravo only
  const partialRows: SnapshotRow[] = [];
  for (const e of partialEntities) partialRows.push(...minter.fetch(e, partialDate, 1));
  insertRows(db, LIVE_TABLE, partialRows);
  line();
  line(`Injected partial snapshot ${partialDate}: only [${partialEntities.map((e) => e.code).join(", ")}].`);
  rule();

  line("1) naiveLatestSnapshot()  - WHERE snapshot_date = MAX(snapshot_date)   [THE BUG]");
  line(`     -> ${describeLive(naiveLatestSnapshot(db))}`);
  line("     The newest snapshot wins even though it is partial: 4 entities vanish.");
  line();

  line("2) latestValidSnapshot()  - newest snapshot passing the completeness gate");
  const valid = latestValidSnapshot(db, {
    completenessColumn: "entity",
    threshold: COMPLETENESS_THRESHOLD,
  });
  line(`     -> ${describeLive(valid)}`);
  line("     The partial fails HAVING COUNT(DISTINCT entity) >= threshold, so the");
  line("     reader falls back to the last COMPLETE snapshot. Dashboard stays whole.");
  line();

  line("3) perEntityLatestSnapshot() - each entity resolves to its OWN latest");
  const perEntity = perEntityLatestSnapshot(db, { groupBy: ["entity", "series_date"] });
  line(`     -> ${describeLive(perEntity)}`);
  line("     Strongest guarantee: alpha & bravo show their FRESH data from the new");
  line("     snapshot, the other four keep their last-good data. Nobody blanks.");
  rule();
  line("Defense in depth: the producer tries never to write a partial, and the");
  line("consumer refuses to render one even if it somehow appears.");
}

function main(): void {
  const db = act1();
  act2(db);
  db.close();
}

main();
