/**
 * Proof one: the backtest.
 *
 * Every known-good historical edition must pass. A gate that blocks good work
 * is a gate that gets turned off, so this is the tighter of the two proofs in
 * day-to-day terms.
 *
 * It is also, on its own, worthless as evidence that the gate works. See
 * negativeControl.test.ts for why.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { DATASET, brandWindowDistinct } from '../src/data.js';
import { GOOD_EDITIONS, editionById } from '../src/editions.js';
import { validate } from '../src/gate.js';

test('the backtest corpus is not trivially small', () => {
  assert.ok(
    GOOD_EDITIONS.length >= 10,
    'expected at least 10 known-good editions, got ' + GOOD_EDITIONS.length,
  );
});

test('no known-good edition is blocked', () => {
  const blocked: string[] = [];
  for (const edition of GOOD_EDITIONS) {
    const result = validate(edition, DATASET);
    if (result.decision === 'block') {
      blocked.push(
        edition.id + ' -> ' + result.blocking.map((f) => f.check + ': ' + f.detail).join(' | '),
      );
    }
  }
  assert.deepEqual(blocked, [], 'editions blocked that should not have been');
});

test('every good edition actually had claims extracted from it', () => {
  // Otherwise the backtest would pass simply because nothing was ever checked.
  for (const edition of GOOD_EDITIONS) {
    const result = validate(edition, DATASET);
    assert.ok(result.claims.length > 0, edition.id + ' produced no claims to check');
  }
});

test('the asymmetric tolerance is genuinely exercised', () => {
  // The archive case: published when the figure was lower, recomputed higher today.
  const edition = editionById('GOOD-UNDERSTATED');
  const claimed = Number(/added (\d+) new listings/.exec(edition.copy)?.[1]);
  const recomputedToday = brandWindowDistinct(DATASET, 'Everline', edition.window);

  assert.ok(Number.isFinite(claimed), 'could not read the claimed figure back out of the copy');
  assert.ok(
    recomputedToday - claimed >= 3,
    'expected the recomputed figure (' +
      recomputedToday +
      ') to sit materially above the claim (' +
      claimed +
      '), otherwise this test proves nothing',
  );
  assert.equal(validate(edition, DATASET).decision, 'pass');
});

test('a quiet week that really was quiet is allowed to say so', () => {
  const edition = editionById('GOOD-QUIET');
  assert.equal(validate(edition, DATASET).decision, 'pass');
});

test('the market-level figure passes when the copy says that is what it is', () => {
  const edition = editionById('GOOD-PLACEMENTS');
  const result = validate(edition, DATASET);
  assert.equal(result.decision, 'pass');
  const countClaim = result.claims.find((c) => c.kind === 'brand_count');
  assert.equal(countClaim?.kind === 'brand_count' ? countClaim.basis : null, 'placements');
});
