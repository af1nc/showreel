/**
 * Generic stale-while-revalidate (SWR) cache with single-flight refresh.
 *
 * The pattern comes from materializing an expensive computation: the real work
 * (in the original system, a ~45-second analytical query) is far too slow to run
 * on every read. So we cache the result and serve it instantly, and only when
 * the cached value is older than a TTL do we recompute - in the BACKGROUND, so
 * readers never block on the slow path.
 *
 * Guarantees:
 *   - `get()` returns the cached value immediately when one exists, even if it
 *     is stale (that is the "stale-while-revalidate" contract).
 *   - When the value is stale, `get()` kicks off at most ONE background refresh.
 *     This is the "single-flight" guarantee: concurrent callers that all see a
 *     stale cache share the same in-flight recompute instead of each starting
 *     their own.
 *   - Only the very first call (cold cache, nothing to serve) awaits the
 *     computation. Every subsequent call returns synchronously-available data.
 *   - A failed background refresh never rejects a reader; the last good value
 *     keeps being served and the next `get()` will retry.
 *
 * This is deliberately storage-agnostic: the "materialized result" is just an
 * in-process value here. Swap `compute` for anything (a DB write + read-back, a
 * file, a remote cache) without changing the concurrency logic.
 */

export interface StaleWhileRevalidateOptions<T> {
  /** The expensive computation to cache. Called at most once at a time. */
  compute: () => Promise<T>;
  /** How long a cached value is considered fresh, in milliseconds. */
  ttlMs: number;
  /** Injectable clock (ms). Defaults to `Date.now`. Handy for tests. */
  now?: () => number;
  /** Optional hook fired when a background refresh settles. Never throws. */
  onRefresh?: (result: { ok: boolean; durationMs: number; error?: unknown }) => void;
}

interface CacheEntry<T> {
  value: T;
  storedAt: number;
}

export class StaleWhileRevalidate<T> {
  private readonly compute: () => Promise<T>;
  private readonly ttlMs: number;
  private readonly now: () => number;
  private readonly onRefresh?: StaleWhileRevalidateOptions<T>["onRefresh"];

  private cache: CacheEntry<T> | null = null;
  /** The single in-flight refresh, or null when none is running. */
  private inFlight: Promise<T> | null = null;

  constructor(opts: StaleWhileRevalidateOptions<T>) {
    if (opts.ttlMs < 0) throw new RangeError("ttlMs must be >= 0");
    this.compute = opts.compute;
    this.ttlMs = opts.ttlMs;
    this.now = opts.now ?? Date.now;
    this.onRefresh = opts.onRefresh;
  }

  /** True when there is no cached value, or the cached value is past its TTL. */
  isStale(): boolean {
    if (!this.cache) return true;
    return this.now() - this.cache.storedAt >= this.ttlMs;
  }

  /** True when a background refresh is currently running. */
  isRefreshing(): boolean {
    return this.inFlight !== null;
  }

  /** The current cached value without triggering a refresh (undefined if cold). */
  peek(): T | undefined {
    return this.cache?.value;
  }

  /**
   * Return the cached value.
   *
   * - Cache present & fresh  -> return it immediately, do nothing.
   * - Cache present & stale  -> return it immediately AND trigger (or join) a
   *                             single background refresh. The caller does not
   *                             wait for the refresh.
   * - Cache absent (cold)    -> await the computation; there is nothing to serve.
   */
  async get(): Promise<T> {
    if (this.cache) {
      if (this.isStale()) {
        // Fire-and-forget. Swallow errors so a failed refresh never surfaces to
        // a reader - the stale value is still perfectly serviceable.
        void this.refresh().catch(() => {});
      }
      return this.cache.value;
    }
    // Cold start: nothing to serve yet, so this one caller must block.
    return this.refresh();
  }

  /**
   * Start a refresh, or return the already-running one (single-flight).
   * On success the cache is replaced. Returns the value produced.
   */
  private refresh(): Promise<T> {
    if (this.inFlight) return this.inFlight; // join the existing recompute

    const startedAt = this.now();
    const run = this.compute().then((value) => {
      this.cache = { value, storedAt: this.now() };
      return value;
    });

    this.inFlight = run;

    // Bookkeeping chain, kept separate so its own settling never produces an
    // unhandled rejection and never blocks the returned promise.
    run.then(
      () => {
        this.safeNotify({ ok: true, durationMs: this.now() - startedAt });
      },
      (error) => {
        this.safeNotify({ ok: false, durationMs: this.now() - startedAt, error });
      },
    ).finally(() => {
      if (this.inFlight === run) this.inFlight = null;
    });

    return run;
  }

  /** Force an awaited rebuild (joins an in-flight one) - for manual/scheduled refresh. */
  async forceRefresh(): Promise<T> {
    return this.refresh();
  }

  private safeNotify(result: { ok: boolean; durationMs: number; error?: unknown }): void {
    if (!this.onRefresh) return;
    try {
      this.onRefresh(result);
    } catch {
      // A misbehaving hook must never break the cache.
    }
  }
}
