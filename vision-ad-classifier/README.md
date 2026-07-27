[← Showreel](..)

# 🖼️ Vision Ad Classifier

![AI & agents](https://img.shields.io/badge/AI_%26_agents-8b5cf6) ![Node.js](https://img.shields.io/badge/Node.js-339933?logo=nodedotjs&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

Multimodal classification of ad creatives that combines a **deterministic**
signal with a **probabilistic** one, and is deliberate about which is allowed to
decide what.

Given an ad creative (an image plus its pixel dimensions), it produces:

```json
{
  "ad_type": "banner",          // FORMAT  - decided by pixel dimensions (deterministic)
  "theme": "promotion",         // CONTENT - decided by a vision model (probabilistic)
  "summary": "Limited-time seasonal sale: \"Save up to 30% this week only\".",
  "format_source": "dimensions",
  "vision_ad_type_guess": "search",  // what the model *said* the format was (ignored)
  "confidence": "dimensions+vision"
}
```

It runs fully offline with no API key and no cloud, using a mock vision client.
Swapping in a real multimodal model (Gemini Vision, GPT-4o, ...) is a
one-method change.

## The interesting part

The star idea is **knowing where NOT to trust the model.**

A vision model is great at reading what an ad *says* - its headline, offer,
theme, and a one-line summary. It is surprisingly bad at reliably naming the
ad's *format*. The same creative would come back as a "display banner" on one
run and a "search-ad screenshot" on the next. That non-determinism churned
downstream data every time the pipeline re-ran.

But format does not need a model at all. **Pixels do not lie.** An ad's format
is essentially encoded in its dimensions:

- An exact match against the **IAB standard banner-size table** (300x250,
  728x90, 160x600, ...) is a definitive banner.
- A 16:9 or 9:16 aspect ratio above a size threshold is a video.
- A mid-width image (roughly 500-1200 px) that is not a standard banner size is
  a search-ad screenshot (height varies with stacked sitelinks, so width is the
  tell).
- A small near-square is a logo / wordmark.

So the design splits the job cleanly:

| Signal | Decided by | Property |
|---|---|---|
| **FORMAT** (`ad_type`) | pixel dimensions vs. the IAB table | deterministic, reproducible |
| **CONTENT** (`theme`, `summary`) | the vision model | probabilistic, validated against an allowlist |

The vision client is even *allowed* to return its own format guess. The
classifier reads it, then throws it away in favour of the pixel verdict, keeping
only `theme` and `summary`. The demo prints the model's discarded guess next to
the pixel verdict so you can watch the guess flip-flop between runs while the
format label stays rock steady.

Three more production-hardening details are preserved:

- **Retry with exponential backoff + jitter** around the model call. Transient
  429 / 5xx responses are retried (base 2s, factor 3 gives ~2s, 6s, 18s, with
  +/-25% jitter so parallel workers do not retry in lockstep). See
  `withRetry` in `src/classifier.js`.
- **Bounded-concurrency worker pool** (`src/workerPool.js`) so a large batch of
  creatives is classified in parallel without opening an unbounded number of
  simultaneous requests, which is the fast path to getting rate-limited.
- **Structured output + allowlist validation.** A real model is asked for JSON
  (`responseMimeType: "application/json"`), and every returned field is checked
  against a hard enum (`ad_type`, `theme`) before it is trusted. Off-list values
  are discarded, not stored.

## Layout

```
src/
  dimensionClassifier.js  IAB size table + pure, deterministic format classifier
  visionClient.js         VisionClient interface + offline MockVision implementation
  classifier.js           combines the two; retry/backoff + enum validation
  workerPool.js           generic bounded-concurrency pool
  demo.js                 runs synthetic ads through the pipeline, offline
test/
  dimensionClassifier.test.js
```

## Run it

Requires Node 18+ (uses only built-ins - no dependencies to install).

```bash
node src/demo.js
# or
npm run demo
```

You will see each synthetic ad classified, the same batch run a second time, a
stability report proving the pixel-decided format never changes while the
model's guess does, and a retry/backoff demonstration.

Run the unit tests for the deterministic classifier:

```bash
npm test
```

## Plugging in a real vision model

Implement the one-method `VisionClient` interface. Anything that can turn image
bytes into `{ ad_type, theme, summary }` works:

```js
const { VisionClient } = require('./src/visionClient');

class RealVision extends VisionClient {
  constructor() {
    super();
    // No literal fallback for the credential: refuse to start without it.
    this.apiKey = process.env.GEMINI_API_KEY;
    if (!this.apiKey) throw new Error('GEMINI_API_KEY is not set');
  }

  async classify(imageBytes) {
    // 1) call your model with the image + a prompt that requests JSON
    // 2) parse the structured response
    // 3) return { ad_type, theme, summary }
    // On a 429/5xx, throw an error with `.status` set so withRetry backs off.
  }
}
```

Then feed it to the same classifier - the deterministic format logic, retry
wrapper, enum validation, and worker pool are all model-agnostic:

```js
const { classifyMany } = require('./src/classifier');
const results = await classifyMany(ads, new RealVision(), { concurrency: 5 });
```

## What was stubbed

This is a standalone extract of a module from a larger private pipeline. Two
things are stubbed so it runs anywhere, offline:

- **Real vision model -> `MockVision`.** The production module called a hosted
  multimodal model over HTTP. Here `MockVision` returns canned structured output
  behind the `VisionClient` interface. It also simulates two real behaviours on
  purpose: a randomised (flaky) format guess, and optional transient 429 errors
  so the retry/backoff path can be demonstrated.
- **Real creative images -> synthetic dimension tuples + placeholder bytes.**
  The demo does not need real images. Each "ad" is a `{ width, height,
  imageBytes }` tuple; the placeholder bytes are a tiny JSON descriptor the mock
  reads to pick canned content. In production, width and height would be read
  from the image bytes (any image-size library) or supplied as creative
  metadata, and `imageBytes` would be the actual PNG / JPEG.

Any deployment identifiers (GCP project, buckets, credentials) from the original
have been removed; a real deployment would supply its own via environment
variables (for example `process.env.GEMINI_API_KEY`, project `my-gcp-project`).
"Google Ads Transparency" and "IAB" are generic industry terms.

---

MIT · Part of [Showreel](..), twelve standalone engineering projects.
