'use strict';

/**
 * visionClient.js
 *
 * A tiny provider-agnostic interface for the "what does the ad SAY?" part of
 * classification - the CONTENT (theme + summary).
 *
 * To plug in any real multimodal model (Gemini Vision, GPT-4o, ...),
 * implement one method:
 *
 *     async classify(imageBytes) -> { ad_type, theme, summary }
 *
 * Note the returned `ad_type`: the model is *allowed* to guess a format, but
 * the classifier deliberately ignores that guess (see README: "where NOT to
 * trust the model"). Only `theme` and `summary` are trusted from the model.
 */

const crypto = require('crypto');

// Allowlists the classifier validates model output against.
// (AD_TYPE_ENUM intentionally matches dimensionClassifier's FORMAT_ENUM: it is
// the set of format labels a model might emit, all of which we re-derive from
// pixels anyway.)
const AD_TYPE_ENUM = ['banner', 'search', 'video', 'logo'];
const THEME_ENUM = ['promotion', 'brand', 'product', 'seasonal'];

/**
 * Base interface. Subclass and implement classify().
 */
class VisionClient {
  // eslint-disable-next-line no-unused-vars
  async classify(imageBytes) {
    throw new Error('VisionClient.classify(imageBytes) must be implemented by a subclass');
  }
}

// Canned "scenes" the mock can return, keyed by a tag the demo embeds in its
// placeholder bytes. For arbitrary bytes we pick deterministically by hash so
// the same input always yields the same content.
const DEFAULT_SCENES = {
  promo_sale:  { theme: 'promotion', summary: 'Limited-time seasonal sale: "Save up to 30% this week only".' },
  brand_story: { theme: 'brand',     summary: 'Brand-awareness creative with a tagline and no explicit offer.' },
  product_shot:{ theme: 'product',   summary: 'Highlights a premium product tier and its key features.' },
  seasonal:    { theme: 'seasonal',  summary: 'Seasonal campaign tied to a holiday moment.' },
  logo_only:   { theme: 'brand',     summary: null },
};

function hashPick(imageBytes, keys) {
  const buf = Buffer.isBuffer(imageBytes) ? imageBytes : Buffer.from(imageBytes || []);
  const h = crypto.createHash('sha256').update(buf).digest();
  return keys[h[0] % keys.length];
}

/**
 * MockVision - an offline stand-in for a real multimodal model.
 *
 * Returns canned structured output so the demo runs with no API key and no
 * network. It also deliberately simulates two real-world behaviours:
 *   - `flakyFormat`: the model's own FORMAT guess is randomised each call,
 *     mirroring the non-determinism that led us to stop trusting the model for
 *     format and read it off pixels instead.
 *   - `failFirst`: throw a transient (429-style) error a few times before
 *     succeeding, so the retry/backoff wrapper can be demonstrated.
 */
class MockVision extends VisionClient {
  /**
   * @param {object}  [opts]
   * @param {object}  [opts.scenes]      Map of tag -> { theme, summary }.
   * @param {number}  [opts.failFirst]   Throw a transient error this many times
   *                                      before the first success (per instance).
   * @param {boolean} [opts.flakyFormat] Randomise the model's ad_type guess each
   *                                      call (default true).
   */
  constructor(opts = {}) {
    super();
    this.scenes = opts.scenes || DEFAULT_SCENES;
    this.failFirst = opts.failFirst || 0;
    this.flakyFormat = opts.flakyFormat !== false;
    this._calls = 0;
  }

  _sceneFor(imageBytes) {
    // Demo convenience: placeholder bytes may be a small JSON descriptor such
    // as {"scene":"promo_sale"}. Real image bytes fall through to a hash pick.
    try {
      const asText = Buffer.from(imageBytes).toString('utf8');
      const obj = JSON.parse(asText);
      if (obj && obj.scene && this.scenes[obj.scene]) return this.scenes[obj.scene];
    } catch (_) {
      /* not a JSON descriptor - fall through to hash-based selection */
    }
    return this.scenes[hashPick(imageBytes, Object.keys(this.scenes))];
  }

  async classify(imageBytes) {
    this._calls += 1;
    if (this._calls <= this.failFirst) {
      const err = new Error('mock vision: simulated rate limit');
      err.status = 429; // transient - the retry wrapper should back off
      err.transient = true;
      throw err;
    }
    const scene = this._sceneFor(imageBytes);
    // The model's FORMAT guess. Deliberately unstable to mirror reality; the
    // classifier ignores it in favour of pixel dimensions.
    const ad_type = this.flakyFormat
      ? AD_TYPE_ENUM[Math.floor(Math.random() * AD_TYPE_ENUM.length)]
      : 'banner';
    return { ad_type, theme: scene.theme, summary: scene.summary };
  }
}

module.exports = {
  AD_TYPE_ENUM,
  THEME_ENUM,
  VisionClient,
  MockVision,
  DEFAULT_SCENES,
};
