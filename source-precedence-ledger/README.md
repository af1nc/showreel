[← Showreel](..)

# ⚖️ Source Precedence Ledger

![Data engineering](https://img.shields.io/badge/Data_engineering-0ea5e9) ![Python](https://img.shields.io/badge/Python-3776ab?logo=python&logoColor=white) ![stdlib only](https://img.shields.io/badge/stdlib-only-2ea44f) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

Three systems report the cost of the same work, they disagree, and one figure per
line has to be published and defended. This resolves the disagreement into a
single book: precedence per category, a sanity bound that escalates an implausible
flip instead of taking it, human overrides that always win and are always recorded,
and a per line audit trail good enough to defend any published number on its own.

## Try it

```bash
python main.py --demo
```

There is no install step. Python 3 and the standard library, no packages, no
network, nothing to configure. It runs in about a second and it is deterministic:
`Decimal` throughout, no floats, no wall clock, no randomness, so two runs produce
byte identical output.

```bash
python main.py --resolve           # build and print the book
python main.py --drift             # diff against the previously published book
python main.py --audit WO-4471     # the full trail behind one figure
```

## The story it came from

Three systems each held a version of what a piece of work cost: the plan, the
contractor invoice, and the operational tracker. They disagreed on most lines and
none of them was wrong, exactly. The plan was an intention, the invoice was what
was billed, and the tracker measured what it could see. Somebody still had to
publish one number per line, sign it, and answer questions about it weeks later.

The naive version of this is a chain of `COALESCE` calls. It produces a plausible
table and it is indefensible: nobody can say why a given figure won, a single bad
export slides straight through, and the total silently changes when a rule moves.
Everything below exists because of a specific way that went wrong.

## The interesting part

- **Keys never match cleanly, so normalise before you compare.** The same job
  arrives as `WO-4471`, `wo4471` and `WO 4471 (rev2)`. Compared literally that is
  three jobs and three published figures. `keys.py` normalises to alphanumeric
  lowercase and strips a *spelled out* revision suffix (`rev2`, `revision3`, `v4`).

- **Then guard the merge, because the aggressive rule is worse than the problem.**
  A rule that also strips a trailing letter joins the last stragglers and destroys
  `WO-4471-B`, a different job at the same site. That rule is kept in the codebase
  and never used to key anything: `find_collisions` runs it deliberately and
  reports what it would have merged, with the attribute that proves the jobs are
  different. The demo prices it: 2,480.00 that would have become one more losing
  candidate on another line and never been published at all.

- **Admit on value, not on label.** A line earns its place in the book by carrying
  an amount, never because a status field reads the right way. One fixture is
  marked `cancelled` by the contractor and carries real invoiced cost, and it is
  the only record of that job anywhere. A label based filter loses the whole line.
  A status field is another team's workflow state, maintained on their schedule,
  and marking an order cancelled after invoicing it does not refund the money. The
  only thing that fails admission is a genuine zero, and the fixtures contain one
  of those too so the distinction is tested rather than asserted.

- **Precedence per category, expressed as data.** The tracker is authoritative
  where it measures the work directly, the invoice is authoritative for
  subcontracted work where the tracker only logs a stub, and the plan is never
  authoritative, only ever the fallback when nobody reported the job. That is four
  different orderings, and as nested conditionals it becomes unreadable and
  unauditable. `rules.py` is a table: category, scope, ordering, bound, and the
  reason in words. Somebody who does not read Python can still check the policy.

- **A sanity bound on every precedence flip. This is the most important judgement
  in the project.** Precedence says source A beats source B. It does not say by how
  much. When A is more than 2x B, taking A silently is exactly how one bad export
  becomes a published number, and precedence is the mechanism that launders it:
  the rule fired, so the figure looks principled. Beyond the bound the line does
  **not** auto resolve. It is escalated to a human decision queue carrying both
  figures, the gap, and the rule that would have fired. An escalated line publishes
  no figure at all and contributes nothing to the total, so the absence is visible
  rather than being papered over with a fallback.

  **The fix for a wrong escalation is a named exception, never a lower bound.**
  When a flip is genuinely correct (the contractor invoiced a deposit, so the
  measured figure legitimately dwarfs it) that line gets a `BoundException`
  carrying who granted it, when, and why, and the exception is scoped to that one
  line. Lowering the bound to make the warning go away re-admits every bad export
  in the file at once, which is the original bug with extra steps.

- **A manual override layer that always wins and is always recorded.** A human
  ruling beats every rule, carries who ruled, when and why, and appears in the
  trail as an override rather than as a resolution. The rule outcome is still
  computed and still written underneath it, so the reader can see what the machine
  would have done and what the person did instead. A line somebody has already
  ruled on does not sit in the decision queue as though nobody had looked at it.

- **One owner per figure, proved.** The book is not finished when it is built, it
  is finished when it has been shown to partition its inputs: every input row has
  exactly one disposition (winner, suppressed, or rejected with a reason), every
  admitted line is claimed exactly once, the book invents no line no source
  reported, and the published total is the sum of the winning claims and nothing
  else. Six invariants, asserted rather than hoped for. `PartitionError` refuses
  the book. `tests/test_partition.py` feeds in an overlapping policy (the realistic
  version: someone adds a site carve out and leaves the general rule in place), and
  checks both that the assertion trips and that the broken book's total really did
  inflate, because the failure mode is a table that looks entirely plausible.

- **A drift check, and zero movement is a real result.** `--drift` re-resolves and
  diffs against the previously published book, reporting every line whose figure,
  winning source or status changed, with the reason drawn from that line's trail.
  A report with no movements and a report that never ran are different outcomes,
  render as visibly different text and exit with different codes, so "no drift"
  can never be a missing input file in disguise.

- **An audit trail per line, as the deliverable.** Which raw spellings joined, what
  each source reported, which rule fired and why it is ordered that way, the gap
  against the runner up, whether the bound held, any exception or ruling, the
  outcome, and every suppressed figure with the reason it lost. The test it has to
  pass is that somebody who was not in the room can defend any single number.

## What it does not do

- **No database, no service, no UI.** It reads five small CSVs and prints. The
  policy, the overrides and the published book are files; wiring them to real
  storage is deliberately left out.
- **The fixtures are synthetic and tiny.** Nine lines, chosen so that every case in
  this README appears exactly once and can be read in full. It is not a benchmark.
- **Resolution is per line, never across lines.** It will not notice that two work
  orders are halves of the same job, or that a total is right while its split is
  wrong. Those need a different check.
- **The bound is a ratio, which is the crude version.** A 2x rule is harsh on very
  small figures and lenient on very large ones. A production version would want an
  absolute floor underneath it so a 40.00 line against a 15.00 line does not
  occupy a person for ten minutes.
- **Overrides never expire.** A ruling made against one set of inputs still wins
  after those inputs change. The drift report will show the line moving, but
  nothing forces the ruling to be revisited.
- **The escalation queue is a printed table.** Routing, ownership, chasing and
  service levels are somebody else's problem here.

---

MIT · Part of [Showreel](..), a set of standalone engineering projects.
