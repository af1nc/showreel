#!/usr/bin/env node
'use strict';

/**
 * Offline demo for Share of AI.
 *
 * Runs the whole pipeline over the deterministic MockLLM (no network, no API
 * key, no cloud), prints a per-brand Share of AI table plus the collected
 * citations, and writes the full result set to ./output/results.json.
 *
 *   npm run demo
 */

const fs = require('fs');
const path = require('path');

const { MockLLM } = require('./llmClient');
const { runShareOfAi } = require('./shareOfAi');

const ROOT = path.join(__dirname, '..');
const brandConfig = require(path.join(ROOT, 'config', 'brands.json'));
const queryConfig = require(path.join(ROOT, 'config', 'queries.json'));

// ---------------------------------------------------------------------------
// Tiny console table helpers (no dependencies)
// ---------------------------------------------------------------------------

function pad(str, width, align) {
  const s = String(str);
  if (s.length >= width) return s;
  const gap = ' '.repeat(width - s.length);
  return align === 'right' ? gap + s : s + gap;
}

function printTable(headers, rows) {
  const widths = headers.map((h, i) =>
    Math.max(h.label.length, ...rows.map((r) => String(r[i]).length))
  );
  const line = headers.map((h, i) => pad(h.label, widths[i], h.align)).join('  ');
  console.log(line);
  console.log(widths.map((w) => '-'.repeat(w)).join('  '));
  for (const r of rows) {
    console.log(headers.map((h, i) => pad(r[i], widths[i], h.align)).join('  '));
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const client = new MockLLM(brandConfig.brands);
  const snapshotDate = '2025-01-06';

  console.log('=== Share of AI (offline demo, MockLLM) ===');
  console.log(`Snapshot date : ${snapshotDate}`);
  console.log(`Brands tracked: ${brandConfig.brands.length}`);
  console.log(`Anchor brand  : ${brandConfig.anchor}`);
  console.log('');

  const result = await runShareOfAi(client, queryConfig, brandConfig, snapshotDate);

  console.log(`Answers analysed: ${result.rows.length}  |  errors: ${result.errors.length}`);
  console.log('');

  // --- Scoreboard ---------------------------------------------------------
  console.log('Share of AI scoreboard (ranked by first-appearance-weighted score)');
  console.log('');
  printTable(
    [
      { label: 'Brand',        align: 'left' },
      { label: 'Group',        align: 'left' },
      { label: 'Share of AI%', align: 'right' },
      { label: 'Visibility%',  align: 'right' },
      { label: 'Mention sh.%', align: 'right' },
      { label: 'Avg rank',     align: 'right' },
      { label: 'Appearances',  align: 'right' }
    ],
    result.scoreboard.map((s) => [
      s.brand,
      s.group || '',
      s.share_of_ai_pct.toFixed(1),
      s.visibility_pct.toFixed(1),
      s.mention_share_pct.toFixed(1),
      s.avg_rank == null ? '-' : s.avg_rank.toFixed(2),
      s.appearances
    ])
  );
  console.log('');

  // --- Per-answer ranking snapshot ---------------------------------------
  console.log('Per-answer first-appearance ranking (sample)');
  console.log('');
  for (const row of result.rows) {
    const order = row.brands_mentioned
      .map((b) => `${b.rank}. ${b.brand} (x${b.mention_count})`)
      .join('  ');
    console.log(`  [${row.query_id} / ${row.market}] ${order || '(no tracked brands)'}`);
  }
  console.log('');

  // --- Citations ----------------------------------------------------------
  const domains = new Map();
  for (const row of result.rows) {
    for (const c of row.citations) {
      domains.set(c.domain, (domains.get(c.domain) || 0) + 1);
    }
  }
  console.log('Grounding citations by domain');
  console.log('');
  printTable(
    [
      { label: 'Domain', align: 'left' },
      { label: 'Cited',  align: 'right' }
    ],
    Array.from(domains.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([domain, count]) => [domain, count])
  );
  console.log('');

  // --- Persist ------------------------------------------------------------
  const outDir = path.join(ROOT, 'output');
  fs.mkdirSync(outDir, { recursive: true });
  const outFile = path.join(outDir, 'results.json');
  fs.writeFileSync(outFile, JSON.stringify(result, null, 2));
  console.log(`Wrote full results to ${path.relative(ROOT, outFile)}`);
}

main().catch((err) => {
  console.error('Demo failed:', err);
  process.exit(1);
});
