/**
 * A synthetic stand-in for the real, rate-limited external API.
 *
 * The real source was an unofficial, quota-limited public endpoint that would
 * intermittently refuse requests (HTTP 429 / CAPTCHA / empty HTML) for a subset
 * of entities on any given run. This stub reproduces exactly that failure mode,
 * but *deterministically* (no wall-clock randomness) so the demo's "resume and
 * complete over several runs" behaviour is reproducible byte-for-byte.
 *
 * Contract:
 *   - fetch(entity, snapshotDate, runIndex) returns the entity's full set of
 *     rows when the source is willing to serve it, or [] when it "rate-limits"
 *     that entity on that run.
 *   - Which entities are refused is a pure function of (entity, runIndex, seed),
 *     so the same scenario always produces the same story.
 */

import { SERIES, SERIES_DATES } from "./config";
import type { EntityDef } from "./config";
import type { SnapshotRow } from "./db";

export interface ExternalSource {
  fetch(entity: EntityDef, snapshotDate: string, runIndex: number): SnapshotRow[];
}

export interface FlakySourceOptions {
  /** Namespaces the deterministic hash so different scenarios differ. */
  seed: string;
  /**
   * 0..100. Higher means more entities are rate-limited on any given run.
   * Applies only before `recoveryRun`.
   */
  rateLimitedPercent: number;
  /**
   * 1-based run index at (and after) which the source stops rate-limiting and
   * serves every entity. Models a quota window that eventually clears. Omit to
   * keep the source flaky indefinitely.
   */
  recoveryRun?: number;
}

/** Small, fast, deterministic 32-bit hash (FNV-1a). No crypto, no randomness. */
function fnv1a(str: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** Deterministic value in [0, 100) for a single measurement. */
function syntheticValue(entity: string, series: string, seriesDate: string): number {
  const h = fnv1a(`${entity}|${series}|${seriesDate}`);
  return Math.round((h % 10000) / 100); // 0.00 .. 99.99
}

export function createFlakySource(opts: FlakySourceOptions): ExternalSource {
  const { seed, rateLimitedPercent, recoveryRun } = opts;

  function isRateLimited(entity: EntityDef, runIndex: number): boolean {
    // Once the quota window clears, everything is served.
    if (recoveryRun !== undefined && runIndex >= recoveryRun) return false;
    // Otherwise a deterministic subset is refused on this run. Because the hash
    // folds in runIndex, the refused set *changes* run to run - i.e. the source
    // is genuinely flaky, not monotonic. Persistence in staging is what makes
    // that survivable.
    const bucket = fnv1a(`${seed}|${entity.code}|${runIndex}`) % 100;
    return bucket < rateLimitedPercent;
  }

  return {
    fetch(entity, snapshotDate, runIndex) {
      if (isRateLimited(entity, runIndex)) {
        return []; // the API refused this entity on this run
      }
      const rows: SnapshotRow[] = [];
      for (const seriesDate of SERIES_DATES) {
        for (const series of SERIES) {
          rows.push({
            snapshot_date: snapshotDate,
            series_date: seriesDate,
            entity: entity.code,
            series,
            label: entity.label,
            value: syntheticValue(entity.code, series, seriesDate),
          });
        }
      }
      return rows;
    },
  };
}
