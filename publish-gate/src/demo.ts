/**
 * Narrated demo. Deterministic, offline, and finishes in well under a second.
 */

import {
  DATASET,
  SWEEP_BRAND,
  SWEEP_WEEK_INDEX,
  WEEKS,
  addDays,
  brandWindowDistinct,
  brandWindowPlacements,
  windowLaunchCount,
  type Dataset,
} from './data.js';
import { GOOD_EDITIONS, INCIDENT_EDITIONS, editionById, type Edition } from './editions.js';
import { OVERSTATEMENT_TOLERANCE, QUIET_WEEK_CEILING, type Finding } from './checks.js';
import { validate } from './gate.js';
import { AuditLog, dryRun, publish } from './publish.js';
import { FakeDigestGenerator, toEdition } from './fakeModel.js';

const RULE = '-'.repeat(78);
const log = new AuditLog();

let clockStep = 0;
/** Fixed clock. Every run prints the same timestamps. */
function nextTimestamp(): string {
  const minutes = clockStep++;
  const mm = String(9 + Math.floor(minutes / 60)).padStart(2, '0');
  const ss = String(minutes % 60).padStart(2, '0');
  return '2031-04-02T' + mm + ':' + ss + ':00Z';
}

function section(n: number, title: string): void {
  console.log('');
  console.log(RULE);
  console.log(' ' + n + '. ' + title);
  console.log(RULE);
}

function wrap(text: string, indent: string, width = 92): string {
  const words = text.split(' ');
  const lines: string[] = [];
  let line = '';
  for (const word of words) {
    if (line.length + word.length + 1 > width) {
      lines.push(line);
      line = word;
    } else {
      line = line.length === 0 ? word : line + ' ' + word;
    }
  }
  if (line.length > 0) lines.push(line);
  return lines.map((l, i) => (i === 0 ? l : indent + l)).join('\n');
}

function field(label: string, value: string): void {
  const pad = label.padEnd(12, ' ');
  console.log('     ' + pad + ' ' + wrap(value, ' '.repeat(18)));
}

function printFindings(findings: readonly Finding[]): void {
  if (findings.length === 0) {
    console.log('   no findings');
    return;
  }
  for (const f of findings) {
    console.log('   [' + f.severity.toUpperCase().padEnd(5) + '] ' + f.check);
    field('sentence', '"' + f.sentence + '"');
    field('claimed', f.claimed);
    field('recomputed', f.recomputed);
    field('basis', f.basis);
    field('why', f.detail);
    console.log('');
  }
}

function printCopy(edition: Edition): void {
  console.log('   copy:');
  console.log('     ' + wrap(edition.copy, '     ', 88));
}

function verdict(edition: Edition): void {
  const result = validate(edition, DATASET);
  console.log(
    '   verdict: ' +
      (result.decision === 'pass' ? 'PASS' : 'BLOCK') +
      '   claims checked: ' +
      result.claims.length +
      '   blocking: ' +
      result.blocking.length +
      '   warnings: ' +
      result.warnings.length,
  );
  console.log('');
  printFindings(result.findings);
}

console.log('');
console.log('PUBLISH GATE');
console.log('A pre-publish validation gate for machine-generated editorial copy.');

// ---------------------------------------------------------------------------
section(1, 'The dataset');
const week9 = WEEKS[SWEEP_WEEK_INDEX]!;
console.log('   rows                : ' + DATASET.listings.length);
console.log(
  '   distinct listings   : ' + new Set(DATASET.listings.map((r) => r.listing_id)).size,
);
console.log('   windows             : ' + WEEKS.length + ' weekly windows, ' + WEEKS[0]!.start + ' to ' + WEEKS[WEEKS.length - 1]!.end);
console.log('   generated from a fixed seed, so every run sees the same data.');

// ---------------------------------------------------------------------------
section(2, 'The generator writes this week');
const generator = new FakeDigestGenerator();
const request = {
  window: WEEKS[10]!,
  leadBrand: 'Everline' as const,
  secondBrand: 'Cirrus' as const,
  writtenOn: addDays(WEEKS[10]!.end, 1),
};
const generated = generator.generate(request);
const liveEdition = toEdition('LIVE-W11', request, generated);
printCopy(liveEdition);
console.log('');
console.log('   the generator also reports its own numbers:');
console.log('     ' + JSON.stringify(generated.claimedNumbers));
console.log(
  '   the gate does not read that field. Every figure below is recomputed from the dataset.',
);

