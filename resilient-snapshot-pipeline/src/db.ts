/**
 * Local store.
 *
 * In production this was a cloud data warehouse with server-side transactions.
 * Here it is a single SQLite database (in-memory by default) so the demo runs
 * with no cloud, no credentials, and no network. SQLite is used specifically
 * because it gives us *real* atomic transactions (BEGIN / COMMIT / ROLLBACK),
 * which is the whole point of the "atomic promote" the producer relies on.
 *
 * Two tables, identical shape:
 *   snapshots           - the LIVE table every reader queries. Must never
 *                         contain a partial snapshot.
 *   snapshots_staging   - the producer's scratch space. Partial progress
 *                         accumulates here across runs and is only ever
 *                         promoted to `snapshots` as a complete unit.
 */

import { DatabaseSync } from "node:sqlite";

export const LIVE_TABLE = "snapshots";
export const STAGING_TABLE = "snapshots_staging";

/**
 * One measured value.
 *   snapshot_date - the collection version. All rows written by one logical
 *                   "day" of collection share a snapshot_date. This is what the
 *                   completeness gate and the atomic promote key on.
 *   series_date   - the data's own time axis (a weekly period here).
 *   entity        - the independently-completing unit.
 *   series        - a sub-dimension within the entity.
 *   label         - human label for the entity.
 *   value         - the measurement.
 */
export interface SnapshotRow {
  snapshot_date: string;
  series_date: string;
  entity: string;
  series: string;
  label: string;
  value: number;
}

export const SNAPSHOT_COLUMNS = [
  "snapshot_date",
  "series_date",
  "entity",
  "series",
  "label",
  "value",
] as const;

/** Identifiers passed to query builders come from code constants, never user
 * input. We still validate them so the builders can never be a SQL-injection
 * vector even if a caller wires them up carelessly. */
const IDENTIFIER_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

export function assertIdentifier(name: string): string {
  if (!IDENTIFIER_RE.test(name)) {
    throw new Error(`Refusing unsafe SQL identifier: ${JSON.stringify(name)}`);
  }
  return name;
}

function createTable(db: DatabaseSync, name: string): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS ${assertIdentifier(name)} (
      snapshot_date TEXT NOT NULL,
      series_date   TEXT NOT NULL,
      entity        TEXT NOT NULL,
      series        TEXT NOT NULL,
      label         TEXT NOT NULL,
      value         REAL NOT NULL
    );
  `);
  db.exec(
    `CREATE INDEX IF NOT EXISTS idx_${name}_snap ON ${name} (snapshot_date);`,
  );
  db.exec(
    `CREATE INDEX IF NOT EXISTS idx_${name}_entity ON ${name} (entity, series_date);`,
  );
}

export function openDb(path = ":memory:"): DatabaseSync {
  const db = new DatabaseSync(path);
  createTable(db, LIVE_TABLE);
  createTable(db, STAGING_TABLE);
  return db;
}

/** Insert helper shared by the producer and by fault-injection in the demo.
 * Wrapped in a manual transaction so a batch either lands whole or not at all. */
export function insertRows(
  db: DatabaseSync,
  table: string,
  rows: SnapshotRow[],
): void {
  if (rows.length === 0) return;
  const cols = SNAPSHOT_COLUMNS.join(", ");
  const placeholders = SNAPSHOT_COLUMNS.map((c) => `@${c}`).join(", ");
  const stmt = db.prepare(
    `INSERT INTO ${assertIdentifier(table)} (${cols}) VALUES (${placeholders})`,
  );
  db.exec("BEGIN");
  try {
    for (const row of rows) {
      stmt.run(row as unknown as Record<string, string | number>);
    }
    db.exec("COMMIT");
  } catch (err) {
    db.exec("ROLLBACK");
    throw err;
  }
}
