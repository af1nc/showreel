/**
 * Demo: run the Bayesian A/B engine on synthetic conversion data.
 *
 * In a production setting the two (trials, conversions) pairs would come from a
 * data warehouse or analytics API. Here they are just plain integers so the
 * module runs anywhere with no external dependencies or credentials.
 */

import { analyzeAbTest, estimateAdditionalSamples } from './bayesianAB.js';

// ── Synthetic experiment ──────────────────────────────────────────────────
// Arm A (control): 1000 exposures, 84 conversions  -> 8.4%
// Arm B (variant): 1000 exposures, 103 conversions -> 10.3%
const controlTrials = 1000;
const controlConversions = 84;
const variantTrials = 1000;
const variantConversions = 103;

const pct = (x: number) => `${(x * 100).toFixed(2)}%`;
const signedPct = (x: number) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(2)}%`;

const result = analyzeAbTest(
  controlTrials,
  controlConversions,
  variantTrials,
  variantConversions,
);

const [ciLow, ciHigh] = result.liftCredibleInterval;
const ciLabel = `${Math.round(result.credibleMass * 100)}% credible interval`;

const samples = estimateAdditionalSamples(
  result.controlRate,
  result.variantRate,
  controlTrials,
  variantTrials,
  0.95,
);

console.log('Bayesian A/B Test  -  control (A) vs variant (B)');
console.log('─'.repeat(56));
console.log(
  `  Control (A):  ${controlConversions} / ${controlTrials}  = ${pct(result.controlRate)}`,
);
console.log(
  `  Variant (B):  ${variantConversions} / ${variantTrials}  = ${pct(result.variantRate)}`,
);
console.log('─'.repeat(56));
console.log(`  P(B > A):                 ${pct(result.probVariantBeatsControl)}`);
console.log(`  Expected lift (B vs A):   ${signedPct(result.expectedLift)}`);
console.log(
  `  ${ciLabel}:   [${signedPct(ciLow)}, ${signedPct(ciHigh)}]`,
);
console.log(
  `  Expected loss of shipping B: ${(result.expectedLoss * 100).toFixed(4)} pp`,
);
console.log(`  Verdict:                  ${result.verdict}`);
console.log('─'.repeat(56));

if (samples.additionalSamples === 0) {
  console.log(
    `  Already at 95% confidence (current ${pct(samples.currentConfidence)}).`,
  );
} else if (samples.additionalSamples < 0) {
  console.log('  Effect too small to detect - no realistic sample size resolves it.');
} else {
  console.log(
    `  Estimated additional samples to reach 95% confidence: ${samples.additionalSamples.toLocaleString()}`,
  );
  console.log(`  (current confidence ${pct(samples.currentConfidence)})`);
}
console.log('─'.repeat(56));
