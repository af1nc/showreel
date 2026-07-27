/**
 * Runnable demo for the reach/frequency dedup library and the SWR cache.
 *
 *   npm run demo
 *
 * Part 1 shows the Sainsbury deduplication: within each market, summing channel
 * reach over-counts because audiences overlap, so the deduplicated net reach is
 * lower than the naive sum. Across markets (disjoint populations) net reach is
 * simply additive. Part 2 shows the stale-while-revalidate cache serving a slow
 * computation instantly while refreshing in the background, single-flight.
 */

import {
  computeCampaignReach,
  type MarketInput,
} from "./reachDedup.js";
import { StaleWhileRevalidate } from "./staleWhileRevalidate.js";

const nf = new Intl.NumberFormat("en-US");
const int = (n: number) => nf.format(Math.round(n));
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// Part 1 - deduplicated reach & frequency
// ---------------------------------------------------------------------------

// Synthetic campaign: three markets with disjoint populations. The last market
// has no known population universe, exercising the MAX-unit fallback.
const campaign: MarketInput[] = [
  {
    market: "Market Alpha",
    universe: 10_000_000,
    channels: [
      { name: "Display", reach: 3_000_000, impressions: 12_000_000 },
      { name: "Online Video", reach: 2_500_000, impressions: 9_000_000 },
      { name: "Social", reach: 4_000_000, impressions: 22_000_000 },
      { name: "Search", reach: 1_200_000, impressions: 3_500_000 },
    ],
  },
  {
    market: "Market Beta",
    universe: 5_000_000,
    channels: [
      { name: "Display", reach: 1_800_000, impressions: 6_500_000 },
      { name: "Online Video", reach: 1_500_000, impressions: 5_000_000 },
      { name: "Social", reach: 2_200_000, impressions: 11_000_000 },
    ],
  },
  {
    // No population universe available -> falls back to MAX single-channel reach.
    market: "Market Gamma",
    universe: null,
    channels: [
      { name: "Display", reach: 900_000, impressions: 2_800_000 },
      { name: "Social", reach: 1_100_000, impressions: 4_200_000 },
    ],
  },
];

function printReachReport(): void {
  const result = computeCampaignReach(campaign);

  console.log("============================================================");
  console.log(" Deduplicated audience reach & frequency");
  console.log("============================================================");
  console.log("");
  console.log("Per-market (reach deduplicated WITHIN each market):");
  console.log("");

  for (const m of result.perMarket) {
    const overlapRemoved = m.rawSumReach - m.netReach;
    console.log(`  ${m.market}`);
    console.log(
      `    universe basis : ${m.universeBasis}` +
        (m.universe != null ? ` (N = ${int(m.universe)})` : " (no population - MAX-unit floor)"),
    );
    console.log(`    naive sum reach: ${int(m.rawSumReach)}  <- over-counts overlap`);
    console.log(`    net reach      : ${int(m.netReach)}  (deduplicated)`);
    if (m.universeBasis === "population") {
      console.log(`    overlap removed: ${int(overlapRemoved)}  (${pct(overlapRemoved / m.rawSumReach)} of naive)`);
    }
    console.log(`    impressions    : ${int(m.impressions)}`);
    console.log(`    frequency      : ${m.frequency.toFixed(2)}x  (impressions / net reach)`);
    console.log("");
  }

  console.log("Campaign total (net reach ADDITIVE across disjoint markets):");
  console.log(`    Σ naive sum reach: ${int(result.totalRawSumReach)}`);
  console.log(`    Σ net reach      : ${int(result.totalNetReach)}   <- Σ of per-market net reach`);
  console.log(`    Σ impressions    : ${int(result.totalImpressions)}`);
  console.log(`    frequency        : ${result.totalFrequency.toFixed(2)}x`);
  console.log(`    markets rolled up: ${result.markets}`);
  console.log("");
}

// ---------------------------------------------------------------------------
// Part 2 - stale-while-revalidate cache
// ---------------------------------------------------------------------------

async function printSwrDemo(): Promise<void> {
  console.log("============================================================");
  console.log(" Stale-while-revalidate cache (single-flight refresh)");
  console.log("============================================================");
  console.log("");

  let computeCount = 0;

  // Stand-in for the expensive materialization. In the real system this is a
  // multi-second analytical rebuild; here we just sleep and bump a version.
  const cache = new StaleWhileRevalidate<{ version: number; computedAt: number }>({
    ttlMs: 300,
    compute: async () => {
      const version = ++computeCount;
      console.log(`    [compute] slow rebuild #${version} started...`);
      await sleep(150); // simulate the expensive work
      console.log(`    [compute] slow rebuild #${version} finished`);
      return { version, computedAt: Date.now() };
    },
    onRefresh: ({ ok, durationMs }) =>
      console.log(`    [refresh] background refresh settled: ok=${ok} in ${durationMs}ms`),
  });

  console.log("1) Cold start - the first reader has nothing to serve, so it waits:");
  const first = await cache.get();
  console.log(`   -> got version ${first.version} (compute ran ${computeCount}x)`);
  console.log("");

  console.log("2) Fresh cache - three concurrent readers, all instant, no recompute:");
  const fresh = await Promise.all([cache.get(), cache.get(), cache.get()]);
  console.log(`   -> versions ${fresh.map((f) => f.version).join(", ")} (compute still ran ${computeCount}x)`);
  console.log("");

  console.log(`3) Let the cache go stale (ttl = 300ms)...`);
  await sleep(350);
  console.log(`   stale? ${cache.isStale()}`);
  console.log("");

  console.log("4) Stale cache - five concurrent readers all get the OLD value instantly,");
  console.log("   and together trigger exactly ONE background refresh (single-flight):");
  const stale = await Promise.all([
    cache.get(),
    cache.get(),
    cache.get(),
    cache.get(),
    cache.get(),
  ]);
  console.log(`   -> all five served version ${stale[0].version} without blocking`);
  console.log(`      (versions returned: ${stale.map((s) => s.version).join(", ")})`);
  console.log(`      refresh running? ${cache.isRefreshing()}`);
  console.log("");

  console.log("5) Wait for the single background refresh to complete...");
  await sleep(250);
  const after = cache.peek();
  console.log(`   -> cache now holds version ${after?.version}; total computes = ${computeCount}`);
  console.log("      (one cold compute + exactly one background refresh = 2)");
  console.log("");
}

async function main(): Promise<void> {
  printReachReport();
  await printSwrDemo();
  console.log("Done.");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
