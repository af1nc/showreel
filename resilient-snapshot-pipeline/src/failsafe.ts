/**
 * Snapshot fail-safe read helpers - the CONSUMER side of the defense.
 *
 * Single source of truth for "find the latest snapshot" across every reader.
 * It exists to replace the one line of SQL that caused a real production
 * partial-snapshot incident:
 *
 *     WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM snapshots)   -- the bug
 *
 * When an external source is rate-limited and a partial snapshot lands in the
 * live table, that naive `MAX(snapshot_date)` selects the partial and the
 * dashboard goes blank for every entity that run happened to miss. The whole
 * dashboard flips to the newest *version* even though that version is
 * incomplete.
 *
 * Three read strategies, weakest to strongest:
 *
 *   1. naiveLatestSnapshot        - the bug, kept only to contrast against.
 *   2. latestValidSnapshot        - the most recent COMPLETE snapshot (a
 *                                   completeness HAVING gate), with a COALESCE
 *                                   fallback to MAX so a reader never sees NULL.
 *   3. perEntityLatestSnapshot    - the strongest guarantee. Each (entity,
 *                                   period) group resolves to its OWN most
 *                                   recent snapshot, so one entity's bad run can
 *                                   never blank another entity.
 *
 * The builders take a table name and column names from CODE CONSTANTS (never
 * from request input) and validate them, so they are not a SQL-injection
 * surface. Read values are always passed as bound parameters.
 */

import type { DatabaseSync } from "node:sqlite";
import { LIVE_TABLE, SNAPSHOT_COLUMNS, assertIdentifier } from "./db";
import type { SnapshotRow } from "./db";

const SELECT_COLS = SNAPSHOT_COLUMNS.join(", ");

/* -------------------------------------------------------------------------- */
/* 1. Naive - THE BUG. Included only so the demo can show what it does wrong.  */
/* -------------------------------------------------------------------------- */

/**
 * Picks whatever snapshot_date is newest, complete or not. If the latest
 * collection run wrote a partial snapshot, this returns the partial and every
 * missing entity silently disappears from the result. Do not use in real code.
 */
export function naiveLatestSnapshot(
  db: DatabaseSync,
  table: string = LIVE_TABLE,
): SnapshotRow[] {
  assertIdentifier(table);
  return db
    .prepare(
      `SELECT ${SELECT_COLS} FROM ${table}
       WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM ${table})`,
    )
    .all() as unknown as SnapshotRow[];
}

/* -------------------------------------------------------------------------- */
/* 2. Latest VALID snapshot - completeness gate + COALESCE fallback.           */
/* -------------------------------------------------------------------------- */

export interface LatestValidSnapshotOptions {
  /** Table to read from (a code constant, e.g. `snapshots`). */
  table?: string;
  /** Column whose DISTINCT count defines completeness (e.g. `entity`). */
  completenessColumn: string;
  /** Minimum distinct values required for a snapshot to count as complete. */
  threshold: number;
}

/**
 * Returns the most recent snapshot_date that meets the completeness criterion,
 * i.e. the newest date whose COUNT(DISTINCT completenessColumn) >= threshold.
 * Falls back to the absolute MAX(snapshot_date) when no complete snapshot
 * exists yet, so a brand-new deployment with only partial data still shows
 * *something* rather than nothing. Returns null only when the table is empty.
 */
export function latestValidSnapshotDate(
  db: DatabaseSync,
  opts: LatestValidSnapshotOptions,
): string | null {
  const table = assertIdentifier(opts.table ?? LIVE_TABLE);
  const completenessColumn = assertIdentifier(opts.completenessColumn);
  const row = db
    .prepare(
      `SELECT COALESCE(
         (SELECT snapshot_date FROM ${table}
            GROUP BY snapshot_date
            HAVING COUNT(DISTINCT ${completenessColumn}) >= @threshold
            ORDER BY snapshot_date DESC
            LIMIT 1),
         (SELECT MAX(snapshot_date) FROM ${table})
       ) AS snapshot_date`,
    )
    .get({ threshold: opts.threshold }) as unknown as { snapshot_date: string | null } | undefined;
  return row?.snapshot_date ?? null;
}

/** All rows of the most recent COMPLETE snapshot (see latestValidSnapshotDate). */
export function latestValidSnapshot(
  db: DatabaseSync,
  opts: LatestValidSnapshotOptions,
): SnapshotRow[] {
  const table = assertIdentifier(opts.table ?? LIVE_TABLE);
  const date = latestValidSnapshotDate(db, opts);
  if (date === null) return [];
  return db
    .prepare(`SELECT ${SELECT_COLS} FROM ${table} WHERE snapshot_date = @date`)
    .all({ date }) as unknown as SnapshotRow[];
}

/* -------------------------------------------------------------------------- */
/* 3. Per-entity latest - the strongest no-blank guarantee.                    */
/* -------------------------------------------------------------------------- */

export interface PerEntityLatestOptions {
  /** Table to read from (a code constant, e.g. `snapshots`). */
  table?: string;
  /**
   * Grouping keys identifying a single scrape unit, e.g.
   * ["entity", "series_date"]. For each group the CTE keeps EVERY row from that
   * group's most recent snapshot_date.
   *
   * Why group rather than dedup per row: one collection run can legitimately
   * produce multiple rows for the same group (several sub-series per entity per
   * period). Partitioning by the sub-series too would collapse those rows and
   * silently drop most of them, so the grouping keys deliberately exclude the
   * sub-series dimension.
   */
  groupBy?: string[];
}

/**
 * Returns, for each (groupBy...) tuple, all rows from that tuple's most recent
 * snapshot. This is the strongest guarantee: if entity A last updated on a newer
 * snapshot than entity B, each still shows its own freshest complete data and
 * neither can blank the other. A single entity's bad run only ages that one
 * entity; it never removes it.
 *
 * Implemented as a JOIN of the table against a per-group MAX(snapshot_date),
 * which keeps ALL rows of the winning snapshot for each group.
 */
export function perEntityLatestSnapshot(
  db: DatabaseSync,
  opts: PerEntityLatestOptions = {},
): SnapshotRow[] {
  const table = assertIdentifier(opts.table ?? LIVE_TABLE);
  const groupBy = (opts.groupBy ?? ["entity", "series_date"]).map(assertIdentifier);
  const groupExpr = groupBy.join(", ");
  const joinKeys = groupBy.map((k) => `k.${k} = t.${k}`).join(" AND ");
  return db
    .prepare(
      `WITH keys AS (
         SELECT ${groupExpr}, MAX(snapshot_date) AS latest_snap
         FROM ${table}
         GROUP BY ${groupExpr}
       )
       SELECT t.* FROM ${table} t
       JOIN keys k
         ON ${joinKeys}
        AND k.latest_snap = t.snapshot_date`,
    )
    .all() as unknown as SnapshotRow[];
}
