'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { classifyFormatByDimensions } = require('../src/dimensionClassifier');

test('exact IAB sizes -> banner', () => {
  for (const [w, h] of [[300, 250], [728, 90], [160, 600], [970, 250], [88, 31]]) {
    assert.strictEqual(classifyFormatByDimensions(w, h), 'banner', `${w}x${h}`);
  }
});

test('16:9 and 9:16 large shapes -> video', () => {
  assert.strictEqual(classifyFormatByDimensions(1920, 1080), 'video');
  assert.strictEqual(classifyFormatByDimensions(1280, 720), 'video');
  assert.strictEqual(classifyFormatByDimensions(1080, 1920), 'video');
});

test('mid-width non-banner -> search', () => {
  assert.strictEqual(classifyFormatByDimensions(760, 900), 'search');
  assert.strictEqual(classifyFormatByDimensions(600, 400), 'search');
});

test('small near-square -> logo', () => {
  assert.strictEqual(classifyFormatByDimensions(100, 100), 'logo');
  assert.strictEqual(classifyFormatByDimensions(64, 64), 'logo');
});

test('ambiguous shape -> null (caller may fall back to a vision hint)', () => {
  assert.strictEqual(classifyFormatByDimensions(333, 517), null);
});

test('deterministic: same input always yields same output', () => {
  const a = classifyFormatByDimensions(300, 250);
  const b = classifyFormatByDimensions(300, 250);
  assert.strictEqual(a, b);
  assert.strictEqual(a, 'banner');
});

test('invalid input -> null', () => {
  assert.strictEqual(classifyFormatByDimensions(0, 0), null);
  assert.strictEqual(classifyFormatByDimensions(null, 250), null);
  assert.strictEqual(classifyFormatByDimensions(300, undefined), null);
  assert.strictEqual(classifyFormatByDimensions(-10, -10), null);
});
