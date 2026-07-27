/**
 * Bayesian A/B Testing Engine
 * ---------------------------
 * A dependency-free, from-first-principles Bayesian analyzer for two-arm
 * conversion-rate (Beta-Binomial) experiments.
 *
 * Everything below is implemented by hand: the special functions (log-Gamma,
 * log-Beta), the random-variate generators (Marsaglia-Tsang Gamma, Box-Muller
 * normal, Gamma-ratio Beta), and the Monte-Carlo decision statistics
 * (P(B > A), expected lift with a credible interval, and expected loss).
 *
 * There is no statistics library and no I/O here. Feed it two arms, each as a
 * plain (trials, conversions) integer pair, and it returns the posterior
 * comparison and a ship/hold decision.
 */

// ─── Configuration ───────────────────────────────────────────────────────────

/** Default number of Monte-Carlo draws used for every posterior statistic. */
export const DEFAULT_NUM_SAMPLES = 100_000;

// ─── Special Functions ───────────────────────────────────────────────────────

/**
 * Natural log of the Gamma function via the Lanczos approximation.
 *
 * The Beta PDF normalising constant B(a, b) blows up numerically for large
 * a, b if computed directly from factorials, so we work in log space. The
 * reflection formula extends the approximation to z < 0.5.
 */
export function logGamma(z: number): number {
  if (z < 0.5) {
    // Reflection: Gamma(z)*Gamma(1-z) = pi / sin(pi*z)
    return Math.log(Math.PI / Math.sin(Math.PI * z)) - logGamma(1 - z);
  }
  z -= 1;
  const g = 7;
  const c = [
    0.99999999999980993,
    676.5203681218851,
    -1259.1392167224028,
    771.32342877765313,
    -176.61502916214059,
    12.507343278686905,
    -0.13857109526572012,
    9.9843695780195716e-6,
    1.5056327351493116e-7,
  ];
  let x = c[0];
  for (let i = 1; i < g + 2; i++) {
    x += c[i] / (z + i);
  }
  const t = z + g + 0.5;
  return 0.5 * Math.log(2 * Math.PI) + (z + 0.5) * Math.log(t) - t + Math.log(x);
}

/**
 * Natural log of the Beta function: B(a, b) = Gamma(a)*Gamma(b)/Gamma(a+b).
 */
export function logBeta(a: number, b: number): number {
  return logGamma(a) + logGamma(b) - logGamma(a + b);
}

// ─── Random Variate Generators ───────────────────────────────────────────────

/**
 * Standard normal variate via the Box-Muller transform.
 */
