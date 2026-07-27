/**
 * Progressive-fill staged writer - the PRODUCER side of the defense.
 *
 * The problem: the external API is rate-limited, so any single run can only
 * collect a subset of entities before it starts getting refused. Writing that
 * subset straight to the live table is exactly what caused a real
 * partial-snapshot incident - downstream readers picked the newest snapshot and
 * it was incomplete.
 *
 * The pattern (one "run" == one invocation, scheduled hourly):
 *
 *   1. GC - drop staging rows for snapshot dates older than the retention window
 *           so abandoned, never-completed days can't accumulate forever.
 *   2. RESUME - read which entities earlier runs of the SAME snapshot_date
 *           already landed in staging. We only ever fetch the missing ones. This
 *           makes the job idempotent and lets a rate-limited day finish across
 *           many runs instead of restarting from zero each time.
 *   3. SHORT-CIRCUIT - if staging is already complete (all required entities
 *           present), skip straight to promotion.
 *   4. FETCH - ask the source only for the missing entities (required first),
 *           append whatever it serves to staging. A refused entity simply isn't
 *           appended; it will be retried next run.
 *   5. GATE - recompute completeness. If every required entity is now present,
 *           PROMOTE atomically. Otherwise exit cleanly, leaving the last
 *           complete snapshot live and untouched.
 *
 * The promotion is a single atomic transaction:
 *     BEGIN
 *       DELETE FROM live      WHERE snapshot_date = @d
 *       INSERT INTO live      SELECT * FROM staging WHERE snapshot_date = @d
 *       DELETE FROM staging   WHERE snapshot_date = @d
 *     COMMIT
 * so a reader can never observe the gap between the delete and the insert, and a
 * crash mid-promote rolls back to the previous complete snapshot.
 */

import type { DatabaseSync } from "node:sqlite";
import {
  LIVE_TABLE,
  STAGING_TABLE,
  SNAPSHOT_COLUMNS,
  insertRows,
} from "./db";
import type { SnapshotRow } from "./db";
import {
  ALL_ENTITIES,
  REQUIRED_ENTITIES,
  STAGING_RETENTION_DAYS,
} from "./config";
import type { EntityDef } from "./config";
import type { ExternalSource } from "./fakeSource";

const REQUIRED_CODES = REQUIRED_ENTITIES.map((e) => e.code);

export interface CycleResult {
  snapshotDate: string;
  runIndex: number;
  /** Entities the source served (and we staged) on THIS run. */
  fetchedThisRun: string[];
  /** Entities the source rate-limited on THIS run. */
  rateLimitedThisRun: string[];
  /** Required entities present in staging AFTER this run (cumulative). */
  requiredInStaging: string[];
  /** Required entities still missing from staging after this run. */
  missingRequired: string[];
  /** True iff this run promoted a complete snapshot to the live table. */
  promoted: boolean;
  /** Short human-readable explanation of what happened. */
  note: string;
}

export class ProgressivePipeline {
  constructor(
    private readonly db: DatabaseSync,
    private readonly source: ExternalSource,
  ) {}

  /** Distinct entity codes already staged for a given snapshot_date. */
  private entitiesInStaging(snapshotDate: string): Set<string> {
    const rows = this.db
      .prepare(
        `SELECT DISTINCT entity FROM ${STAGING_TABLE} WHERE snapshot_date = @d`,
      )
      .all({ d: snapshotDate }) as unknown as { entity: string }[];
    return new Set(rows.map((r) => r.entity));
  }

  /** Drop staging rows for snapshots older than the retention window. */
  private cleanupStaleStaging(snapshotDate: string): number {
    const cutoff = subtractDays(snapshotDate, STAGING_RETENTION_DAYS);
    const info = this.db
      .prepare(`DELETE FROM ${STAGING_TABLE} WHERE snapshot_date < @cutoff`)
      .run({ cutoff });
    return Number(info.changes);
  }

