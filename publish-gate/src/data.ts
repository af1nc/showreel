/**
 * Synthetic dataset for the Market Activity Digest.
 *
 * Everything here is generated from a fixed seed, so every run of the demo and
 * of the tests sees identical data. There is no network access and no external
 * file to load.
 *
 * The domain is deliberately mundane: competing brands of home and kitchen
 * goods putting new product listings live in six markets.
 */

export type Brand = 'Aurora' | 'Beacon' | 'Cirrus' | 'Dalton' | 'Everline';
export type Market = 'Portugal' | 'Chile' | 'Vietnam' | 'Norway' | 'Morocco' | 'Finland';

export const BRANDS: readonly Brand[] = ['Aurora', 'Beacon', 'Cirrus', 'Dalton', 'Everline'];
export const MARKETS: readonly Market[] = [
  'Portugal',
  'Chile',
  'Vietnam',
  'Norway',
  'Morocco',
  'Finland',
];

/**
 * One row of the collected dataset.
 *
 * A single `listing_id` can appear on several rows, once per market it went
 * live in. That is the whole reason the distinct count and the summed group
 * count disagree, and it is the trap that checks.ts is built around.
 */
export interface Listing {
  listing_id: string;
  brand: Brand;
  market: Market;
  /** The day the listing actually went live. */
  launch_date: string;
  /** The day our collection run first saw it. Always on or after launch_date. */
  collected_date: string;
  title: string;
}

/** A digest window, inclusive at both ends. */
export interface Window {
  id: string;
  start: string;
  end: string;
}

/**
 * Held behind an object rather than passed as a bare array so that the demo can
 * hand the gate a deliberately broken dataset (a property that throws) and show
 * the fail-open path without needing a second implementation of anything.
 */
export interface Dataset {
  readonly listings: readonly Listing[];
}

const DAY_MS = 86_400_000;

export function fromISO(iso: string): number {
  return Date.parse(iso + 'T00:00:00Z');
}

