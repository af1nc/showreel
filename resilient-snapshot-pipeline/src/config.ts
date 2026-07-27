/**
 * Domain configuration for the demo.
 *
 * Everything here is deliberately generic. In the real system this was a set of
 * geographic markets, each tracking a handful of competitor brands over a weekly
 * time axis. Here it is simply:
 *
 *   entity     - the independently-completing unit of work. If the external API
 *                serves this entity's data we can persist it; if it rate-limits
 *                us, this one entity is missing but the others are unaffected.
 *   series     - a sub-dimension measured within each entity (several rows per
 *                entity per period).
 *   seriesDate - the data's own time axis (e.g. a weekly period). This is
 *                distinct from `snapshot_date`, which is the *collection*
 *                version/date.
 */

export interface EntityDef {
  /** Stable identifier used in the completeness gate and joins. */
  code: string;
  /** Human-readable label carried through for display. */
  label: string;
}

/**
 * REQUIRED entities gate completeness. A snapshot is only promoted to the live
 * table once every one of these has been collected. This mirrors the real
 * system's "core markets" tier: the minimum bar below which a snapshot is
 * considered unusable and must not reach the dashboard.
 */
export const REQUIRED_ENTITIES: EntityDef[] = [
  { code: "alpha", label: "Region Alpha" },
  { code: "bravo", label: "Region Bravo" },
  { code: "charlie", label: "Region Charlie" },
  { code: "delta", label: "Region Delta" },
  { code: "echo", label: "Region Echo" },
  { code: "foxtrot", label: "Region Foxtrot" },
];

/**
 * OPTIONAL entities are collected opportunistically. Their absence never blocks
 * a promotion. Whatever we manage to fetch rides along in the same snapshot.
 */
export const OPTIONAL_ENTITIES: EntityDef[] = [
  { code: "golf", label: "Region Golf" },
  { code: "hotel", label: "Region Hotel" },
];

export const ALL_ENTITIES: EntityDef[] = [...REQUIRED_ENTITIES, ...OPTIONAL_ENTITIES];

/** Sub-dimensions measured within every entity. */
export const SERIES = ["series-a", "series-b", "series-c"] as const;

/** The data's own weekly time axis (fixed so the demo is fully deterministic). */
export const SERIES_DATES = ["2024-01-01", "2024-01-08", "2024-01-15"] as const;

/**
 * Completeness threshold used by the consumer-side read gate: a snapshot must
 * contain at least this many DISTINCT entities to be considered "complete".
 * Kept as a count (not a set membership test) to mirror the production SQL,
 * where the HAVING clause counted distinct codes.
 */
export const COMPLETENESS_THRESHOLD = REQUIRED_ENTITIES.length;

/** Staging rows for snapshot dates older than this are garbage-collected. */
export const STAGING_RETENTION_DAYS = 14;
