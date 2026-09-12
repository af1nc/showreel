"""Re-resolve, then diff against the book that was already published.

Every figure in the previous book was defended to somebody. When the rules, the
overrides or the source files move, the question is not "what does the book say
now" but "what changed since the version people are working from, and why".

A drift report with no movements is a real and useful result. It has to be
impossible to confuse with a report that never ran, so the two render as clearly
different things and carry different exit paths.
"""

import csv
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from audit import fmt_money, render_table
from keys import canonical
from resolver import money

NEW = "NEW"
DROPPED = "DROPPED"
AMOUNT = "AMOUNT"
SOURCE = "SOURCE"
BOTH = "AMOUNT AND SOURCE"
STATUS = "STATUS"


@dataclass(frozen=True)
class PublishedLine:
    key: str
    site: str
    category: str
    period: str
    amount: Optional[Decimal]
    winning_source: str
    status: str


@dataclass(frozen=True)
class Movement:
    key: str
    kind: str
    before: str
    after: str
    reason: str


@dataclass
class DriftReport:
    ran: bool
    compared: int = 0
    movements: list = field(default_factory=list)
    not_run_reason: str = ""

    @classmethod
    def not_run(cls, reason):
        return cls(ran=False, not_run_reason=reason)

    @property
    def moved(self):
        return len(self.movements)

    def render(self):
        if not self.ran:
            return (
                "Drift check DID NOT RUN: {0}\n"
                "This is not a clean result. Nothing has been compared."
            ).format(self.not_run_reason)
        if not self.movements:
            return (
                "Drift check ran against {0} previously published lines.\n"
                "0 movements: every line resolves to the same figure and the same source."
            ).format(self.compared)
        headers = ["work order", "what moved", "published book", "re-resolved", "why"]
        rows = [[m.key, m.kind, m.before, m.after, m.reason] for m in self.movements]
        table = render_table(headers, rows)
        return (
            "Drift check ran against {0} previously published lines, {1} moved.\n".format(
                self.compared, self.moved
            )
            + table
        )


def load_published_book(path):
    """Read a previously published book. Missing file is not an empty book."""
    if not os.path.exists(path):
        return None
    published = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            key = canonical(record["work_order"])
            raw_amount = record["amount"].strip()
            published[key] = PublishedLine(
                key=key,
                site=record["site"].strip(),
                category=record["category"].strip().lower(),
                period=record["period"].strip(),
                amount=money(raw_amount) if raw_amount else None,
                winning_source=record["winning_source"].strip(),
                status=record["status"].strip().upper(),
            )
    return published


def _reason_for(book, key):
    """Why this line resolves the way it does now, in one clause, from its trail."""
    trail = book.trails.get(key)
    stages = trail.stages() if trail else []
    if "OVERRIDE" in stages:
        return "a human ruling now stands on this line"
    if "EXCEPTION" in stages:
        return "flip beyond the bound allowed by a named exception"
    line = book.by_key(key)
    if line is not None and line.status == "ESCALATED":
        return "the sanity bound refused the flip and escalated it"
    if line is not None:
        return "precedence under {0}".format(line.rule_fired)
    return "no longer present in any source"


def _state(amount, source, status):
    if amount is None:
        return "{0} ({1})".format(status, source)
    return "{0} from {1}".format(fmt_money(amount), source)


def compare(published, book):
    """Diff a re-resolved book against the published one."""
    if published is None:
        return DriftReport.not_run("no published book was found to compare against")

    movements = []
    current = {line.key: line for line in book.lines}

    for key in sorted(set(published) | set(current)):
        was = published.get(key)
        now = current.get(key)

        if was is None:
            movements.append(Movement(
                key=key, kind=NEW, before="not in the book",
                after=_state(now.amount, now.winning_source, now.status),
                reason="admitted by this run: " + _reason_for(book, key)))
            continue
        if now is None:
            movements.append(Movement(
                key=key, kind=DROPPED,
                before=_state(was.amount, was.winning_source, was.status),
                after="not in the book",
                reason="no source reported this line in this run"))
            continue

        amount_moved = was.amount != now.amount
        source_moved = was.winning_source != now.winning_source
        status_moved = was.status != now.status

        if not (amount_moved or source_moved or status_moved):
            continue

        if status_moved and now.amount is None:
            kind = STATUS
        elif amount_moved and source_moved:
            kind = BOTH
        elif amount_moved:
            kind = AMOUNT
        elif source_moved:
            kind = SOURCE
        else:
            kind = STATUS

        movements.append(Movement(
            key=key, kind=kind,
            before=_state(was.amount, was.winning_source, was.status),
            after=_state(now.amount, now.winning_source, now.status),
            reason=_reason_for(book, key)))

    return DriftReport(ran=True, compared=len(published), movements=movements)
