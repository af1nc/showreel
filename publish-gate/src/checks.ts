/**
 * The four checks. Each one recomputes a figure from the dataset and compares
 * it to what the copy asserts. The generator's own numbers are never consulted.
 */

import {
  brandMarketDistinct,
  brandWindowDistinct,
  brandWindowPlacements,
  inWindow,
  rowsForListing,
  windowLaunchCount,
  type Dataset,
  type Window,
} from './data.js';
import type { Claim } from './claims.js';

export type Severity = 'block' | 'warn';
export type CheckId = 'quiet_week' | 'count' | 'window' | 'named_market';

export interface Finding {
  check: CheckId;
  severity: Severity;
  /** The sentence the claim came from, quoted back so an editor can find it. */
  sentence: string;
  /** What the copy said. */
  claimed: string;
  /** What the data says, recomputed now. */
  recomputed: string;
  /** Which figure the claim was judged against. Stated so nobody has to guess. */
  basis: string;
  detail: string;
}

export interface CheckContext {
  dataset: Dataset;
  window: Window;
}

/**
 * TOLERANCE IS ASYMMETRIC, AND THIS IS THE SINGLE MOST IMPORTANT LINE IN THE
 * PROJECT.
 *
 * Collection is incremental: listings keep arriving for a window long after
 * that window closed. An edition published three weeks ago quoted the figure
 * that was true when it was written, and the figure recomputed today is
 * legitimately higher. So:
 *
 *   claimed <  recomputed   ->  NEVER a finding. Not at any distance.
 *   claimed == recomputed   ->  fine.
 *   claimed >  recomputed   ->  a finding, but only once it is material.
 *
 * Only an over-claim can be a defect, because only an over-claim asserts
 * something the data cannot support. Under-claiming is the expected state of
 * every archived edition, and a symmetric tolerance turns the entire archive
 * red for no reason.
 */
export const OVERSTATEMENT_TOLERANCE = 0.15;

/** Small absolute cushion so a claim of 4 against a true 3 is not a scandal. */
export const OVERSTATEMENT_FLOOR = 3;

/** Above this many launches in the window, "a quiet week" is not defensible. */
export const QUIET_WEEK_CEILING = 5;

export function overstates(claimed: number, recomputed: number): boolean {
  if (claimed <= recomputed) return false;
  const excess = claimed - recomputed;
  return excess > OVERSTATEMENT_FLOOR && excess > recomputed * OVERSTATEMENT_TOLERANCE;
}

const DISTINCT_BASIS = 'COUNT(DISTINCT listing_id), brand-wide across all markets';
const PLACEMENT_BASIS = 'distinct listing_id per brand+market group, then summed';

/**
 * Check 1: quiet-week claim.
 *
 * Modelled on an edition that told readers a week had been uneventful while the
 * dataset held a normal week of launches. The asymmetry applies here too: the
 * sentence asserts an upper bound on activity, so only activity above the
 * ceiling contradicts it.
 */
function checkQuietWeek(claim: Claim, ctx: CheckContext): Finding[] {
  if (claim.kind !== 'quiet_week') return [];
  const launches = windowLaunchCount(ctx.dataset, ctx.window);
  if (launches <= QUIET_WEEK_CEILING) return [];
  return [
    {
      check: 'quiet_week',
      severity: 'block',
      sentence: claim.sentence,
      claimed: 'little or no new activity in the window',
      recomputed: String(launches) + ' distinct listings launched in the window',
      basis: 'COUNT(DISTINCT listing_id), all brands, launch_date inside the window',
      detail:
        'The copy asserts the window was quiet. The recomputed launch count is ' +
        launches +
        ', above the ceiling of ' +
        QUIET_WEEK_CEILING +
        '.',
    },
  ];
}

/**
 * Check 2: count claim.
 *
 * "Beacon added 34 new listings" is recomputed brand-wide, at the altitude the
 * sentence aggregates at, and judged with the asymmetric tolerance above.
 */
