/**
 * The two corpora the proofs run against.
 *
 * GOOD_EDITIONS are known-good historical editions. The gate must not block a
 * single one of them.
 *
 * INCIDENT_EDITIONS are reconstructions of real failure shapes, one per check.
 * The gate must catch every one of them.
 *
 * Both corpora derive their numbers from the dataset at load time rather than
 * hard-coding them, so the fixtures cannot drift away from the data they are
 * meant to describe. The incident editions then distort those numbers on
 * purpose, in the specific way the original failures did.
 */

import {
  BRANDS,
  DATASET,
  MARKETS,
  SWEEP_BRAND,
  SWEEP_PLACEMENTS,
  SWEEP_WEEK_INDEX,
  WEEKS,
  addDays,
  asOfCollected,
  brandMarketDistinct,
  brandWindowDistinct,
  marketsForBrand,
  sampleListingIds,
  type Brand,
  type Market,
  type Window,
} from './data.js';
import type { CheckId, Severity } from './checks.js';
import type { ValidatableEdition } from './gate.js';

export interface Edition extends ValidatableEdition {
  id: string;
  window: Window;
  publishedAt: string;
  copy: string;
  citedListingIds: readonly string[];
  /**
   * The numbers the generator reported alongside its copy. Kept only so the
   * demo can show them being ignored: the gate recomputes everything and never
   * reads this field.
   */
  generatorNumbers: Readonly<Record<string, number>>;
  note: string;
}

function header(window: Window): string {
  return 'Market Activity Digest, ' + window.id + ' (' + window.start + ' to ' + window.end + ').';
}

function twoMarkets(brand: Brand, window: Window): [Market, Market] {
  const markets = marketsForBrand(DATASET, brand, window);
  const first = markets[0] ?? MARKETS[0]!;
  const second = markets[1] ?? first;
  return [first, second];
}

interface GoodEditionSpec {
  id: string;
  weekIndex: number;
  brand: Brand;
  secondBrand: Brand;
}

function goodEdition(spec: GoodEditionSpec): Edition {
  const window = WEEKS[spec.weekIndex]!;
  const count = brandWindowDistinct(DATASET, spec.brand, window);
  const [m1, m2] = twoMarkets(spec.brand, window);
  const [m3] = twoMarkets(spec.secondBrand, window);
  const cited = sampleListingIds(DATASET, spec.brand, window, 3);

  const copy = [
    header(window),
    spec.brand + ' added ' + count + ' new listings across markets including ' + m1 + ' and ' + m2 + '.',
    spec.secondBrand + ' stayed active in ' + m3 + '.',
    'Pack sizes across the category keep drifting smaller, which buyers appear to reward.',
  ].join(' ');

  return {
    id: spec.id,
    window,
    publishedAt: addDays(window.end, 1),
    copy,
    citedListingIds: cited,
    generatorNumbers: { claimed_count: count },
    note: 'Ordinary edition, figures correct as written.',
  };
}

/**
 * The archive case that matters most. This edition was written three days after
 * its window closed, using the data collected by then. More rows have arrived
 * since, so the figure recomputed today is higher than the figure in the copy.
 * The edition is not wrong and must not be blocked.
 */
function underStatedEdition(): Edition {
  const window = WEEKS[3]!;
  const brand: Brand = 'Everline';
  const cutoff = addDays(window.end, 3);
  const asThen = brandWindowDistinct(asOfCollected(DATASET, cutoff), brand, window);
  const [m1, m2] = twoMarkets(brand, window);

  const copy = [
    header(window),
    brand + ' added ' + asThen + ' new listings across markets including ' + m1 + ' and ' + m2 + '.',
    'Rivals held steady.',
  ].join(' ');

  return {
    id: 'GOOD-UNDERSTATED',
    window,
    publishedAt: cutoff,
    copy,
    citedListingIds: sampleListingIds(asOfCollected(DATASET, cutoff), brand, window, 2),
    generatorNumbers: { claimed_count: asThen },
    note:
      'Published on ' +
      cutoff +
      ' quoting ' +
      asThen +
      ', which was correct then. Today the same window recomputes to ' +
      brandWindowDistinct(DATASET, brand, window) +
      '. Under-claiming must never block.',
  };
}

/** A genuinely thin week, so the quiet-week check has an honest pass to make. */
function quietWeekEdition(): Edition {
  const window = WEEKS[11]!;
  const copy = [
    header(window),
    'A quiet week: nothing new launched from most brands.',
    'Aurora was one of the few names to move at all.',
  ].join(' ');
  return {
    id: 'GOOD-QUIET',
    window,
    publishedAt: addDays(window.end, 1),
    copy,
    citedListingIds: [],
    generatorNumbers: {},
    note: 'The week really was quiet, so the quiet-week check has to let it through.',
  };
}