// ---------------------------------------------------------------------------
section(3, "Dry run: what the editor's panel shows");
const preview = dryRun(liveEdition, DATASET);
console.log('   decision: ' + preview.decision.toUpperCase());
console.log('   claims extracted:');
for (const claim of preview.claims) {
  const extra =
    claim.kind === 'brand_count'
      ? ' ' + claim.brand + ' = ' + claim.value + ' (' + claim.basis + ')'
      : claim.kind === 'named_market'
        ? ' ' + claim.brand + ' in ' + claim.market
        : claim.kind === 'window_items'
          ? ' ' + claim.listingIds.join(', ')
          : '';
  console.log('     - ' + claim.kind.padEnd(13) + extra);
}
console.log('');
printFindings(preview.findings);
console.log(
  '   one sentence is not checked at all: "The category keeps drifting towards smaller pack',
);
console.log(
  '   sizes, which buyers appear to reward." Nothing in the data settles it, so the gate says',
);
console.log('   nothing about it. The gate checks facts, not judgement.');

// ---------------------------------------------------------------------------
section(4, 'Publish');
const published = publish(liveEdition, DATASET, { actor: 'editor.rowe', at: nextTimestamp() }, log);
console.log('   status  : ' + published.status);
console.log('   message : ' + published.message);
console.log('   audit   : #' + published.audit.seq + ' ' + published.audit.action);
console.log('   the panel and this path called the same validate(). They cannot disagree.');

// ---------------------------------------------------------------------------
section(5, 'Asymmetric tolerance: an old edition that under-claims');
const understated = editionById('GOOD-UNDERSTATED');
console.log('   ' + wrap(understated.note, '   '));
console.log('');
printCopy(understated);
console.log('');
verdict(understated);
console.log(
  '   ' +
    wrap(
      'Counts only grow as collection catches up, so a figure below the recomputed one is the normal state of every archived edition. Under-claiming never blocks. Only an over-claim beyond ' +
        Math.round(OVERSTATEMENT_TOLERANCE * 100) +
        ' per cent does.',
      '   ',
    ),
);
const understatedClaim = Number(/added (\d+) new listings/.exec(understated.copy)?.[1] ?? 0);
const understatedTruth = brandWindowDistinct(DATASET, 'Everline', understated.window);
console.log(
  '   ' +
    wrap(
      'Note the size of the gap: ' +
        (understatedTruth - understatedClaim) +
        ' below the recomputed ' +
        understatedTruth +
        ' passes without comment, while the same ' +
        (understatedTruth - understatedClaim) +
        ' above it would block. The tolerance is not a band around the truth, it is a ceiling.',
      '   ',
    ),
);

// ---------------------------------------------------------------------------
section(6, 'Incident: a quiet week that was not quiet');
const incidentQuiet = editionById('INCIDENT-QUIET');
printCopy(incidentQuiet);
console.log('');
console.log(
  '   true launches in ' +
    incidentQuiet.window.id +
    ': ' +
    windowLaunchCount(DATASET, incidentQuiet.window) +
    ' (ceiling for a quiet week: ' +
    QUIET_WEEK_CEILING +
    ')',
);
console.log('');
verdict(incidentQuiet);
const refused = publish(
  incidentQuiet,
  DATASET,
  { actor: 'scheduler', at: nextTimestamp() },
  log,
);
console.log('   publish attempt: ' + refused.status + ' (' + refused.message + ')');
console.log('   the refusal is in the audit trail as well, at #' + refused.audit.seq + '.');

// ---------------------------------------------------------------------------
section(7, 'Incident: an inflated count');
const incidentCount = editionById('INCIDENT-COUNT');
printCopy(incidentCount);
console.log('');
verdict(incidentCount);

// ---------------------------------------------------------------------------
section(8, 'Distinct listings versus summed market groups');
console.log(
  '   ' +
    SWEEP_BRAND +
    ', ' +
    week9.id +
    ': COUNT(DISTINCT listing_id) brand-wide      = ' +
    brandWindowDistinct(DATASET, SWEEP_BRAND, week9),
);
console.log(
  '   ' +
    SWEEP_BRAND +
    ', ' +
    week9.id +
    ': distinct per brand+market group, summed    = ' +
    brandWindowPlacements(DATASET, SWEEP_BRAND, week9),
);
console.log('   Both figures are real. They answer different questions.');
console.log('');
console.log('   (a) copy that quotes the market-level figure and says so:');
const goodPlacements = editionById('GOOD-PLACEMENTS');
printCopy(goodPlacements);
console.log('');
verdict(goodPlacements);
console.log('   (b) the same number written as a count of listings:');
const badPlacements = editionById('INCIDENT-PLACEMENTS');
printCopy(badPlacements);
console.log('');
verdict(badPlacements);

