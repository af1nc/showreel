/**
 * Deterministic claim extraction.
 *
 * The gate never asks the generator what it meant, and never asks a second
 * model to interpret the copy. Interpretation is a fixed set of patterns over
 * the sentences, so the same copy always yields the same claims and a claim is
 * either extracted or it is not. Anything the patterns do not recognise is
 * simply not checked, which is a deliberate limit and is written up as such in
 * the README.
 */

import { BRANDS, MARKETS, type Brand, type Market } from './data.js';

export type ClaimKind = 'quiet_week' | 'brand_count' | 'window_items' | 'named_market';

export interface QuietWeekClaim {
  kind: 'quiet_week';
  sentence: string;
}

export interface BrandCountClaim {
  kind: 'brand_count';
  brand: Brand;
  value: number;
  /**
   * Which figure the sentence is making a claim about. Plain "new listings"
   * means distinct listings brand-wide. The copy has to say "listing
   * placements" to be judged against the summed brand+market figure.
   */
  basis: 'distinct' | 'placements';
  sentence: string;
}

export interface NamedMarketClaim {
  kind: 'named_market';
  brand: Brand;
  market: Market;
  sentence: string;
}

export interface WindowItemsClaim {
  kind: 'window_items';
  listingIds: readonly string[];
  sentence: string;
}

export type Claim = QuietWeekClaim | BrandCountClaim | NamedMarketClaim | WindowItemsClaim;

/** The minimum an edition has to expose for its claims to be extracted. */
export interface ClaimSource {
  copy: string;
  citedListingIds: readonly string[];
}

const BRAND_ALTERNATION = BRANDS.join('|');
const MARKET_ALTERNATION = MARKETS.join('|');

const QUIET_RE =
  /\b(no new listings|a quiet week|quiet week|little new activity|nothing new launched|no meaningful activity)\b/i;

/**
 * A brand-wide count sentence. Note what is NOT captured here: a market.
 *
 * The first version of this gate pulled the market out of the same sentence and
 * tested the count against that single market, because the sentence happened to
 * mention one. The copy aggregates across all markets and merely names a couple
 * of them as colour, so the recomputed per-market figure was always far lower
 * than the claim and the gate blocked a large share of perfectly good editions.
 * Counts are checked brand-wide. Named markets are a separate, weaker claim.
 */
const COUNT_RE = new RegExp(
  '\\b(' +
    BRAND_ALTERNATION +
    ')\\b[^.]{0,100}?\\b(\\d[\\d,]*)\\s+new\\s+(listing placements|listings?)\\b',
  'gi',
);

const BRAND_RE = new RegExp('\\b(' + BRAND_ALTERNATION + ')\\b', 'g');
const MARKET_RE = new RegExp('\\b(' + MARKET_ALTERNATION + ')\\b', 'g');

export function splitSentences(copy: string): string[] {
  return copy
    .split(/(?<=\.)\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function uniqueMatches(re: RegExp, sentence: string): string[] {
  const out: string[] = [];
  for (const m of sentence.matchAll(re)) {
    const value = m[1]!;
    if (!out.includes(value)) out.push(value);
  }
  return out;
}

export function extractClaims(source: ClaimSource): Claim[] {
  const claims: Claim[] = [];

  for (const sentence of splitSentences(source.copy)) {
    if (QUIET_RE.test(sentence)) {
      claims.push({ kind: 'quiet_week', sentence });
    }

    for (const m of sentence.matchAll(COUNT_RE)) {
      const brand = m[1] as Brand;
      const value = Number(m[2]!.replace(/,/g, ''));
      const noun = m[3]!.toLowerCase();
      claims.push({
        kind: 'brand_count',
        brand,
        value,
        basis: noun.startsWith('listing placements') ? 'placements' : 'distinct',
        sentence,
      });
    }

    // A market is only attributed to a brand when the sentence names exactly
    // one brand. Two brands in one sentence is ambiguous, and a gate that
    // guesses is a gate that blocks good copy.
    const brandsHere = uniqueMatches(BRAND_RE, sentence) as Brand[];
    const marketsHere = uniqueMatches(MARKET_RE, sentence) as Market[];
    if (brandsHere.length === 1 && marketsHere.length > 0) {
      for (const market of marketsHere) {
        claims.push({ kind: 'named_market', brand: brandsHere[0]!, market, sentence });
      }
    }
  }

  if (source.citedListingIds.length > 0) {
    claims.push({
      kind: 'window_items',
      listingIds: [...source.citedListingIds],
      sentence: 'Items cited as examples from this window.',
    });
  }

  return claims;
}