export function normalRandom(): number {
  const u1 = Math.random();
  const u2 = Math.random();
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

/**
 * Gamma(shape, scale = 1) variate using Marsaglia and Tsang's rejection method.
 *
 * The method is exact and highly efficient for shape >= 1. For shape < 1 we
 * use the standard boost identity Gamma(a) = Gamma(a + 1) * U^(1/a).
 */
export function gammaRandom(shape: number): number {
  if (shape < 1) {
    return gammaRandom(shape + 1) * Math.pow(Math.random(), 1 / shape);
  }
  const d = shape - 1 / 3;
  const c = 1 / Math.sqrt(9 * d);
  while (true) {
    let x: number;
    let v: number;
    do {
      x = normalRandom();
      v = 1 + c * x;
    } while (v <= 0);
    v = v * v * v;
    const u = Math.random();
    // Squeeze step (cheap accept) then the exact log acceptance test.
    if (u < 1 - 0.0331 * (x * x) * (x * x)) return d * v;
    if (Math.log(u) < 0.5 * x * x + d * (1 - v + Math.log(v))) return d * v;
  }
}

/**
 * Beta(alpha, beta) variate via the Gamma ratio:
 * if X ~ Gamma(alpha) and Y ~ Gamma(beta) then X / (X + Y) ~ Beta(alpha, beta).
 */
export function betaRandom(alpha: number, beta: number): number {
  const x = gammaRandom(alpha);
  const y = gammaRandom(beta);
  return x / (x + y);
}

/**
 * Analytic mean of Beta(alpha, beta).
 */
export function betaMean(alpha: number, beta: number): number {
  return alpha / (alpha + beta);
}

// ─── Monte-Carlo Decision Statistics ─────────────────────────────────────────

/**
 * P(B > A) by Monte-Carlo simulation, where A ~ Beta(a1, b1), B ~ Beta(a2, b2).
 * This is the probability that arm B's true conversion rate beats arm A's.
 */
export function probBGreaterA(
  a1: number,
  b1: number,
  a2: number,
  b2: number,
  numSamples: number = DEFAULT_NUM_SAMPLES,
): number {
  let count = 0;
  for (let i = 0; i < numSamples; i++) {
    const sampleA = betaRandom(a1, b1);
    const sampleB = betaRandom(a2, b2);
    if (sampleB > sampleA) count++;
  }
  return count / numSamples;
}

/**
 * Posterior distribution of the relative lift (B - A) / A.
 * Returns the mean lift plus the lower/upper bounds of a symmetric credible
 * interval (default 90%, i.e. the 5th and 95th percentiles).
 */
export function computeLiftDistribution(
  a1: number,
  b1: number,
  a2: number,
  b2: number,
  numSamples: number = DEFAULT_NUM_SAMPLES,
  credibleMass: number = 0.9,
): { meanLift: number; ciLow: number; ciHigh: number } {
  const lifts: number[] = [];
  for (let i = 0; i < numSamples; i++) {
    const sampleA = betaRandom(a1, b1);
    const sampleB = betaRandom(a2, b2);
    if (sampleA > 0) {
      lifts.push((sampleB - sampleA) / sampleA);
    }
  }
  lifts.sort((a, b) => a - b);
  const n = lifts.length;
  const tail = (1 - credibleMass) / 2;
  return {
    meanLift: lifts.reduce((s, v) => s + v, 0) / n,
    ciLow: lifts[Math.floor(n * tail)],
    ciHigh: lifts[Math.floor(n * (1 - tail))],
  };
}

/**
 * Expected loss of shipping B: E[max(A - B, 0)] in conversion-rate terms.
 *
 * This is the decision-theoretic cost of choosing B when A might actually be
 * better. When it drops below a small tolerance the decision is "safe": even if
 * we picked the wrong arm, the expected regret is negligible.
 */
export function computeExpectedLoss(
  a1: number,
  b1: number,
  a2: number,
  b2: number,
  numSamples: number = DEFAULT_NUM_SAMPLES,
): number {
  let totalLoss = 0;
  for (let i = 0; i < numSamples; i++) {
    const sampleA = betaRandom(a1, b1);
    const sampleB = betaRandom(a2, b2);
    totalLoss += Math.max(sampleA - sampleB, 0);
  }
  return totalLoss / numSamples;
}

/**
 * Sampled points of a Beta(alpha, beta) posterior density, for plotting.
 *
 * The curve is centred on the distribution's mode and spans mode +/- 5 standard
 * deviations, clamped to [0, 1]. The PDF is evaluated in log space through
 * logBeta so it stays stable for large counts.
 */
export function betaDensityCurve(
  alpha: number,
  beta: number,
  numPoints: number = 200,
): Array<{ x: number; density: number }> {
  const mode =
    alpha > 1 && beta > 1 ? (alpha - 1) / (alpha + beta - 2) : alpha / (alpha + beta);
  const stdDev = Math.sqrt(
    (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1)),
  );

  const lo = Math.max(0, mode - 5 * stdDev);
  const hi = Math.min(1, mode + 5 * stdDev);
  const step = (hi - lo) / (numPoints - 1);

  const points: Array<{ x: number; density: number }> = [];
  const logBetaVal = logBeta(alpha, beta);

  for (let i = 0; i < numPoints; i++) {
    const x = lo + i * step;
    // Beta PDF: f(x) = x^(a-1) * (1-x)^(b-1) / B(a, b)
    let logDensity =
      (alpha - 1) * Math.log(x) + (beta - 1) * Math.log(1 - x) - logBetaVal;
    if (x <= 0 || x >= 1) logDensity = -Infinity;
    points.push({ x, density: Math.exp(logDensity) });
  }

  return points;
}

// ─── Two-Arm Beta-Binomial Analyzer ──────────────────────────────────────────

export type Verdict =
  | 'ship_variant'
  | 'ship_control'
  | 'keep_testing'
  | 'inconclusive';

export interface AbTestResult {
  /** Observed conversion rate of the control arm (A). */
  controlRate: number;
  /** Observed conversion rate of the variant arm (B). */
  variantRate: number;
  /** Posterior probability that the variant's true rate beats the control's. */
  probVariantBeatsControl: number;
  /** Posterior mean of the relative lift (B - A) / A. */
  expectedLift: number;
  /** Credible interval [low, high] for the relative lift. */
  liftCredibleInterval: [number, number];
  /** Credible mass used for the interval above (e.g. 0.9 for 90%). */
  credibleMass: number;
  /** Expected loss (in rate terms) of shipping the variant. */
  expectedLoss: number;
  /** Decision recommendation derived from P(variant beats control). */
  verdict: Verdict;
  /** Sampled posterior density of the control arm, for plotting. */
  posteriorControl: Array<{ x: number; density: number }>;
  /** Sampled posterior density of the variant arm, for plotting. */
  posteriorVariant: Array<{ x: number; density: number }>;
}

export interface AbTestOptions {
  /** Monte-Carlo draws per statistic. Default {@link DEFAULT_NUM_SAMPLES}. */
  numSamples?: number;
  /** Credible-interval mass for the lift. Default 0.9 (a 90% interval). */
  credibleMass?: number;
  /**
   * Conjugate Beta prior pseudo-counts (alpha, beta). Default [1, 1], the
   * uniform prior. Both arms share the same prior.
   */
  prior?: [number, number];
  /** Include the posterior density curves in the result. Default true. */
  includeDensityCurves?: boolean;
}

/**
 * Map P(variant beats control) to a decision.
 *
 * The thresholds encode a simple ship/hold rule: 95% confidence to ship,
 * 80%+ (or the symmetric losing side) to keep gathering data, and the middle
 * band is genuinely inconclusive.
 */
