/**
 * Proof two: the negative control.
 *
 * Every edition here is a reconstruction of a failure that actually reached
 * readers. The gate must catch all of them.
 *
 * This is the proof that gives the backtest its meaning. A validator whose
 * entire body is "return pass" scores 100 per cent on the backtest, so a green
 * backtest says nothing about whether the gate can detect anything at all. The
 * last test in this file demonstrates that directly: it runs an always-pass
 * validator through both corpora and shows it sailing through one and failing
 * the other completely.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { DATASET } from '../src/data.js';
import {
  GOOD_EDITIONS,
  INCIDENT_EDITIONS,
  INCIDENT_EXPECTATIONS,
  editionById,
} from '../src/editions.js';
import { validate, type GateResult, type ValidatableEdition } from '../src/gate.js';
import { AuditLog, publish } from '../src/publish.js';
import type { Dataset } from '../src/data.js';

test('every reconstructed incident is caught, with the expected check and severity', () => {
  for (const expectation of INCIDENT_EXPECTATIONS) {
    const edition = editionById(expectation.editionId);
    const result = validate(edition, DATASET);
    const hit = result.findings.find(
      (f) => f.check === expectation.check && f.severity === expectation.severity,
    );
    assert.ok(
      hit,
      expectation.editionId +
        ' (' +
        expectation.label +
        ') produced no ' +
        expectation.severity +
        ' finding from the ' +
        expectation.check +
        ' check. Findings: ' +
        JSON.stringify(result.findings.map((f) => f.check + '/' + f.severity)),
    );
  }
});

test('the corpus covers every incident edition', () => {
  assert.equal(INCIDENT_EXPECTATIONS.length, INCIDENT_EDITIONS.length);
});

test('blocking incidents are actually refused at the publish path', () => {
  const log = new AuditLog();
  for (const expectation of INCIDENT_EXPECTATIONS) {
    if (expectation.severity !== 'block') continue;
    const outcome = publish(
      editionById(expectation.editionId),
      DATASET,
      { actor: 'test', at: '2031-04-02T00:00:00Z' },
      log,
    );
    assert.equal(outcome.published, false, expectation.editionId + ' was allowed through');
    assert.equal(outcome.status, 'blocked');
  }
});

test('the named-market incident warns and still publishes', () => {
  const edition = editionById('INCIDENT-MARKET');
  const result = validate(edition, DATASET);
  assert.equal(result.decision, 'pass');
  assert.equal(result.warnings.length > 0, true);

  const log = new AuditLog();
  const outcome = publish(edition, DATASET, { actor: 'test', at: '2031-04-02T00:00:00Z' }, log);
  assert.equal(outcome.published, true);
});

test('the group-sum incident is judged against the distinct figure and names both', () => {
  const result = validate(editionById('INCIDENT-PLACEMENTS'), DATASET);
  const finding = result.blocking.find((f) => f.check === 'count');
  assert.ok(finding);
  assert.match(finding.claimed, /860/);
  assert.match(finding.recomputed, /478/);
  assert.match(finding.detail, /counts a listing once per market/);
});

test('an override needs a real reason and is written to the audit trail', () => {
  const log = new AuditLog();
  const edition = editionById('INCIDENT-COUNT');

  const refused = publish(
    edition,
    DATASET,
    { actor: 'test', at: '2031-04-02T00:01:00Z', override: { reason: 'ok' } },
    log,
  );
  assert.equal(refused.published, false);
  assert.equal(refused.status, 'override_rejected');

  const allowed = publish(
    edition,
    DATASET,
    {
      actor: 'test',
      at: '2031-04-02T00:02:00Z',
      override: { reason: 'Verified against the source feed by the category team.' },
    },
    log,
  );
  assert.equal(allowed.published, true);
  assert.equal(allowed.status, 'published_by_override');
  assert.equal(allowed.audit.overrideReason?.startsWith('Verified against'), true);
  assert.ok(allowed.audit.findings.length > 0);
  assert.equal(log.firstTamperedSeq(), null);
});

test('the gate fails open when it throws, and records it', () => {
  const broken = Object.defineProperty({}, 'listings', {
    enumerable: true,
    get(): never {
      throw new Error('listing store unavailable');
    },
  }) as Dataset;

  const log = new AuditLog();
  const outcome = publish(
    editionById('INCIDENT-COUNT'),
    broken,
    { actor: 'scheduler', at: '2031-04-02T00:03:00Z' },
    log,
  );
  assert.equal(outcome.published, true);
  assert.equal(outcome.status, 'published_gate_error');
  assert.equal(log.list()[0]?.action, 'gate_error');
});

/**
 * The point of the whole exercise, asserted rather than claimed.
 */
test('an always-pass validator scores perfectly on the backtest and catches nothing', () => {
  const alwaysPass = (edition: ValidatableEdition): GateResult => ({
    editionId: edition.id,
    window: edition.window,
    claims: [],
    findings: [],
    blocking: [],
    warnings: [],
    decision: 'pass',
  });

  const goodBlocked = GOOD_EDITIONS.filter((e) => alwaysPass(e).decision === 'block').length;
  const incidentsCaught = INCIDENT_EDITIONS.filter((e) => alwaysPass(e).findings.length > 0).length;

  assert.equal(goodBlocked, 0, 'the fake validator should look flawless on the backtest');
  assert.equal(incidentsCaught, 0, 'and should catch nothing at all');

  // The real gate, over the same two corpora.
  const realGoodBlocked = GOOD_EDITIONS.filter(
    (e) => validate(e, DATASET).decision === 'block',
  ).length;
  const realIncidentsCaught = INCIDENT_EDITIONS.filter(
    (e) => validate(e, DATASET).findings.length > 0,
  ).length;

  assert.equal(realGoodBlocked, 0);
  assert.equal(realIncidentsCaught, INCIDENT_EDITIONS.length);
});
