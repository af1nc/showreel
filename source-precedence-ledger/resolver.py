"""Loading, admission, precedence, the sanity bound, escalation and overrides.

The order of operations is the whole design and it is deliberate:

    load  ->  admit on value  ->  key  ->  apply precedence  ->  test the bound
          ->  escalate or resolve  ->  apply any human override on top

Every step records what it did to every row, because the audit trail is the
deliverable. A figure nobody can defend is not worth publishing.
"""

import csv
import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional, Sequence

from audit import AuditTrail
from keys import KeyedRow, canonical
from rules import Policy

MONEY = Decimal("0.01")

# source name -> (filename, code column, amount column, status column)
SOURCE_FILES = {
    "plan": ("plan.csv", "work_order", "approved_amount", "status"),
    "vendor": ("vendor.csv", "invoice_ref", "invoiced_amount", "invoice_status"),
    "system": ("system.csv", "job_code", "measured_cost", "job_state"),
}

# Rank used only where a tie has to break deterministically (picking the site
# and category labels for a line). It is not a precedence order.
STABLE_SOURCE_ORDER = ("system", "vendor", "plan")

WINNER = "WINNER"
SUPPRESSED = "SUPPRESSED"
REJECTED = "REJECTED"

RESOLVED = "RESOLVED"
OVERRIDDEN = "OVERRIDDEN"
ESCALATED = "ESCALATED"


def money(raw):
    """Parse a money column. Decimal throughout, never float: a book that does
    not add up to the penny is not a book.
    """
    try:
        return Decimal(str(raw).strip() or "0").quantize(MONEY)
    except InvalidOperation:
        return Decimal("0.00").quantize(MONEY)


@dataclass(frozen=True)
class Candidate:
    """One row from one source, after parsing and before any judgement."""

    source: str
    raw_code: str
    site: str
    category: str
    period: str
    amount: Decimal
    label: str

    @property
    def key(self):
        return canonical(self.raw_code)

    def as_keyed_row(self):
        return KeyedRow(self.source, self.raw_code, self.site, self.category)


@dataclass(frozen=True)
class Override:
    """A human ruling. Beats every rule, and is recorded as a ruling."""

    key: str
    raw_code: str
    amount: Decimal
    ruled_by: str
    ruled_on: str
    reason: str


@dataclass(frozen=True)
class Disposition:
    """What happened to one input row. Every row gets exactly one of these."""

    source: str
    raw_code: str
    key: str
    amount: Decimal
    kind: str
    reason: str


@dataclass(frozen=True)
class Escalation:
    """A line the bound refused to resolve, handed to a person with both figures."""

    key: str
    site: str
    category: str
    period: str
    rule_name: str
    contender: Candidate
    incumbent: Candidate
    ratio: Optional[Decimal]
    bound: Decimal


@dataclass
class BookLine:
    key: str
    site: str
    category: str
    period: str
    status: str
    amount: Optional[Decimal]
    winning_source: str
    rule_fired: str


@dataclass
class Book:
    lines: list = field(default_factory=list)
    dispositions: list = field(default_factory=list)
    queue: list = field(default_factory=list)
    trails: dict = field(default_factory=dict)
    override_claims: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    candidates: list = field(default_factory=list)

    def published(self):
        return [line for line in self.lines if line.amount is not None]

    def total(self):
        return sum((line.amount for line in self.published()), Decimal("0.00")).quantize(MONEY)

    def by_key(self, key):
        for line in self.lines:
            if line.key == key:
                return line
        return None


def load_candidates(data_dir):
    """Read the three source files.

    The encoding is explicit on purpose. A platform default turns a perfectly
    good file into a crash on somebody else's machine.
    """
    rows = []
    for source in ("plan", "vendor", "system"):
        filename, code_col, amount_col, status_col = SOURCE_FILES[source]
        path = os.path.join(data_dir, filename)
        with open(path, newline="", encoding="utf-8") as handle:
            for record in csv.DictReader(handle):
                rows.append(
                    Candidate(
                        source=source,
                        raw_code=record[code_col].strip(),
                        site=record["site"].strip(),
                        category=record["category"].strip().lower(),
                        period=record["period"].strip(),
                        amount=money(record[amount_col]),
                        label=record[status_col].strip().lower(),
                    )
                )
    return rows


