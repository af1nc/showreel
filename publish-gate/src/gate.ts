/**
 * The gate. One validate(), no variants.
 *
 * Both callers in publish.ts route through this function, because the failure
 * that matters most is not a missed defect: it is an editor's preview panel
 * showing green while the enforcing path says red. Two implementations drift
 * within a month. One implementation cannot.
 *
 * validate() is pure: same edition plus same dataset gives the same result,
 * with no clock, no randomness and no input beyond its two arguments.
 */

import { extractClaims, type Claim, type ClaimSource } from './claims.js';
import { CHECKS, type Finding } from './checks.js';
import type { Dataset, Window } from './data.js';

export interface ValidatableEdition extends ClaimSource {
  id: string;
  window: Window;
}

export interface GateResult {
  editionId: string;
  window: Window;
  claims: Claim[];
  findings: Finding[];
  blocking: Finding[];
  warnings: Finding[];
  decision: 'pass' | 'block';
}

export function validate(edition: ValidatableEdition, dataset: Dataset): GateResult {
  const claims = extractClaims(edition);
  const ctx = { dataset, window: edition.window };

  const findings: Finding[] = [];
  for (const check of CHECKS) {
    for (const claim of claims) {
      findings.push(...check.run(claim, ctx));
    }
  }

  const blocking = findings.filter((f) => f.severity === 'block');
  const warnings = findings.filter((f) => f.severity === 'warn');

  return {
    editionId: edition.id,
    window: edition.window,
    claims,
    findings,
    blocking,
    warnings,
    decision: blocking.length > 0 ? 'block' : 'pass',
  };
}

export type Validator = typeof validate;
