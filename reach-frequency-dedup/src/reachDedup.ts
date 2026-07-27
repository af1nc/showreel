/**
 * Deduplicated audience reach & frequency across media channels.
 *
 * The problem: if a Display campaign reaches 3,000,000 people and a Video
 * campaign reaches 2,000,000 people in the same market, you CANNOT say the
 * combined reach is 5,000,000 - the two audiences overlap. Someone who saw
 * both a display ad and a video ad is one person, counted twice.
 *
 * The model (Sainsbury / random-duplication): assume each channel reaches a
 * random subset of a fixed population `N` (the "universe"), independently of
 * the others. The probability a given person is NOT reached by channel i is
 * `1 - r_i / N`. Assuming independence, the probability they are missed by
 * EVERY channel is the product of those terms, so the deduplicated net reach is
 *
 *     net = N * (1 - PROD_i (1 - r_i / N))
 *
 * Two additivity rules fall out of this:
 *   - Within a market, reach is NOT additive (audiences overlap) -> dedup with
 *     the formula above.
 *   - Across markets, reach IS additive (populations are disjoint) -> the total
 *     net reach is simply the sum of per-market net reach.
 *
 * Frequency = impressions / net_reach. Impressions ARE additive (every
 * exposure counts), so we just sum them and divide by the deduplicated reach.
 *
 * The interesting numerical detail: multiplying many terms that are each very
 * close to 1 underflows / loses precision in floating point. We compute the
 * product in LOG space instead:
 *
 *     net = N * (1 - EXP(SUM_i LN(1 - r_i / N)))
 *
 * which turns the product into a sum of logs and is numerically stable even
 * with hundreds of channels.
 */

/** One deduplicated "reach unit" within a market: a channel and its metrics. */
export interface Channel {
  /** Human-readable channel name (Display, Online Video, Social, ...). */
  name: string;
  /** Number of unique people this channel reached (deduped within the channel). */
  reach: number;
  /** Total ad exposures delivered by this channel. Additive across channels. */
  impressions: number;
}

/** The reach/frequency result for a single market. */
export interface MarketReachResult {
  /** How net reach was derived: 'population' (Sainsbury) or 'none' (fallback). */
  universeBasis: "population" | "none";
  /** The population universe used, or null when none was available. */
  universe: number | null;
  /** Deduplicated unique people reached across all channels in this market. */
  netReach: number;
  /** Naive sum of per-channel reach (double-counts overlap). Shown for contrast. */
  rawSumReach: number;
  /** Sum of impressions across channels. */
  impressions: number;
  /** impressions / netReach - average times a reached person saw an ad. */
  frequency: number;
}

/**
 * Compute deduplicated net reach for a set of channels sharing one population.
 *
 * Uses the log-space Sainsbury formula when a positive `universe` is supplied:
 *   net = universe * (1 - EXP(SUM(LN(1 - reach / universe))))
 *
 * Each per-channel ratio is clamped just below 1 (a single channel can never
 * reach more than the whole population, and `LN(0)` is -Infinity), mirroring
 * the `LEAST(ratio, 0.999999)` guard used in the original SQL implementation.
 *
 * When there is no usable universe (null, 0, or negative), we fall back to the
 * single largest channel reach as a conservative floor - the true net reach is
 * at least as large as the biggest individual channel, but without a universe
 * we cannot model the overlap of the rest.
 *
 * @param channels The channels to combine (may be empty -> 0).
 * @param universe The shared population size, or null/0 when unknown.
 */
export function computeNetReach(
  channels: readonly Channel[],
  universe: number | null,
): number {
  if (channels.length === 0) return 0;

  const hasUniverse = typeof universe === "number" && universe > 0;

  if (!hasUniverse) {
    // No population to model overlap against: floor at the largest single unit.
    return Math.max(0, ...channels.map((c) => c.reach));
  }

  const N = universe as number;

  // Sum of logs (log-space product) - stable even with many near-1 terms.
  let lnProd = 0;
  for (const c of channels) {
    if (c.reach <= 0) continue; // a channel reaching nobody contributes LN(1) = 0
    const ratio = Math.min(c.reach / N, 0.999999);
    lnProd += Math.log(1 - ratio);
  }

  return N * (1 - Math.exp(lnProd));
}

/**
 * Average frequency = impressions / net reach.
 * Returns 0 when net reach is 0 (no one was reached, so frequency is undefined).
 */
export function computeFrequency(impressions: number, netReach: number): number {
  if (netReach <= 0) return 0;
  return impressions / netReach;
}

/**
 * Full reach + frequency roll-up for a single market's channels.
 * Combines {@link computeNetReach} and {@link computeFrequency} and reports the
 * naive (overlap-inflated) sum alongside the deduplicated figure.
 */
export function computeMarketReach(
  channels: readonly Channel[],
  universe: number | null,
): MarketReachResult {
  const netReach = computeNetReach(channels, universe);
  const impressions = channels.reduce((sum, c) => sum + c.impressions, 0);
  const rawSumReach = channels.reduce((sum, c) => sum + c.reach, 0);
  const hasUniverse = typeof universe === "number" && universe > 0;

  return {
    universeBasis: hasUniverse ? "population" : "none",
    universe: hasUniverse ? (universe as number) : null,
    netReach,
    rawSumReach,
    impressions,
    frequency: computeFrequency(impressions, netReach),
  };
}

/** A market: its channels and its population universe (null/0 when unknown). */
export interface MarketInput {
  market: string;
  universe: number | null;
  channels: Channel[];
}

/** A per-market result carrying the market label alongside its metrics. */
export interface LabelledMarketResult extends MarketReachResult {
  market: string;
}

/** The campaign-level roll-up across markets. */
export interface CampaignReachResult {
  perMarket: LabelledMarketResult[];
  /** Σ per-market net reach - valid because markets have disjoint populations. */
  totalNetReach: number;
  /** Σ per-market naive reach - for contrast with the deduplicated total. */
  totalRawSumReach: number;
  /** Σ impressions across all markets. */
  totalImpressions: number;
  /** totalImpressions / totalNetReach. */
  totalFrequency: number;
  /** Number of markets rolled up. */
  markets: number;
}

/**
 * Roll a set of markets up to a campaign total.
 *
 * Reach is deduplicated WITHIN each market (Sainsbury) and then summed ACROSS
 * markets - the across-market sum is exact because the populations are disjoint,
 * so there is no cross-market overlap to remove.
 */
export function computeCampaignReach(
  markets: readonly MarketInput[],
): CampaignReachResult {
  const perMarket: LabelledMarketResult[] = markets.map((m) => ({
    market: m.market,
    ...computeMarketReach(m.channels, m.universe),
  }));

  const totalNetReach = perMarket.reduce((s, m) => s + m.netReach, 0);
  const totalRawSumReach = perMarket.reduce((s, m) => s + m.rawSumReach, 0);
  const totalImpressions = perMarket.reduce((s, m) => s + m.impressions, 0);

  return {
    perMarket,
    totalNetReach,
    totalRawSumReach,
    totalImpressions,
    totalFrequency: computeFrequency(totalImpressions, totalNetReach),
    markets: perMarket.length,
  };
}
