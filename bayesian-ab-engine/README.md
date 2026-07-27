[← Showreel](..)

# 🎲 Bayesian A/B Engine

![Data science & ML](https://img.shields.io/badge/Data_science_%26_ML-3b82f6) ![TypeScript](https://img.shields.io/badge/TypeScript-3178c6?logo=typescript&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

Bayesian A/B testing for two-arm conversion experiments, built from first
principles with **no statistics library**. You hand it two arms as plain
`(trials, conversions)` integers and it returns the full posterior comparison:
the probability the variant beats the control, the expected lift with a
credible interval, the expected loss of shipping the variant, and an estimate
of how many more samples you would need to reach a target confidence.

Frequentist A/B tests answer "is this difference statistically significant?".
This answers the questions a decision-maker actually asks:

- **P(B > A)** - how likely is it that the variant is genuinely better?
- **Expected lift + credible interval** - how much better, and how sure are we?
- **Expected loss** - if we ship the variant and we're wrong, how much do we
  expect to lose? When this is tiny, the decision is safe even if it's the
  "wrong" arm.

## The interesting part

Everything is implemented by hand, which is the point of the module.

- **Lanczos log-Gamma.** The Beta PDF's normalising constant `B(a, b)` is a
  ratio of Gamma functions that overflows for large counts. `logGamma` uses the
  Lanczos series (plus the reflection formula for `z < 0.5`) so the whole
  posterior density is evaluated stably in log space via `logBeta`.
- **Marsaglia-Tsang Gamma sampling.** To draw from a Beta posterior we use the
  identity `X / (X + Y) ~ Beta(a, b)` where `X ~ Gamma(a)`, `Y ~ Gamma(b)`. The
  Gamma variates come from Marsaglia and Tsang's rejection method - exact and
  fast for shape >= 1, with the `Gamma(a) = Gamma(a + 1) * U^(1/a)` boost for
  shape < 1. The normal variates it needs come from a hand-written Box-Muller
  transform. No RNG library beyond `Math.random()`.
- **Conjugate Beta-Binomial update.** With a `Beta(1, 1)` (uniform) prior, the
  posterior for a Binomial conversion rate is exactly
  `Beta(1 + conversions, 1 + failures)`. No MCMC is needed for the posteriors
  themselves - Monte Carlo is used only for the comparison statistics that have
  no closed form.
- **Expected-loss decision rule.** Instead of a p-value cutoff, the engine
  computes `E[max(A - B, 0)]`, the expected regret of shipping the variant. A
  verdict function turns `P(B > A)` into a plain recommendation
  (`ship_variant` / `ship_control` / `keep_testing` / `inconclusive`).

## Run it

```bash
npm install
npm run demo
```

The demo runs a synthetic experiment - control: 84/1000, variant: 103/1000 -
and prints P(B > A), the expected lift with its 90% credible interval, the
expected loss, and the estimated additional samples needed to reach 95%
confidence. Because it's Monte Carlo, figures wobble by a fraction of a percent
run to run; raise `numSamples` for tighter estimates.

Example output:

```
Bayesian A/B Test  -  control (A) vs variant (B)
────────────────────────────────────────────────────────
  Control (A):  84 / 1000  = 8.40%
  Variant (B):  103 / 1000  = 10.30%
────────────────────────────────────────────────────────
  P(B > A):                 92.xx%
  Expected lift (B vs A):   +2x.xx%
  90% credible interval:   [-x.xx%, +5x.xx%]
  Expected loss of shipping B: 0.0xxx pp
  Verdict:                  keep_testing
────────────────────────────────────────────────────────
  Estimated additional samples to reach 95% confidence: ...
```

## Use it as a library

```ts
import { analyzeAbTest, estimateAdditionalSamples } from './src/bayesianAB.js';

const result = analyzeAbTest(
  1000, 84,   // control: trials, conversions
  1000, 103,  // variant: trials, conversions
  { numSamples: 200_000, credibleMass: 0.9 },
);

console.log(result.probVariantBeatsControl); // P(B > A)
console.log(result.expectedLift);            // posterior mean relative lift
console.log(result.liftCredibleInterval);    // [low, high]
console.log(result.expectedLoss);            // expected regret of shipping B
console.log(result.verdict);                 // ship_variant | ship_control | ...
```

`analyzeAbTest` also returns `posteriorControl` / `posteriorVariant` - sampled
Beta density curves ready to plot. The lower-level primitives (`logGamma`,
`logBeta`, `gammaRandom`, `betaRandom`, `probBGreaterA`, `computeLiftDistribution`,
`computeExpectedLoss`, `betaDensityCurve`) are all exported too.

## What was stubbed

The original version of this analyzer pulled its two arms from a live
analytics/warehouse query - one arm per experiment variant, aggregated from
raw event data. That data source has been replaced entirely by plain integer
`(trials, conversions)` inputs so the module is standalone and runnable with no
credentials, no database, and no network access. The statistical engine is
unchanged; only the data-loading layer was removed. To wire it to a real
source, replace the integer literals in `src/demo.ts` with counts from your
own query and pass them straight into `analyzeAbTest`.

---

MIT · Part of [Showreel](..), twelve standalone engineering projects.