/**
 * The legitimate use of the placement figure. The copy says "listing
 * placements", so the gate judges it against the summed brand+market total and
 * it passes. Contrast with INCIDENT-PLACEMENTS below, which quotes the same
 * number as if it were a count of listings.
 */
function placementsEdition(): Edition {
  const window = WEEKS[SWEEP_WEEK_INDEX]!;
  const [m1, m2] = twoMarkets(SWEEP_BRAND, window);
  const copy = [
    header(window),
    SWEEP_BRAND +
      ' recorded ' +
      SWEEP_PLACEMENTS +
      ' new listing placements across markets including ' +
      m1 +
      ' and ' +
      m2 +
      '.',
    'That is a catalogue sweep rather than a run of separate launches.',
  ].join(' ');
  return {
    id: 'GOOD-PLACEMENTS',
    window,
    publishedAt: addDays(window.end, 1),
    copy,
    citedListingIds: [],
    generatorNumbers: { claimed_placements: SWEEP_PLACEMENTS },
    note: 'Quotes the market-level figure and says so, so the gate judges it against that figure.',
  };
}

export const GOOD_EDITIONS: readonly Edition[] = [
  goodEdition({ id: 'GOOD-01', weekIndex: 0, brand: 'Aurora', secondBrand: 'Beacon' }),
  goodEdition({ id: 'GOOD-02', weekIndex: 1, brand: 'Beacon', secondBrand: 'Cirrus' }),
  goodEdition({ id: 'GOOD-03', weekIndex: 2, brand: 'Cirrus', secondBrand: 'Dalton' }),
  goodEdition({ id: 'GOOD-04', weekIndex: 4, brand: 'Dalton', secondBrand: 'Everline' }),
  goodEdition({ id: 'GOOD-05', weekIndex: 5, brand: 'Everline', secondBrand: 'Aurora' }),
  goodEdition({ id: 'GOOD-06', weekIndex: 6, brand: 'Aurora', secondBrand: 'Cirrus' }),
  goodEdition({ id: 'GOOD-07', weekIndex: 7, brand: 'Beacon', secondBrand: 'Dalton' }),
  goodEdition({ id: 'GOOD-08', weekIndex: 9, brand: 'Dalton', secondBrand: 'Beacon' }),
  goodEdition({ id: 'GOOD-09', weekIndex: 10, brand: 'Everline', secondBrand: 'Cirrus' }),
  underStatedEdition(),
  quietWeekEdition(),
  placementsEdition(),
];

/** Incident 1: told readers a normal week had been uneventful. */
function incidentQuiet(): Edition {
  const window = WEEKS[5]!;
  const copy = [
    header(window),
    'A quiet week: no new listings were recorded across the category.',
    'The category settles back into its usual rhythm.',
  ].join(' ');
  return {
    id: 'INCIDENT-QUIET',
    window,
    publishedAt: addDays(window.end, 1),
    copy,
    citedListingIds: [],
    generatorNumbers: { claimed_count: 0 },
    note: 'Asserts a quiet week over a window with a full run of launches.',
  };
}

/** Incident 2: a count inflated well beyond anything the data supports. */
function incidentCount(): Edition {
  const window = WEEKS[4]!;
  const brand: Brand = 'Beacon';
  const truth = brandWindowDistinct(DATASET, brand, window);
  const inflated = truth * 2 + 20;
  const [m1, m2] = twoMarkets(brand, window);
  const copy = [
    header(window),
    brand + ' added ' + inflated + ' new listings across markets including ' + m1 + ' and ' + m2 + '.',
    'It was the busiest name of the week by some distance.',
  ].join(' ');
  return {
    id: 'INCIDENT-COUNT',
    window,
    publishedAt: addDays(window.end, 1),
    copy,
    citedListingIds: [],
    generatorNumbers: { claimed_count: inflated },
    note: 'Claims ' + inflated + ' against a recomputed ' + truth + '.',
  };
}