def load_overrides(data_dir):
    path = os.path.join(data_dir, "overrides.csv")
    if not os.path.exists(path):
        return {}
    overrides = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            raw = record["work_order"].strip()
            overrides[canonical(raw)] = Override(
                key=canonical(raw),
                raw_code=raw,
                amount=money(record["amount"]),
                ruled_by=record["ruled_by"].strip(),
                ruled_on=record["ruled_on"].strip(),
                reason=record["reason"].strip(),
            )
    return overrides


def admit(candidates):
    """Admit on value, not on label.

    A row earns its place in the book by carrying an amount. A status field is
    somebody else's workflow state, maintained on somebody else's schedule, and
    a contractor marking an order cancelled after invoicing it does not refund
    the money. The only thing that disqualifies a row is having no value in it.
    """
    admitted, rejected = [], []
    for candidate in candidates:
        if candidate.amount > Decimal("0.00"):
            admitted.append(candidate)
        else:
            rejected.append(
                Disposition(
                    source=candidate.source,
                    raw_code=candidate.raw_code,
                    key=candidate.key,
                    amount=candidate.amount,
                    kind=REJECTED,
                    reason="no value: amount is {0}, the label '{1}' was not consulted".format(
                        candidate.amount, candidate.label
                    ),
                )
            )
    return admitted, rejected


def label_filtered(candidates, bad_labels=("cancelled", "void", "inactive")):
    """What a label based filter would have admitted.

    Never used to build the book. It exists so the demo can price the difference
    in money rather than assert it in prose.
    """
    kept = [c for c in candidates if c.label not in bad_labels and c.amount > Decimal("0.00")]
    dropped = [c for c in candidates if c.label in bad_labels and c.amount > Decimal("0.00")]
    return kept, dropped


def group_lines(admitted):
    """canonical key -> {source: candidate}. One candidate per source per line."""
    lines = {}
    for candidate in admitted:
        lines.setdefault(candidate.key, {})[candidate.source] = candidate
    return dict(sorted(lines.items()))


def _line_attributes(by_source):
    for source in STABLE_SOURCE_ORDER:
        if source in by_source:
            candidate = by_source[source]
            return candidate.site, candidate.category, candidate.period
    raise ValueError("a line with no candidates cannot exist")


def ratio_between(a, b):
    """How far apart two figures are, larger over smaller.

    None when the smaller one is zero, which reads as an unbounded gap and is
    always escalated rather than divided by.
    """
    high, low = max(a, b), min(a, b)
    if low <= Decimal("0.00"):
        return None
    return (high / low).quantize(Decimal("0.001"))