function checkCount(claim: Claim, ctx: CheckContext): Finding[] {
  if (claim.kind !== 'brand_count') return [];

  const distinct = brandWindowDistinct(ctx.dataset, claim.brand, ctx.window);
  const placements = brandWindowPlacements(ctx.dataset, claim.brand, ctx.window);
  const recomputed = claim.basis === 'placements' ? placements : distinct;
  const basis = claim.basis === 'placements' ? PLACEMENT_BASIS : DISTINCT_BASIS;

  if (!overstates(claim.value, recomputed)) return [];

  let detail =
    'Claim exceeds the recomputed figure by ' +
    (claim.value - recomputed) +
    ', beyond the ' +
    Math.round(OVERSTATEMENT_TOLERANCE * 100) +
    ' per cent over-claim tolerance. A claim below the recomputed figure would not be a finding.';

  if (claim.basis === 'distinct' && claim.value === placements && placements !== distinct) {
    detail +=
      ' The claimed figure is exactly the summed brand+market total (' +
      placements +
      '), which counts a listing once per market it is live in. The sentence is brand-wide, so the distinct figure (' +
      distinct +
      ') is the one it is making a claim about.';
  }

  return [
    {
      check: 'count',
      severity: 'block',
      sentence: claim.sentence,
      claimed: String(claim.value) + ' new listings from ' + claim.brand,
      recomputed: String(recomputed) + ' (' + claim.brand + ', this window)',
      basis,
      detail,
    },
  ];
}

/**
 * Check 3: window claim.
 *
 * Items held up as examples from this window must exist and must carry a
 * launch date inside it. Modelled on an edition that illustrated a week with
 * items that had gone live a month earlier.
 */
function checkWindow(claim: Claim, ctx: CheckContext): Finding[] {
  if (claim.kind !== 'window_items') return [];

  const offenders: string[] = [];
  for (const id of claim.listingIds) {
    const rows = rowsForListing(ctx.dataset, id);
    if (rows.length === 0) {
      offenders.push(id + ' (no such listing in the dataset)');
      continue;
    }
    const insideWindow = rows.some((r) => inWindow(r.launch_date, ctx.window));
    if (!insideWindow) {
      offenders.push(id + ' (launched ' + rows[0]!.launch_date + ')');
    }
  }
  if (offenders.length === 0) return [];

  return [
    {
      check: 'window',
      severity: 'block',
      sentence: claim.sentence,
      claimed:
        String(claim.listingIds.length) +
        ' items presented as launching in ' +
        ctx.window.id +
        ' (' +
        ctx.window.start +
        ' to ' +
        ctx.window.end +
        ')',
      recomputed: String(offenders.length) + ' of them fail that test',
      basis: 'launch_date of each cited listing_id against the window bounds',
      detail: offenders.join('; '),
    },
  ];
}

/**
 * Check 4: named-market claim. WARNING TIER, NOT BLOCKING.
 *
 * A market named alongside a brand should have at least one listing for that
 * brand in the window. This is the weakest of the four signals: the sentence
 * names markets as colour ("across markets including Portugal and Chile"), the
 * naming may be about presence rather than new activity, and our market
 * attribution on any single row is the least reliable field we hold. A weak
 * signal that stops a publish is a signal that gets overridden on reflex until
 * nobody reads any of the findings, so it flags and lets the edition through.
 */
function checkNamedMarket(claim: Claim, ctx: CheckContext): Finding[] {
  if (claim.kind !== 'named_market') return [];
  const count = brandMarketDistinct(ctx.dataset, claim.brand, claim.market, ctx.window);
  if (count > 0) return [];
  return [
    {
      check: 'named_market',
      severity: 'warn',
      sentence: claim.sentence,
      claimed: claim.brand + ' activity in ' + claim.market,
      recomputed: '0 listings for ' + claim.brand + ' in ' + claim.market + ' this window',
      basis: 'COUNT(DISTINCT listing_id) for the brand+market pair',
      detail:
        'The market is named next to the brand but has no listing for it in the window. Flagged, not blocked.',
    },
  ];
}

export interface CheckSpec {
  id: CheckId;
  title: string;
  severity: Severity;
  run: (claim: Claim, ctx: CheckContext) => Finding[];
}

export const CHECKS: readonly CheckSpec[] = [
  { id: 'quiet_week', title: 'Quiet-week claim', severity: 'block', run: checkQuietWeek },
  { id: 'count', title: 'Count claim', severity: 'block', run: checkCount },
  { id: 'window', title: 'Window claim', severity: 'block', run: checkWindow },
  { id: 'named_market', title: 'Named-market claim', severity: 'warn', run: checkNamedMarket },
];