export function verdictFromProbability(prob: number): Verdict {
  if (prob >= 0.95) return 'ship_variant';
  if (prob >= 0.8) return 'keep_testing';
  if (prob <= 0.05) return 'ship_control';
  if (prob <= 0.2) return 'keep_testing';
  return 'inconclusive';
}

/**
 * Full Bayesian analysis of a two-arm conversion-rate experiment.
 *
 * Each arm is supplied as plain integers: how many trials (exposures) and how
 * many of them converted. Using a conjugate Beta(alpha, beta) prior, the
 * posterior for a Binomial rate is simply Beta(alpha + conversions,
 * beta + trials - conversions), so no MCMC is needed for the posteriors
 * themselves. We then draw from those posteriors to estimate the comparison
 * statistics that have no closed form (P(B > A), the lift interval, loss).
 *
 * @param controlTrials      Total exposures in the control arm (A).
 * @param controlConversions Conversions in the control arm (A).
 * @param variantTrials      Total exposures in the variant arm (B).
 * @param variantConversions Conversions in the variant arm (B).
 */
export function analyzeAbTest(
  controlTrials: number,
  controlConversions: number,
  variantTrials: number,
  variantConversions: number,
  options: AbTestOptions = {},
): AbTestResult {
  const numSamples = options.numSamples ?? DEFAULT_NUM_SAMPLES;
  const credibleMass = options.credibleMass ?? 0.9;
  const [priorA, priorB] = options.prior ?? [1, 1];
  const includeDensityCurves = options.includeDensityCurves ?? true;

  // Conjugate Beta-Binomial update: posterior = Beta(prior + successes,
  // prior + failures) for each arm.
  const a1 = priorA + controlConversions;
  const b1 = priorB + (controlTrials - controlConversions);
  const a2 = priorA + variantConversions;
  const b2 = priorB + (variantTrials - variantConversions);

  const prob = probBGreaterA(a1, b1, a2, b2, numSamples);
  const lift = computeLiftDistribution(a1, b1, a2, b2, numSamples, credibleMass);
  const loss = computeExpectedLoss(a1, b1, a2, b2, numSamples);

  return {
    controlRate: controlTrials > 0 ? controlConversions / controlTrials : 0,
    variantRate: variantTrials > 0 ? variantConversions / variantTrials : 0,
    probVariantBeatsControl: prob,
    expectedLift: lift.meanLift,
    liftCredibleInterval: [lift.ciLow, lift.ciHigh],
    credibleMass,
    expectedLoss: loss,
    verdict: verdictFromProbability(prob),
    posteriorControl: includeDensityCurves ? betaDensityCurve(a1, b1) : [],
    posteriorVariant: includeDensityCurves ? betaDensityCurve(a2, b2) : [],
  };
}

// ─── Sample-Size Estimator ───────────────────────────────────────────────────

export interface SampleSizeEstimate {
  /**
   * Estimated additional exposures (summed across both arms) still needed to
   * reach the target confidence. 0 if already there; -1 if the observed effect
   * is too small to be detectable.
   */
  additionalSamples: number;
  /** Current P(variant beats control) at the observed data. */
  currentConfidence: number;
}

/**
 * Estimate how many more samples are needed to reach a target confidence.
 *
 * If the experiment has already crossed the target (in either direction) it
 * returns 0. Otherwise it uses the observed effect size with the standard
 * Bayesian rule-of-thumb of ~16 / effect^2 samples per arm to project a
 * remaining budget. Returns -1 when the effect is effectively zero and no
 * realistic sample size would resolve it.
 *
 * @param controlRate  Observed control conversion rate.
 * @param variantRate  Observed variant conversion rate.
 * @param controlN     Control arm sample size so far.
 * @param variantN     Variant arm sample size so far.
 * @param targetConfidence Confidence threshold to reach (default 0.95).
 */
export function estimateAdditionalSamples(
  controlRate: number,
  variantRate: number,
  controlN: number,
  variantN: number,
  targetConfidence: number = 0.95,
  numSamples: number = DEFAULT_NUM_SAMPLES,
): SampleSizeEstimate {
  const a1 = 1 + Math.round(controlRate * controlN);
  const b1 = 1 + Math.round((1 - controlRate) * controlN);
  const a2 = 1 + Math.round(variantRate * variantN);
  const b2 = 1 + Math.round((1 - variantRate) * variantN);

  const currentConfidence = probBGreaterA(a1, b1, a2, b2, numSamples);

  if (
    currentConfidence >= targetConfidence ||
    currentConfidence <= 1 - targetConfidence
  ) {
    return { additionalSamples: 0, currentConfidence };
  }

  const effectSize = Math.abs(variantRate - controlRate);
  if (effectSize < 0.0001) {
    return { additionalSamples: -1, currentConfidence }; // no detectable effect
  }

  const currentN = controlN + variantN;
  // Rough Bayesian heuristic: ~16 / effect^2 exposures per arm.
  const targetPerArm = Math.ceil(16 / (effectSize * effectSize));
  const additionalSamples = Math.max(0, targetPerArm * 2 - currentN);

  return { additionalSamples, currentConfidence };
}
