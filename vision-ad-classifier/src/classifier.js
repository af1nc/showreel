'use strict';

/**
 * classifier.js
 *
 * Combines the two signals into one result:
 *   - FORMAT (`ad_type`) comes from pixel dimensions        -> deterministic
 *   - CONTENT (`theme`, `summary`) comes from the vision client -> probabilistic
 *
 * Around the vision call sits a retry-with-jitter wrapper (for transient
 * 429/5xx), and every model-returned field is validated against a hard
 * allowlist before it is trusted.
 */

const { classifyFormatByDimensions, FORMAT_ENUM } = require('./dimensionClassifier');
const { AD_TYPE_ENUM, THEME_ENUM } = require('./visionClient');
const { runPool } = require('./workerPool');

const TRANSIENT_STATUSES = new Set([429, 500, 502, 503, 504]);

function isTransient(err) {
  if (!err) return false;
  if (err.transient === true) return true;
  if (typeof err.status === 'number' && TRANSIENT_STATUSES.has(err.status)) return true;
  // No status usually means a network-level failure - treat as transient.
  if (err.status === undefined && err.code) return true;
  return false;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * withRetry - exponential backoff with jitter.
 *
 * Production defaults mirror the original service: base 2000ms, factor 3 gives
 * roughly 2s, 6s, 18s between attempts, with +/-25% jitter so parallel workers
 * do not retry in lockstep. Up to 4 attempts. Everything is tunable (the demo
 * uses tiny delays so it finishes instantly).
 *
 * @param {(attempt:number) => Promise<any>} fn
 * @param {object} [opts]
 */
async function withRetry(fn, opts = {}) {
  const maxAttempts = opts.maxAttempts || 4;
  const baseDelayMs = opts.baseDelayMs || 2000;
  const factor = opts.factor || 3;
  const jitter = opts.jitter != null ? opts.jitter : 0.25;
  const onRetry = opts.onRetry;

  let lastErr;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      return await fn(attempt);
    } catch (err) {
      lastErr = err;
      if (!isTransient(err) || attempt === maxAttempts) throw err;
      const base = baseDelayMs * Math.pow(factor, attempt - 1);
      const wait = Math.floor(base * (1 - jitter + Math.random() * 2 * jitter));
      if (onRetry) onRetry({ attempt, waitMs: wait, error: err });
      await sleep(wait);
    }
  }
  throw lastErr;
}

function validateEnum(value, allowlist, fallback = null) {
  return allowlist.includes(value) ? value : fallback;
}

/**
 * classifyAd - classify a single ad creative.
 *
 * @param {object} ad             { width, height, imageBytes }
 * @param {object} visionClient   an object implementing classify(imageBytes)
 * @param {object} [opts]         retry options + { onRetry }
 * @returns {Promise<object>}
 */
async function classifyAd(ad, visionClient, opts = {}) {
  const width = ad.width != null ? ad.width : null;
  const height = ad.height != null ? ad.height : null;

  // (1) FORMAT - deterministic from pixels. Never from the model.
  const dimFormat = classifyFormatByDimensions(width, height);

  // (2) CONTENT - from the vision client, wrapped in retry/backoff.
  let vision = null;
  let contentError = null;
  try {
    vision = await withRetry(() => visionClient.classify(ad.imageBytes), opts);
  } catch (err) {
    contentError = err;
  }

  // (3) Allowlist-validate everything the model returned. Anything off-list is
  //     discarded rather than trusted.
  const visionAdTypeGuess = vision ? validateEnum(vision.ad_type, AD_TYPE_ENUM, null) : null;
  const theme = vision ? validateEnum(vision.theme, THEME_ENUM, null) : null;
  const summary = vision && vision.summary != null ? String(vision.summary).slice(0, 500) : null;

  // (4) Resolve the authoritative FORMAT (`ad_type`):
  //     pixels first; only if pixels are inconclusive do we fall back to the
  //     model's (validated) guess; otherwise 'unknown'.
  let ad_type = dimFormat;
  let formatSource = 'dimensions';
  if (!ad_type) {
    ad_type = visionAdTypeGuess;
    formatSource = ad_type ? 'vision_fallback' : 'none';
  }

  return {
    ad_type: ad_type || 'unknown',
    theme,
    summary,
    width,
    height,
    format_source: formatSource,             // 'dimensions' | 'vision_fallback' | 'none'
    vision_ad_type_guess: visionAdTypeGuess, // what the model *said* (not trusted for format)
    content_source: vision ? 'vision' : 'unavailable',
    confidence: buildConfidence(dimFormat, vision, contentError),
  };
}

function buildConfidence(dimFormat, vision, contentError) {
  if (contentError) return `content_error:${contentError.status || contentError.code || 'unknown'}`;
  if (dimFormat && vision) return 'dimensions+vision';
  if (dimFormat) return 'dimensions_only';
  if (vision) return 'vision_only';
  return 'none';
}

/**
 * classifyMany - classify a batch through a bounded-concurrency pool.
 *
 * @param {Array<object>} ads
 * @param {object} visionClient
 * @param {object} [opts]  { concurrency, onProgress, ...retryOpts }
 */
async function classifyMany(ads, visionClient, opts = {}) {
  return runPool(ads, (ad) => classifyAd(ad, visionClient, opts), opts);
}

module.exports = {
  classifyAd,
  classifyMany,
  withRetry,
  isTransient,
  validateEnum,
  FORMAT_ENUM,
  AD_TYPE_ENUM,
  THEME_ENUM,
};
