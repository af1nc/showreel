'use strict';

/**
 * demo.js - runs the whole pipeline offline. No API key, no network.
 *
 * It pushes a handful of synthetic "ads" (dimension tuples + placeholder bytes)
 * through the classifier and prints the results, then re-runs the identical
 * inputs to demonstrate the central property:
 *
 *   The FORMAT label is STABLE across runs (it comes from pixels), while the
 *   model's own format guess FLIP-FLOPS (which is exactly why we do not trust
 *   the model for format).
 *
 * Finally it shows the retry/backoff wrapper handling transient errors.
 */

const { MockVision } = require('./visionClient');
const { classifyMany, classifyAd } = require('./classifier');

// A placeholder "image": just a JSON descriptor the MockVision understands.
// In production these bytes would be the actual creative image (PNG/JPEG).
function fakeImage(scene) {
  return Buffer.from(JSON.stringify({ scene }), 'utf8');
}

const ADS = [
  { name: 'Medium rectangle',  width: 300,  height: 250,  imageBytes: fakeImage('promo_sale') },
  { name: 'Leaderboard',       width: 728,  height: 90,   imageBytes: fakeImage('brand_story') },
  { name: 'Search screenshot', width: 760,  height: 900,  imageBytes: fakeImage('promo_sale') },
  { name: 'Brand logo',        width: 100,  height: 100,  imageBytes: fakeImage('logo_only') },
  { name: 'Landscape video',   width: 1920, height: 1080, imageBytes: fakeImage('product_shot') },
  { name: 'Odd / ambiguous',   width: 333,  height: 517,  imageBytes: fakeImage('seasonal') },
];

function fmt(v) {
  return v === null || v === undefined ? '-' : String(v);
}

function truncate(s, n) {
  s = fmt(s);
  return s.length > n ? `${s.slice(0, n - 1)}~` : s;
}

function pad(v, n) {
  const s = fmt(v);
  return s.length >= n ? s : s + ' '.repeat(n - s.length);
}

function printTable(title, rows) {
  console.log(`\n${title}`);
  console.log('='.repeat(title.length));
  console.log(
    pad('ad', 18), pad('dims', 10), pad('ad_type', 9), pad('src', 16),
    pad('model_guess', 12), pad('theme', 10), 'summary',
  );
  for (const r of rows) {
    console.log(
      pad(r.name, 18), pad(r.dims, 10), pad(r.ad_type, 9), pad(r.src, 16),
      pad(r.guess, 12), pad(r.theme, 10), r.summary,
    );
  }
}

function toRow(ad, res) {
  return {
    name: ad.name,
    dims: `${ad.width}x${ad.height}`,
    ad_type: res.ad_type,
    src: res.format_source,
    guess: res.vision_ad_type_guess,
    theme: res.theme,
    summary: truncate(res.summary, 52),
  };
}

function stripName(ad) {
  return { width: ad.width, height: ad.height, imageBytes: ad.imageBytes };
}

async function main() {
  console.log('Multimodal ad-creative classifier - offline demo (MockVision, no API key)');

  const vision = new MockVision({ flakyFormat: true });

  const run1 = await classifyMany(ADS.map(stripName), vision, { concurrency: 3, baseDelayMs: 10 });
  printTable('Run 1', ADS.map((ad, i) => toRow(ad, run1[i])));

  const run2 = await classifyMany(ADS.map(stripName), vision, { concurrency: 3, baseDelayMs: 10 });
  printTable('Run 2 (identical inputs)', ADS.map((ad, i) => toRow(ad, run2[i])));

  // Stability report: pixel-decided formats must be identical across runs.
  console.log('\nStability check');
  console.log('===============');
  let pixelStable = true;
  ADS.forEach((ad, i) => {
    const a = run1[i].ad_type;
    const b = run2[i].ad_type;
    const g1 = run1[i].vision_ad_type_guess;
    const g2 = run2[i].vision_ad_type_guess;
    const src = run1[i].format_source;
    const same = a === b;
    if (src === 'dimensions') pixelStable = pixelStable && same;
    const flip = g1 !== g2 ? '(model guess flip-flopped)' : '(model guess same by chance)';
    console.log(
      `  ${pad(ad.name, 18)} format ${pad(a, 8)} ${same ? 'STABLE ' : 'CHANGED'}` +
      `  [${src}]  model: ${pad(g1, 7)}-> ${pad(g2, 7)} ${flip}`,
    );
  });
  console.log(`\n  => pixel-decided formats stable across runs: ${pixelStable ? 'YES' : 'NO'}`);
  console.log('  Note: the "Odd / ambiguous" row matches no IAB size or video ratio, so it');
  console.log('  falls back to the model and CAN flip - the exception that proves the rule.');

  // Retry / backoff demonstration.
  console.log('\nRetry / backoff demo (vision throws 429 twice, then succeeds)');
  console.log('============================================================');
  const flaky = new MockVision({ failFirst: 2 });
  const res = await classifyAd(
    { width: 300, height: 250, imageBytes: fakeImage('promo_sale') },
    flaky,
    {
      baseDelayMs: 15,
      onRetry: ({ attempt, waitMs, error }) =>
        console.log(`  attempt ${attempt} failed (status ${error.status}) - backing off ${waitMs}ms`),
    },
  );
  console.log(`  final: ad_type=${res.ad_type} theme=${res.theme} confidence=${res.confidence}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