  /**
   * Atomic promote. The whole block is one transaction: readers of the live
   * table see either the previous complete snapshot or the new one, never a gap
   * and never a partial. If anything throws, better-sqlite3 rolls the whole
   * transaction back.
   */
  private promote(snapshotDate: string): void {
    const cols = SNAPSHOT_COLUMNS.join(", ");
    const deleteLive = this.db.prepare(
      `DELETE FROM ${LIVE_TABLE} WHERE snapshot_date = @d`,
    );
    const copyFromStaging = this.db.prepare(
      `INSERT INTO ${LIVE_TABLE} (${cols})
       SELECT ${cols} FROM ${STAGING_TABLE} WHERE snapshot_date = @d`,
    );
    const clearStaging = this.db.prepare(
      `DELETE FROM ${STAGING_TABLE} WHERE snapshot_date = @d`,
    );
    // One atomic transaction: readers see either the previous complete snapshot
    // or the new one, never the gap. A throw mid-promote rolls the whole thing
    // back to the previous complete snapshot.
    this.db.exec("BEGIN");
    try {
      deleteLive.run({ d: snapshotDate });
      copyFromStaging.run({ d: snapshotDate });
      clearStaging.run({ d: snapshotDate });
      this.db.exec("COMMIT");
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
  }

  /** Order missing entities so required ones are fetched first. */
  private fetchOrder(completed: Set<string>): EntityDef[] {
    return ALL_ENTITIES.filter((e) => !completed.has(e.code)).sort((a, b) => {
      const aReq = REQUIRED_CODES.includes(a.code) ? 0 : 1;
      const bReq = REQUIRED_CODES.includes(b.code) ? 0 : 1;
      return aReq - bReq;
    });
  }

  /**
   * Run one collection cycle for `snapshotDate`. `runIndex` (1-based) is passed
   * through to the source so the demo's flakiness is deterministic; in
   * production the flakiness comes from the live API's own rate limiter.
   */
  runCycle(snapshotDate: string, runIndex: number): CycleResult {
    this.cleanupStaleStaging(snapshotDate);

    // RESUME: what earlier runs already banked for this snapshot_date.
    let completed = this.entitiesInStaging(snapshotDate);

    // SHORT-CIRCUIT: already complete -> just promote.
    if (REQUIRED_CODES.every((c) => completed.has(c))) {
      this.promote(snapshotDate);
      return this.result(snapshotDate, runIndex, [], [], completed, true,
        "Staging already complete on entry; promoted without re-fetching.");
    }

    // FETCH only the missing entities, required first.
    const fetchedThisRun: string[] = [];
    const rateLimitedThisRun: string[] = [];
    for (const entity of this.fetchOrder(completed)) {
      const rows: SnapshotRow[] = this.source.fetch(entity, snapshotDate, runIndex);
      if (rows.length > 0) {
        // Append immediately so partial progress survives a mid-run crash.
        insertRows(this.db, STAGING_TABLE, rows);
        fetchedThisRun.push(entity.code);
      } else {
        rateLimitedThisRun.push(entity.code);
      }
    }

    // GATE on the freshly-recomputed completeness.
    completed = this.entitiesInStaging(snapshotDate);
    const complete = REQUIRED_CODES.every((c) => completed.has(c));

    if (!complete) {
      const missing = REQUIRED_CODES.filter((c) => !completed.has(c));
      return this.result(
        snapshotDate, runIndex, fetchedThisRun, rateLimitedThisRun, completed, false,
        `Incomplete: still missing ${missing.join(", ")}. Live snapshot untouched; will resume next run.`,
      );
    }

    this.promote(snapshotDate);
    return this.result(
      snapshotDate, runIndex, fetchedThisRun, rateLimitedThisRun, completed, true,
      "All required entities present; promoted staging -> live atomically.",
    );
  }

  private result(
    snapshotDate: string,
    runIndex: number,
    fetchedThisRun: string[],
    rateLimitedThisRun: string[],
    completed: Set<string>,
    promoted: boolean,
    note: string,
  ): CycleResult {
    const requiredInStaging = REQUIRED_CODES.filter((c) => completed.has(c));
    const missingRequired = REQUIRED_CODES.filter((c) => !completed.has(c));
    return {
      snapshotDate,
      runIndex,
      fetchedThisRun,
      rateLimitedThisRun,
      requiredInStaging,
      missingRequired,
      promoted,
      note,
    };
  }
}

/** Subtract whole days from a YYYY-MM-DD string, returning YYYY-MM-DD (UTC). */
export function subtractDays(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const t = Date.UTC(y, m - 1, d) - days * 24 * 60 * 60 * 1000;
  return new Date(t).toISOString().slice(0, 10);
}
