"""One owner per figure, proved rather than assumed.

A precedence engine has one failure mode that matters more than the rest: a line
claimed twice, or a line claimed by nobody. Both are invisible in a table of
plausible looking numbers, and both change the total.

So the book is not finished when it is built. It is finished when it has been
shown to partition the inputs: every input row has exactly one disposition,
every admitted line is claimed exactly once, and the published total is the sum
of the winning claims and nothing else.

This is an assertion, not a warning. A book that fails it is not published.
"""

from decimal import Decimal

from resolver import OVERRIDDEN, REJECTED, SUPPRESSED, WINNER


class PartitionError(AssertionError):
    """The book does not partition its inputs. Refuse to publish it."""


class Check:
    def __init__(self, name, ok, detail):
        self.name = name
        self.ok = ok
        self.detail = detail

    def line(self):
        return "  [{0}] {1}: {2}".format("PASS" if self.ok else "FAIL", self.name, self.detail)


class PartitionReport:
    def __init__(self, checks):
        self.checks = checks

    @property
    def ok(self):
        return all(check.ok for check in self.checks)

    def render(self):
        head = "Partition assertion: {0}".format("PASS" if self.ok else "FAIL")
        return "\n".join([head] + [check.line() for check in self.checks])

    def failures(self):
        return [check for check in self.checks if not check.ok]


def _counts(pairs):
    counted = {}
    for pair in pairs:
        counted[pair] = counted.get(pair, 0) + 1
    return counted


def check_partition(book):
    """Run every invariant and report. Does not raise: see assert_one_owner."""
    checks = []

    # 1. Every input row has exactly one disposition.
    input_rows = _counts([(c.source, c.raw_code) for c in book.candidates])
    disposed = _counts([(d.source, d.raw_code) for d in book.dispositions])
    missing = sorted(row for row in input_rows if row not in disposed)
    doubled = sorted(row for row, count in disposed.items()
                     if count != input_rows.get(row, 0))
    ok = not missing and not doubled
    detail = "{0} input rows, {1} dispositions".format(
        sum(input_rows.values()), sum(disposed.values()))
    if missing:
        detail += "; no disposition for {0}".format(missing)
    if doubled:
        detail += "; disposed a different number of times than they arrived: {0}".format(doubled)
    checks.append(Check("every input row has exactly one disposition", ok, detail))

    # 2. Every admitted line is claimed exactly once in the book.
    admitted_keys = sorted({d.key for d in book.dispositions if d.kind != REJECTED})
    book_keys = _counts([line.key for line in book.lines])
    claimed_twice = sorted(key for key, count in book_keys.items() if count > 1)
    unclaimed = [key for key in admitted_keys if key not in book_keys]
    ok = not claimed_twice and not unclaimed
    detail = "{0} admitted lines, {1} book lines".format(len(admitted_keys), len(book.lines))
    if claimed_twice:
        detail += "; claimed more than once: {0}".format(claimed_twice)
    if unclaimed:
        detail += "; admitted but never claimed: {0}".format(unclaimed)
    checks.append(Check("every admitted line is claimed exactly once", ok, detail))

    # 3. The book invents nothing.
    invented = sorted(key for key in book_keys if key not in admitted_keys)
    checks.append(Check(
        "the book contains no line that no source reported",
        not invented,
        "no invented lines" if not invented else "invented: {0}".format(invented),
    ))

    # 4. The published total is exactly the sum of the winning claims.
    winner_total = sum((d.amount for d in book.dispositions if d.kind == WINNER), Decimal("0.00"))
    override_total = sum((amount for _key, amount in book.override_claims), Decimal("0.00"))
    claimed_total = (winner_total + override_total).quantize(Decimal("0.01"))
    book_total = book.total()
    ok = claimed_total == book_total
    detail = "winners {0} + overrides {1} = {2}, book says {3}".format(
        winner_total, override_total, claimed_total, book_total)
    checks.append(Check("the published total is the sum of the winning claims", ok, detail))

    # 5. Nothing is dropped without a reason on the record.
    unreasoned = [d for d in book.dispositions
                  if d.kind in (REJECTED, SUPPRESSED) and not d.reason.strip()]
    checks.append(Check(
        "every suppressed or rejected row carries a reason",
        not unreasoned,
        "{0} suppressed, {1} rejected, all with reasons".format(
            sum(1 for d in book.dispositions if d.kind == SUPPRESSED),
            sum(1 for d in book.dispositions if d.kind == REJECTED),
        ) if not unreasoned else "{0} rows dropped with no reason".format(len(unreasoned)),
    ))

    # 6. An overridden line publishes the ruling, never a source figure as well.
    bad_overrides = []
    override_keys = {key for key, _amount in book.override_claims}
    for line in book.lines:
        if line.key in override_keys and line.status != OVERRIDDEN:
            bad_overrides.append(line.key)
        if line.status == OVERRIDDEN and line.winning_source != "override":
            bad_overrides.append(line.key)
    checks.append(Check(
        "an overridden line publishes the ruling and nothing else",
        not bad_overrides,
        "{0} overrides applied cleanly".format(len(book.override_claims))
        if not bad_overrides else "inconsistent override lines: {0}".format(sorted(set(bad_overrides))),
    ))

    return PartitionReport(checks)


def assert_one_owner(book):
    """Run the partition check and fail loudly if it does not hold."""
    report = check_partition(book)
    if not report.ok:
        detail = "; ".join("{0} ({1})".format(check.name, check.detail)
                           for check in report.failures())
        raise PartitionError("the book does not partition its inputs: " + detail)
    return report
