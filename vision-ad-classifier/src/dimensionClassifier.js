'use strict';

/**
 * dimensionClassifier.js
 *
 * Deterministic ad-FORMAT classification from pixel dimensions.
 *
 * The core idea: an ad creative's *format* (display banner vs. search-ad
 * screenshot vs. logo vs. video) can be read straight off its width and height.
 * IAB standard banner sizes are a fixed, publicly documented table, so an exact
 * dimension match is a rock-solid signal.
 *
 * Everything in this file is pure and side-effect free, which makes it trivially
 * unit-testable and, crucially, 100% reproducible: the same pixels always yield
 * the same format. That reproducibility is the whole point (see README).
 */

// Generic format allowlist. FORMAT is decided here (from pixels), never by a
// model. See README for why.
const FORMAT_ENUM = ['banner', 'search', 'video', 'logo'];

// IAB standard ad unit sizes as "WIDTHxHEIGHT". These are public industry
// standards; an exact match is a definitive "banner".
const IAB_BANNER_SIZES = new Set([
  '300x250', '336x280', '728x90', '160x600', '300x600', '320x50', '320x100',
  '300x50', '468x60', '234x60', '120x600', '180x150', '125x125', '88x31',
  '970x250', '970x90', '300x1050', '120x60', '250x250', '200x200',
  '120x240', '240x400', '480x320', '768x90',
]);

// Common landscape / portrait video aspect ratios.
const RATIO_16_9 = 16 / 9; // 1.7778 landscape video
const RATIO_9_16 = 9 / 16; // 0.5625 portrait / story video
const VIDEO_RATIO_TOLERANCE = 0.03;
const VIDEO_MIN_LONG_SIDE = 480; // ignore tiny elements that happen to be 16:9

function isVideoShape(w, h) {
  const longSide = Math.max(w, h);
  if (longSide < VIDEO_MIN_LONG_SIDE) return false;
  const ratio = w / h;
  return (
    Math.abs(ratio - RATIO_16_9) <= VIDEO_RATIO_TOLERANCE ||
    Math.abs(ratio - RATIO_9_16) <= VIDEO_RATIO_TOLERANCE
  );
}

/**
 * classifyFormatByDimensions(width, height)
 *
 * Returns one of FORMAT_ENUM, or null when the dimensions don't map to a
 * confident format (the caller may then fall back to a vision hint).
 *
 * @param {number} width
 * @param {number} height
 * @returns {'banner'|'search'|'video'|'logo'|null}
 */
function classifyFormatByDimensions(width, height) {
  const w = Number(width);
  const h = Number(height);
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return null;

  // 1) Exact IAB banner match - the strongest, most deterministic signal.
  if (IAB_BANNER_SIZES.has(`${w}x${h}`)) return 'banner';

  // 2) Video by aspect ratio (16:9 landscape or 9:16 portrait), large enough
  //    to be a real video unit rather than a coincidental small element.
  if (isVideoShape(w, h)) return 'video';

  // 3) Search-ad screenshots render in a mid width band (roughly 500-1200 px)
  //    and are NOT a standard banner size. Height varies a lot (stacked
  //    sitelinks), so width alone is the tell.
  if (w >= 500 && w <= 1200) return 'search';

  // 4) Small near-square marks are logos / wordmarks.
  if (w <= 200 && h <= 200) return 'logo';

  // 5) Anything else: not confident from pixels alone.
  return null;
}

module.exports = {
  FORMAT_ENUM,
  IAB_BANNER_SIZES,
  classifyFormatByDimensions,
};