/** Incident 3: illustrated the week with items that launched elsewhere in time. */
function incidentWindow(): Edition {
  const window = WEEKS[6]!;
  const brand: Brand = 'Aurora';
  const truth = brandWindowDistinct(DATASET, brand, window);
  const inWindowId = sampleListingIds(DATASET, brand, window, 1)[0]!;
  const staleId = sampleListingIds(DATASET, brand, WEEKS[1]!, 1)[0]!;
  const copy = [
    header(window),
    brand + ' added ' + truth + ' new listings in the window.',
    'Three of them are worth calling out.',
  ].join(' ');
  return {
    id: 'INCIDENT-WINDOW',
    window,
    publishedAt: addDays(window.end, 1),
    copy,
    citedListingIds: [inWindowId, staleId, 'LST-999999'],
    generatorNumbers: { claimed_count: truth },
    note: 'One cited item launched five weeks earlier and one does not exist.',
  };
}

/** Find a brand, week and market combination with genuinely no activity. */
function findEmptyPair(): { weekIndex: number; brand: Brand; market: Market } {
  for (let w = 0; w < 11; w++) {
    for (const brand of BRANDS) {
      for (const market of MARKETS) {
        if (brandMarketDistinct(DATASET, brand, market, WEEKS[w]!) === 0) {
          return { weekIndex: w, brand, market };
        }
      }
    }
  }
  throw new Error('no empty brand/market pair in the dataset: the warning case cannot be built');
}

/** Incident 4: named a market for a brand that had nothing there. Warning tier. */
function incidentNamedMarket(): Edition {
  const empty = findEmptyPair();
  const window = WEEKS[empty.weekIndex]!;
  const truth = brandWindowDistinct(DATASET, empty.brand, window);
  const realMarket = marketsForBrand(DATASET, empty.brand, window)[0]!;
  const copy = [
    header(window),
    empty.brand +
      ' added ' +
      truth +
      ' new listings across markets including ' +
      empty.market +
      ' and ' +
      realMarket +
      '.',
    'Its range is widening steadily.',
  ].join(' ');
  return {
    id: 'INCIDENT-MARKET',
    window,
    publishedAt: addDays(window.end, 1),
    copy,
    citedListingIds: [],
    generatorNumbers: { claimed_count: truth },
    note:
      'The count is right. ' +
      empty.market +
      ' is named for ' +
      empty.brand +
      ' with nothing behind it, which is a warning and not a block.',
  };
}

/**
 * Incident 5: the count that made this project necessary. The generator was fed
 * a figure summed across brand+market groups and wrote it as a count of
 * listings, turning a real 478 into a published 860.
 */
function incidentPlacements(): Edition {
  const window = WEEKS[SWEEP_WEEK_INDEX]!;
  const [m1, m2] = twoMarkets(SWEEP_BRAND, window);
  const copy = [
    header(window),
    SWEEP_BRAND +
      ' added ' +
      SWEEP_PLACEMENTS +
      ' new listings across markets including ' +
      m1 +
      ' and ' +
      m2 +
      '.',
    'No other name came close.',
  ].join(' ');
  return {
    id: 'INCIDENT-PLACEMENTS',
    window,
    publishedAt: addDays(window.end, 1),
    copy,
    citedListingIds: [],
    generatorNumbers: { claimed_count: SWEEP_PLACEMENTS },
    note: 'The summed market-level figure published as a count of listings.',
  };
}

export const INCIDENT_EDITIONS: readonly Edition[] = [
  incidentQuiet(),
  incidentCount(),
  incidentWindow(),
  incidentNamedMarket(),
  incidentPlacements(),
];

export interface IncidentExpectation {
  editionId: string;
  check: CheckId;
  severity: Severity;
  label: string;
}

/** What each incident must produce. The negative control asserts exactly this. */
export const INCIDENT_EXPECTATIONS: readonly IncidentExpectation[] = [
  {
    editionId: 'INCIDENT-QUIET',
    check: 'quiet_week',
    severity: 'block',
    label: 'Quiet week asserted over a busy one',
  },
  {
    editionId: 'INCIDENT-COUNT',
    check: 'count',
    severity: 'block',
    label: 'Count inflated beyond tolerance',
  },
  {
    editionId: 'INCIDENT-WINDOW',
    check: 'window',
    severity: 'block',
    label: 'Cited items outside the window',
  },
  {
    editionId: 'INCIDENT-MARKET',
    check: 'named_market',
    severity: 'warn',
    label: 'Market named with nothing behind it',
  },
  {
    editionId: 'INCIDENT-PLACEMENTS',
    check: 'count',
    severity: 'block',
    label: 'Group sum published as a listing count',
  },
];

export function editionById(id: string): Edition {
  const found = [...GOOD_EDITIONS, ...INCIDENT_EDITIONS].find((e) => e.id === id);
  if (!found) throw new Error('unknown edition: ' + id);
  return found;
}