export function toISO(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

export function addDays(iso: string, days: number): string {
  return toISO(fromISO(iso) + days * DAY_MS);
}

/** Small deterministic PRNG (mulberry32). No wall clock, no crypto. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return function next(): number {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function intBetween(rnd: () => number, min: number, max: number): number {
  return min + Math.floor(rnd() * (max - min + 1));
}

/** Twelve consecutive weekly windows. */
export const WEEKS: readonly Window[] = Array.from({ length: 12 }, (_unused, i) => {
  const start = addDays('2031-01-06', i * 7);
  return { id: 'W' + String(i + 1).padStart(2, '0'), start, end: addDays(start, 6) };
});

/** Week 12 is a genuinely thin week, so the quiet-week check has something honest to pass. */
const QUIET_WEEK_INDEX = 11;
const QUIET_WEEK_COUNTS: Record<Brand, number> = {
  Aurora: 1,
  Beacon: 0,
  Cirrus: 0,
  Dalton: 1,
  Everline: 1,
};

/**
 * Week 9 is a catalogue sweep for Cirrus, built to exact figures so the
 * distinct-versus-group-sum demonstration is reproducible:
 *   distinct listing_id             = 478
 *   summed over brand+market groups = 860
 */
export const SWEEP_WEEK_INDEX = 8;
export const SWEEP_BRAND: Brand = 'Cirrus';
export const SWEEP_DISTINCT = 478;
export const SWEEP_PLACEMENTS = 860;

const WORD_A = [
  'Harbour',
  'Meadow',
  'Copper',
  'Northfield',
  'Lantern',
  'Willow',
  'Granite',
  'Saffron',
  'Pebble',
  'Juniper',
];
const WORD_B = [
  'Kettle',
  'Tumbler',
  'Skillet',
  'Carafe',
  'Storage Tin',
  'Chopping Board',
  'Mixing Bowl',
  'Teapot',
  'Cutlery Set',
  'Colander',
];
const WORD_C = ['Small', 'Midi', 'Large', 'Family', 'Compact', 'Twin Pack'];

function makeTitle(rnd: () => number): string {
  const a = WORD_A[intBetween(rnd, 0, WORD_A.length - 1)];
  const b = WORD_B[intBetween(rnd, 0, WORD_B.length - 1)];
  const c = WORD_C[intBetween(rnd, 0, WORD_C.length - 1)];
  return a + ' ' + b + ', ' + c;
}

/**
 * Not every brand sells everywhere. Two brands are simply absent from a market
 * for the whole period, which is what gives the named-market check something
 * real to catch.
 */
const MARKET_EXCLUSIONS: Partial<Record<Brand, readonly Market[]>> = {
  Beacon: ['Morocco'],
  Dalton: ['Norway'],
};

function pickMarkets(rnd: () => number, howMany: number, brand: Brand): Market[] {
  const blocked = MARKET_EXCLUSIONS[brand] ?? [];
  const pool = MARKETS.filter((m) => !blocked.includes(m));
  const out: Market[] = [];
  for (let i = 0; i < howMany && pool.length > 0; i++) {
    out.push(pool.splice(intBetween(rnd, 0, pool.length - 1), 1)[0]!);
  }
  return out;
}

/**
 * Collection lag. Roughly three rows in five are seen within two days, the rest
 * turn up a week or more later. This is what makes recomputed totals climb
 * after an edition has already been published, and therefore what forces the
 * tolerance in checks.ts to be asymmetric.
 */
function collectionLag(rnd: () => number): number {
  return rnd() < 0.6 ? intBetween(rnd, 0, 2) : intBetween(rnd, 8, 20);
}

export function inWindow(date: string, window: Window): boolean {
  return date >= window.start && date <= window.end;
}

function buildSweep(startId: number, week: Window): Listing[] {
  const rnd = mulberry32(99_173);
  const rows: Listing[] = [];
  // 382 listings live in two markets, 96 live in one: 382*2 + 96 = 860 rows.
  const twoMarketCount = SWEEP_PLACEMENTS - SWEEP_DISTINCT;
  for (let i = 0; i < SWEEP_DISTINCT; i++) {
    const id = 'LST-' + String(startId + i).padStart(6, '0');
    const launch = addDays(week.start, intBetween(rnd, 0, 6));
    const title = makeTitle(rnd);
    const markets = pickMarkets(rnd, i < twoMarketCount ? 2 : 1, SWEEP_BRAND);
    for (const market of markets) {
      rows.push({
        listing_id: id,
        brand: SWEEP_BRAND,
        market,
        launch_date: launch,
        collected_date: addDays(launch, collectionLag(rnd)),
        title,
      });
    }
  }
  return rows;
}

export function buildDataset(seed = 20_310_106): Dataset {
  const rnd = mulberry32(seed);
  const listings: Listing[] = [];
  let counter = 1;

  for (let w = 0; w < WEEKS.length; w++) {
    const week = WEEKS[w]!;
    for (const brand of BRANDS) {
      if (w === SWEEP_WEEK_INDEX && brand === SWEEP_BRAND) {
        listings.push(...buildSweep(counter, week));
        counter += SWEEP_DISTINCT;
        continue;
      }
      const distinctCount =
        w === QUIET_WEEK_INDEX ? QUIET_WEEK_COUNTS[brand] : intBetween(rnd, 12, 30);

      for (let i = 0; i < distinctCount; i++) {
        const id = 'LST-' + String(counter++).padStart(6, '0');
        const launch = addDays(week.start, intBetween(rnd, 0, 6));
        const title = makeTitle(rnd);
        const roll = rnd();
        const howManyMarkets = roll < 0.7 ? 1 : roll < 0.92 ? 2 : 3;
        for (const market of pickMarkets(rnd, howManyMarkets, brand)) {
          listings.push({
            listing_id: id,
            brand,
            market,
            launch_date: launch,
            collected_date: addDays(launch, collectionLag(rnd)),
            title,
          });
        }
      }
    }
  }

  listings.sort((a, b) =>
    a.listing_id === b.listing_id
      ? a.market.localeCompare(b.market)
      : a.listing_id.localeCompare(b.listing_id),
  );
  return { listings };
}

export const DATASET: Dataset = buildDataset();

export function listingsInWindow(dataset: Dataset, window: Window): Listing[] {
  return dataset.listings.filter((r) => inWindow(r.launch_date, window));
}

/**
 * The dataset as it stood on a given collection date. Used to show that an
 * edition published weeks ago quoted a figure that was correct at the time and
 * is lower than today's recomputed total.
 */
export function asOfCollected(dataset: Dataset, isoDate: string): Dataset {
  return { listings: dataset.listings.filter((r) => r.collected_date <= isoDate) };
}

/**
 * COUNT(DISTINCT listing_id) for one brand across every market, which is the
 * altitude the copy actually writes at. This is the figure a brand-wide
 * sentence should be judged against.
 */
export function brandWindowDistinct(dataset: Dataset, brand: Brand, window: Window): number {
  const ids = new Set<string>();
  for (const r of dataset.listings) {
    if (r.brand === brand && inWindow(r.launch_date, window)) ids.add(r.listing_id);
  }
  return ids.size;
}

/**
 * The same thing counted the naive way: distinct listings per brand+market
 * group, then summed. Any listing live in several markets is counted once per
 * market, so this figure is always greater than or equal to the distinct one.
 * It is a real figure with a real meaning (market-level placements), it is just
 * not the figure a brand-wide sentence is making a claim about.
 */
export function brandWindowPlacements(dataset: Dataset, brand: Brand, window: Window): number {
  const groups = new Map<string, Set<string>>();
  for (const r of dataset.listings) {
    if (r.brand !== brand || !inWindow(r.launch_date, window)) continue;
    const key = r.brand + '|' + r.market;
    let bucket = groups.get(key);
    if (!bucket) {
      bucket = new Set<string>();
      groups.set(key, bucket);
    }
    bucket.add(r.listing_id);
  }
  let total = 0;
  for (const bucket of groups.values()) total += bucket.size;
  return total;
}

export function brandMarketDistinct(
  dataset: Dataset,
  brand: Brand,
  market: Market,
  window: Window,
): number {
  const ids = new Set<string>();
  for (const r of dataset.listings) {
    if (r.brand === brand && r.market === market && inWindow(r.launch_date, window)) {
      ids.add(r.listing_id);
    }
  }
  return ids.size;
}

/** Distinct listings launched in the window, all brands. */
export function windowLaunchCount(dataset: Dataset, window: Window): number {
  const ids = new Set<string>();
  for (const r of dataset.listings) {
    if (inWindow(r.launch_date, window)) ids.add(r.listing_id);
  }
  return ids.size;
}

export function marketsForBrand(dataset: Dataset, brand: Brand, window: Window): Market[] {
  const seen = new Set<Market>();
  for (const r of dataset.listings) {
    if (r.brand === brand && inWindow(r.launch_date, window)) seen.add(r.market);
  }
  return MARKETS.filter((m) => seen.has(m));
}

export function rowsForListing(dataset: Dataset, listingId: string): Listing[] {
  return dataset.listings.filter((r) => r.listing_id === listingId);
}

export function sampleListingIds(
  dataset: Dataset,
  brand: Brand,
  window: Window,
  howMany: number,
): string[] {
  const ids: string[] = [];
  for (const r of dataset.listings) {
    if (r.brand === brand && inWindow(r.launch_date, window) && !ids.includes(r.listing_id)) {
      ids.push(r.listing_id);
      if (ids.length === howMany) break;
    }
  }
  return ids;
}

// Self-check: the headline demonstration figures must hold, or the demo lies.
{
  const sweepWeek = WEEKS[SWEEP_WEEK_INDEX]!;
  const rows = DATASET.listings.filter(
    (r) => r.brand === SWEEP_BRAND && inWindow(r.launch_date, sweepWeek),
  );
  const distinct = new Set(rows.map((r) => r.listing_id)).size;
  if (distinct !== SWEEP_DISTINCT || rows.length !== SWEEP_PLACEMENTS) {
    throw new Error(
      'dataset self-check failed: expected ' +
        SWEEP_DISTINCT +
        '/' +
        SWEEP_PLACEMENTS +
        ', got ' +
        distinct +
        '/' +
        rows.length,
    );
  }
}