def resolve(candidates, policy, overrides=None):
    """Build the book: one figure per line, every figure defensible."""
    overrides = overrides or {}
    book = Book(candidates=list(candidates))

    admitted, rejected = admit(candidates)
    book.rejected = rejected
    book.dispositions.extend(rejected)

    for key, by_source in group_lines(admitted).items():
        site, category, period = _line_attributes(by_source)
        trail = AuditTrail(key=key, site=site, category=category, period=period)
        trail.add(
            "KEYS",
            "raw spellings joined: "
            + ", ".join(sorted("{0}={1}".format(c.source, c.raw_code) for c in by_source.values())),
        )
        for candidate in sorted(by_source.values(), key=lambda c: c.source):
            trail.add(
                "INPUT",
                "{0} reports {1} (label '{2}')".format(
                    candidate.source, candidate.amount, candidate.label
                ),
            )

        # The resolver does not trust the policy to hand back exactly one rule.
        # It builds a claim per rule returned and lets partition.assert_one_owner
        # be the judge, so an overlapping policy fails loudly instead of quietly
        # counting a line twice.
        for rule in policy.rules_for(category, site):
            ranked = [by_source[src] for src in rule.order if src in by_source]
            if not ranked:
                trail.add(
                    "POLICY",
                    "rule '{0}' ranks no source that reported this line".format(rule.name),
                )
                continue

            trail.add("POLICY", "rule fired: {0} ({1})".format(rule.name, rule.note))
            winner = ranked[0]
            runner_up = ranked[1] if len(ranked) > 1 else None

            status = RESOLVED
            published_source = winner.source
            published_amount = winner.amount

            if runner_up is None:
                trail.add(
                    "PRECEDENCE",
                    "{0} is the only admitted source, taken at {1}".format(
                        winner.source, winner.amount
                    ),
                )
            else:
                gap = ratio_between(winner.amount, runner_up.amount)
                shown = "unbounded" if gap is None else "{0}x".format(gap)
                trail.add(
                    "PRECEDENCE",
                    "{0} ({1}) beats {2} ({3}), gap {4}".format(
                        winner.source, winner.amount, runner_up.source, runner_up.amount, shown
                    ),
                )
                if gap is None or gap > rule.bound:
                    exception = policy.exception_for(key)
                    if exception is None:
                        status = ESCALATED
                        published_source = "none"
                        published_amount = None
                        trail.add(
                            "BOUND",
                            "gap {0} exceeds the {1}x bound, so the flip is not taken automatically".format(
                                shown, rule.bound
                            ),
                        )
                        # A line a person has already ruled on is decided. It is
                        # recorded as having broken the bound, but it does not go
                        # back into the queue as though nobody had looked at it.
                        if key in overrides:
                            trail.add(
                                "OUTCOME",
                                "would have ESCALATED, pre-empted by the ruling below",
                            )
                        else:
                            trail.add(
                                "OUTCOME", "ESCALATED to the decision queue with both figures"
                            )
                            book.queue.append(
                                Escalation(
                                    key=key,
                                    site=site,
                                    category=category,
                                    period=period,
                                    rule_name=rule.name,
                                    contender=winner,
                                    incumbent=runner_up,
                                    ratio=gap,
                                    bound=rule.bound,
                                )
                            )
                    else:
                        trail.add("BOUND", "gap {0} exceeds the {1}x bound".format(shown, rule.bound))
                        trail.add(
                            "EXCEPTION",
                            "named exception granted by {0} on {1}: {2}".format(
                                exception.granted_by, exception.granted_on, exception.reason
                            ),
                        )
                else:
                    trail.add("BOUND", "gap {0} is within the {1}x bound".format(shown, rule.bound))

            override = overrides.get(key)
            if override is not None:
                trail.add(
                    "OVERRIDE",
                    "{0} ruled {1} on {2}: {3}".format(
                        override.ruled_by, override.amount, override.ruled_on, override.reason
                    ),
                )
                trail.add(
                    "OUTCOME",
                    "OVERRIDDEN at {0}, the rule outcome above is recorded but not published".format(
                        override.amount
                    ),
                )
                status = OVERRIDDEN
                published_source = "override"
                published_amount = override.amount
                book.override_claims.append((key, override.amount))
                for candidate in by_source.values():
                    book.dispositions.append(
                        Disposition(
                            candidate.source,
                            candidate.raw_code,
                            key,
                            candidate.amount,
                            SUPPRESSED,
                            "superseded by a human ruling from {0}".format(override.ruled_by),
                        )
                    )
            elif status == ESCALATED:
                for candidate in by_source.values():
                    book.dispositions.append(
                        Disposition(
                            candidate.source,
                            candidate.raw_code,
                            key,
                            candidate.amount,
                            SUPPRESSED,
                            "line escalated, no figure published",
                        )
                    )
            else:
                trail.add("OUTCOME", "RESOLVED to {0} at {1}".format(winner.source, winner.amount))
                for candidate in by_source.values():
                    if candidate is winner:
                        book.dispositions.append(
                            Disposition(
                                candidate.source,
                                candidate.raw_code,
                                key,
                                candidate.amount,
                                WINNER,
                                "top ranked source under {0}".format(rule.name),
                            )
                        )
                    else:
                        ranked_here = candidate.source in rule.order
                        why = (
                            "outranked by {0}".format(winner.source)
                            if ranked_here
                            else "not ranked by this rule"
                        )
                        book.dispositions.append(
                            Disposition(
                                candidate.source,
                                candidate.raw_code,
                                key,
                                candidate.amount,
                                SUPPRESSED,
                                why,
                            )
                        )

            book.lines.append(
                BookLine(
                    key=key,
                    site=site,
                    category=category,
                    period=period,
                    status=status,
                    amount=published_amount,
                    winning_source=published_source,
                    rule_fired=rule.name,
                )
            )

        book.trails[key] = trail

    book.lines.sort(key=lambda line: (line.period, line.key))
    return book
