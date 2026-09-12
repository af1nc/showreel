[← Showreel](..)

# 🚧 Publish Gate

![AI guardrails](https://img.shields.io/badge/AI_guardrails-e11d48) ![TypeScript](https://img.shields.io/badge/TypeScript-3178c6?logo=typescript&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

A language model writes a weekly digest summarising activity in a dataset. Before that
digest can reach a reader, every claim in it that is checkable against data is
**recomputed from the data**, and a blocking finding refuses the publish. The gate has one
implementation, an asymmetric tolerance, a recorded override, and it fails open.

It ships with the two proofs that decide whether a validator like this is worth having: a
**backtest** over known-good editions that must produce zero blocks, and a **negative
control** over reconstructed incidents that must catch every one.

## Try it

```bash
npm install && npm run demo
```

The demo runs offline and finishes in about a second. It narrates a full pass: the
generator writing an edition, the dry run an editor's panel would show, the publish, an
archived edition that under-claims and is waved through, four incident editions with the
recomputed figure printed beside the claimed one, an override being refused for a thin
reason and then accepted with a real one, the fail-open path when the validator itself
throws, and the audit trail that records all of it.

## The story it came from

Machine-written copy went out on a schedule to people who acted on it. Roughly one edition
in ten carried a number that the underlying data did not support: a total counted at the
wrong grain, a week described as quiet when it was not, an example held up as new that had
been live for a month. Each one was caught by a human eventually, and each one was caught
after it had been sent.

Every proposed fix was a rule about attention: read it more carefully, have a second person
check it, add a line to the checklist. Rules like that hold for about three weeks. What
holds is a mechanism that runs whether or not anyone is paying attention, and that does
something specific when it finds a problem. So the checks became code sitting in the
publish path, and the copy stopped going out over numbers the data could not support.

## The interesting part

**Recompute, do not trust.** The generator emits copy and reports its own numbers alongside
it. The gate never reads that field. Every figure in a claim is recomputed from the dataset
at check time. A generator that is confidently wrong reports a confidently wrong number,
so its own account of its output is worth nothing as evidence. The demo prints the reported
numbers next to the recomputed ones purely to show the gap.

**Tolerance is asymmetric, and this is the single hardest thing to get right.** Collection
is incremental: rows keep arriving for a window long after that window has closed. An
edition published three weeks ago quoted the figure that was true when it was written, and
the same window recomputed today is legitimately higher. So a claim that sits **under** the
recomputed figure must never block, at any distance. Only a claim that materially
**exceeds** it blocks, where material means more than 15 per cent over and more than three
in absolute terms. The tolerance is a ceiling, not a band around the truth. Reversing the
sign, or making it symmetric "to be safe", turns the entire archive red overnight and the
gate gets switched off. It is `overstates()` in `src/checks.ts`, six lines, and it is the
line that decides whether anyone keeps the thing.

**Claims are checked at the altitude the copy aggregates at.** The copy writes brand-wide
sentences that name a couple of markets as colour: "34 new listings across markets
including Portugal and Chile". The first version of this gate pulled the market out of the
same sentence and tested 34 against Portugal alone. Portugal alone was never going to be
34, so the gate blocked a large fraction of perfectly good editions in its first week and
lost most of its credibility before it had caught anything. Counts are now checked
brand-wide, always. The named markets are extracted as a separate, weaker claim.

**Distinct versus placement counting.** A listing that goes live in several markets is one
listing on several rows. `COUNT(DISTINCT listing_id)` brand-wide gives 478 for the demo's
sweep week; distinct-per-brand-and-market summed across groups gives 860. Both are real
figures answering different questions, and 860 published as a count of listings is the
original defect this project exists for. So both counts are implemented, the copy decides
which one applies (plain "new listings" means distinct, "listing placements" means the
summed figure), and every finding states the basis it was judged against rather than
leaving the editor to guess. When a claim happens to equal the summed figure exactly, the
finding says so, because that is almost always what went wrong.

**One implementation, two callers.** `validate()` in `src/gate.ts` exists once. The dry-run
endpoint an editor's panel calls and the enforcing publish path are the same code:
`publish()` literally calls `dryRun()`. This is structural rather than conventional,
because the failure that destroys trust fastest is not a missed defect, it is a preview
panel showing green while the gate says red. Two implementations of the same rules drift
within a month and nobody can tell which one is right.

**The gate fails open.** If `validate()` throws, the edition publishes and the failure is
written to the audit trail. A validator with a bug in it must not become a publishing
outage. A gate that can stop the presses gets switched off the first time it does, and then
nothing is checked at all. The demo forces this path by handing the gate a dataset whose
read throws.

**Override with a recorded reason.** A blocking finding can be overridden, but only with a
reason of at least ten characters, and the override is written to an append-only audit
trail with the actor, the timestamp, the reason and the exact findings that were overridden.
Entries are frozen and chained with a fingerprint over the previous entry, so a later edit
to history is detectable. An override is a new entry, never a change to the block it
overrode.

**Scope honesty.** The gate checks claims that are checkable against data. A sentence like
"the category keeps drifting towards smaller pack sizes, which buyers appear to reward" is
not checked and never will be, because nothing in the data settles it. A badly judged,
poorly argued or actively misleading sentence passes this gate cleanly. It catches
arithmetic and attribution against a known dataset, and that is all it catches. Anything
sold as broader than that is being oversold.

## The four checks

Each one is modelled on a failure shape that actually reached readers.

1. **Quiet-week claim.** Copy asserting there was little or no new activity, recomputed
   against the true launch count in the window. Blocking. The asymmetry applies here too:
   the sentence asserts an upper bound on activity, so only activity above the ceiling
   contradicts it.
2. **Count claim.** "N new listings from Beacon", recomputed brand-wide with the asymmetric
   tolerance applied. Blocking.
3. **Window claim.** Items cited as examples from the digest window must exist and must
   carry a launch date inside it. Blocking.
4. **Named-market claim.** A market named alongside a brand should have at least one
   listing for that brand in the window. **Warning, not blocking.** This is the weakest
   signal of the four: the market is named as colour, the sentence may mean presence rather
   than new activity, and per-row market attribution is the least reliable field held. A
   weak signal that stops a publish is a signal that gets overridden on reflex, and once
   people are overriding on reflex they stop reading the strong findings too. The weakest
   signal gets the weakest response so the strong ones keep their meaning.

## Running the proofs

```bash
npm test
```

**`test/backtest.test.ts`** runs the gate over twelve known-good historical editions.
Required result: zero blocks. It also asserts that each edition actually produced claims,
so the backtest cannot pass by checking nothing, and that the under-claiming archive case
really does sit materially below today's recomputed figure, so the asymmetry is genuinely
exercised rather than merely present.

**`test/negativeControl.test.ts`** runs the gate over five editions reconstructed from real
incidents, one per check plus the group-sum case. Required result: every one caught, with
the expected check and the expected severity.

**A backtest alone proves nothing.** A validator whose entire body is `return pass` scores
a flawless 100 per cent on the backtest: zero good editions blocked, which is exactly the
headline number. It is a measure of how little damage the gate does, not of whether it can
detect anything at all. The negative control is what gives the backtest its meaning, and it
is not optional. The last test in `negativeControl.test.ts` asserts this directly: it runs
an always-pass validator over both corpora and shows it sailing through one and catching
nothing whatsoever in the other, next to the real gate scoring 12/12 and 5/5.

## What was stubbed for the demo

- **The language model is faked.** `src/fakeModel.ts` implements a `DigestGenerator`
  interface with a deterministic offline stand-in: no network, no key, no account. A real
  client implements that one interface, and nothing downstream changes, because nothing
  downstream trusts what it returns.
- **The warehouse is a seeded in-memory dataset.** `src/data.ts` generates around 2,300
  rows from a fixed seed. Production read the same shapes out of a columnar store; the
  counting logic here is the same logic, written in TypeScript instead of SQL.
- **The domain is invented.** Five brands of home and kitchen goods across six markets.
  Every name, figure and edition in this repository is synthetic.
- **Time is injected.** Timestamps are passed in by the caller rather than read from a
  clock, so `npm run demo` prints identical output on every run.

---

MIT · Part of [Showreel](..).