// ---------------------------------------------------------------------------
section(9, 'Incident: items cited from outside the window');
const incidentWindow = editionById('INCIDENT-WINDOW');
printCopy(incidentWindow);
console.log('   cited: ' + incidentWindow.citedListingIds.join(', '));
console.log('');
verdict(incidentWindow);

// ---------------------------------------------------------------------------
section(10, 'Warning tier: a market named with nothing behind it');
const incidentMarket = editionById('INCIDENT-MARKET');
printCopy(incidentMarket);
console.log('');
verdict(incidentMarket);
const warnOutcome = publish(
  incidentMarket,
  DATASET,
  { actor: 'editor.rowe', at: nextTimestamp() },
  log,
);
console.log('   status: ' + warnOutcome.status + ' (' + warnOutcome.message + ')');
console.log(
  '   ' +
    wrap(
      'The weakest signal gets the weakest response. A market named as colour is the least reliable claim in the copy, and a weak signal that stops a publish is a signal that gets overridden on reflex until nobody reads any of them.',
      '   ',
    ),
);

// ---------------------------------------------------------------------------
section(11, 'Override, with a reason that is written down');
const shortReason = publish(
  badPlacements,
  DATASET,
  { actor: 'editor.rowe', at: nextTimestamp(), override: { reason: 'fine' } },
  log,
);
console.log('   attempt 1 reason "fine"');
console.log('     -> ' + shortReason.status + ': ' + shortReason.message);
const goodReason = publish(
  badPlacements,
  DATASET,
  {
    actor: 'editor.rowe',
    at: nextTimestamp(),
    override: {
      reason: 'Sweep confirmed with the category team, sentence reworded to say placements.',
    },
  },
  log,
);
console.log('   attempt 2 reason given in full');
console.log('     -> ' + goodReason.status + ': ' + goodReason.message);
console.log('     -> audit #' + goodReason.audit.seq + ' records actor, time, reason and findings');

// ---------------------------------------------------------------------------
section(12, 'Fail open: the gate itself breaks');
const brokenDataset = Object.defineProperty({}, 'listings', {
  enumerable: true,
  get(): never {
    throw new Error('listing store unavailable');
  },
}) as Dataset;
const failOpen = publish(
  liveEdition,
  brokenDataset,
  { actor: 'scheduler', at: nextTimestamp() },
  log,
);
console.log('   status    : ' + failOpen.status);
console.log('   published : ' + failOpen.published);
console.log('   message   : ' + failOpen.message);
console.log(
  '   ' +
    wrap(
      'A validator with a bug in it must not become an outage. The edition goes out, the failure lands in the audit trail, and somebody fixes the gate. A gate that can stop the presses gets switched off the first time it does.',
      '   ',
    ),
);

// ---------------------------------------------------------------------------
section(13, 'The audit trail');
for (const entry of log.list()) {
  console.log(
    '   #' +
      String(entry.seq).padEnd(3) +
      entry.at +
      '  ' +
      entry.actor.padEnd(12) +
      entry.action.padEnd(18) +
      entry.editionId.padEnd(20) +
      entry.fingerprint,
  );
  console.log('        ' + wrap(entry.detail, '        '));
  if (entry.overrideReason !== null) {
    console.log('        reason: ' + entry.overrideReason);
  }
}
console.log('');
console.log(
  '   chain check: ' +
    (log.firstTamperedSeq() === null ? 'intact' : 'BROKEN at #' + log.firstTamperedSeq()),
);

// ---------------------------------------------------------------------------
section(14, 'The two proofs');
let blocked = 0;
for (const edition of GOOD_EDITIONS) {
  if (validate(edition, DATASET).decision === 'block') blocked++;
}
let caught = 0;
for (const edition of INCIDENT_EDITIONS) {
  if (validate(edition, DATASET).findings.length > 0) caught++;
}
console.log(
  '   backtest        : ' +
    GOOD_EDITIONS.length +
    ' known-good editions, ' +
    blocked +
    ' blocked (required: 0)',
);
console.log(
  '   negative control: ' +
    INCIDENT_EDITIONS.length +
    ' reconstructed incidents, ' +
    caught +
    ' caught (required: ' +
    INCIDENT_EDITIONS.length +
    ')',
);
console.log(
  '   ' +
    wrap(
      'The backtest on its own proves nothing: a validator that returns "pass" unconditionally scores full marks on it. The negative control is what makes the backtest mean anything. Run both with npm test.',
      '   ',
    ),
);
console.log('');
