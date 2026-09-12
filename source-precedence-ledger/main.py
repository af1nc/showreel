"""Source Precedence Ledger: command line entry point.

    python main.py --demo
    python main.py --resolve
    python main.py --drift
    python main.py --audit WO-4471
"""

import sys

# Windows consoles still default to a legacy code page, which turns a table
# border into a UnicodeEncodeError. Do this before anything prints.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import os
from decimal import Decimal

import drift as drift_module
import keys as keys_module
from audit import fmt_money, render_book, render_queue, render_sources, render_table
from partition import assert_one_owner, check_partition
from resolver import (
    WINNER,
    label_filtered,
    load_candidates,
    load_overrides,
    resolve,
)
from rules import Policy

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
PUBLISHED_BOOK = os.path.join(DATA_DIR, "published_book.csv")

RULE = "═" * 78


def heading(number, title):
    print()
    print(RULE)
    print("{0}. {1}".format(number, title))
    print(RULE)


def build_book():
    candidates = load_candidates(DATA_DIR)
    overrides = load_overrides(DATA_DIR)
    policy = Policy()
    policy.validate()
    return candidates, overrides, policy, resolve(candidates, policy, overrides)


def cmd_resolve():
    _candidates, _overrides, _policy, book = build_book()
    print(render_book(book))
    print()
    print(render_queue(book))
    print()
    print(assert_one_owner(book).render())
    return 0


def cmd_drift():
    _candidates, _overrides, _policy, book = build_book()
    published = drift_module.load_published_book(PUBLISHED_BOOK)
    report = drift_module.compare(published, book)
    print(report.render())
    return 0 if report.ran else 1


def cmd_audit(code):
    _candidates, _overrides, _policy, book = build_book()
    key = keys_module.canonical(code)
    trail = book.trails.get(key)
    if trail is None:
        print("No line in the book for '{0}' (normalised to '{1}').".format(code, key))
        known = ", ".join(sorted(book.trails))
        print("Known keys: " + known)
        return 1
    raw_codes = keys_module.group_raw_codes(
        [c.as_keyed_row() for c in book.candidates]
    ).get(key, ())
    print(trail.render(raw_codes=raw_codes, dispositions=book.dispositions))
    return 0


def cmd_demo():
    candidates, overrides, policy, book = build_book()

    print(RULE)
    print("SOURCE PRECEDENCE LEDGER")
    print("Three systems report the cost of the same maintenance work orders for")
    print("Wrenfield Estates (a fictional landlord). They disagree. One figure per")
    print("line has to be published, and every figure has to be defensible.")
    print(RULE)

    heading(1, "The raw disagreement")
    print("Three files, three spellings of the same code, three different amounts.")
    print("Nothing has been decided yet.")
    print()
    print(render_sources(candidates))

    heading(2, "Keys: normalise before you compare, then guard the merge")
    keyed = [c.as_keyed_row() for c in candidates]
    grouped = keys_module.group_raw_codes(keyed)
    joined = [(key, raws) for key, raws in grouped.items() if len(raws) > 1]
    print("Codes arrive spelled differently in every system. Normalising to")
    print("alphanumeric lowercase and stripping a spelled out revision suffix joins")
    print("lines that looked unrelated:")
    print()
    print(render_table(
        ["canonical key", "raw spellings joined"],
        [[key, "  |  ".join(raws)] for key, raws in joined],
    ))
    print()
    print("Now the guard. A rule aggressive enough to fold every stray spelling also")
    print("folds work orders that are genuinely different:")
    print()
    collisions = keys_module.find_collisions(keyed)
    for collision in collisions:
        print("  REFUSED: " + collision.describe())
        for key in sorted(collision.keys)[1:]:
            line = book.by_key(key)
            if line is not None and line.amount is not None:
                print("           {0} publishes {1} of its own. Under the careless key it".format(
                    key, fmt_money(line.amount)))
                print("           would have become one more candidate for {0} and never".format(
                    sorted(collision.keys)[0]))
                print("           been published at all.")
    print()
    print("The book is keyed on the conservative rule, so the merge never happens.")
    print("The careless rule is kept in keys.py only to prove what it would cost.")

    heading(3, "Admission: on value, not on label")
    strict_kept, label_dropped = label_filtered(candidates)
    lost = sum((c.amount for c in label_dropped), Decimal("0.00"))
    print("A label based filter drops anything marked cancelled, void or inactive.")
    print("Here is what that filter would have thrown away:")
    print()
    print(render_table(
        ["source", "raw code", "label", "amount"],
        [[c.source, c.raw_code, c.label, fmt_money(c.amount)] for c in label_dropped],
        ["left", "left", "left", "right"],
    ))
    print()
    print("{0} of invoiced cost, and for {1} the contractor invoice is the only".format(
        fmt_money(lost), label_dropped[0].raw_code if label_dropped else "that line"))
    print("record of the job, so the whole line would have vanished from the book.")
    print("A status field is another team's workflow state. It does not refund money.")
    print("The ledger admits a row because it carries an amount:")
    for disposition in book.rejected:
        print("  rejected {0} from {1}: {2}".format(
            disposition.raw_code, disposition.source, disposition.reason))
    print("  (that one is a genuine zero, which is the only thing that fails admission)")

    heading(4, "Precedence, per category, expressed as data")
    print(render_table(
        ["category", "scope", "precedence", "bound", "why"],
        policy.table(),
    ))
    print()
    print("The whole policy is a table in rules.py, not a nest of conditionals, so")
    print("somebody who does not read Python can still check it.")

    heading(5, "The sanity bound: the most important judgement here")
    print("Precedence says source A beats source B. It does not say by how much.")
    print("When A is more than its bound times B, taking A silently is exactly how a")
    print("single bad export becomes a published number. Beyond the bound the line")
    print("does not auto resolve, it goes to a person:")
    print()
    print(render_queue(book))
    print()
    exception_lines = [key for key, trail in book.trails.items() if "EXCEPTION" in trail.stages()]
    for key in sorted(exception_lines):
        exception = policy.exception_for(key)
        line = book.by_key(key)
        print("  {0} broke the same bound and was still resolved to {1} at {2},".format(
            key, line.winning_source, fmt_money(line.amount)))
        print("  because {0} granted a named exception on {1}:".format(
            exception.granted_by, exception.granted_on))
        print("  '{0}'".format(exception.reason))
    pre_empted = [key for key, trail in book.trails.items()
                  if any(entry.detail.startswith("would have ESCALATED") for entry in trail.entries)]
    for key in sorted(pre_empted):
        print()
        print("  {0} broke the bound too, but a person had already ruled on it, so it is".format(key))
        print("  decided rather than queued. It is still recorded as having broken the")
        print("  bound. See section 6.")
    print()
    print("That is the correct fix for a wrong escalation: one named, reasoned")
    print("exception for one line. Lowering the bound to make the warning go away")
    print("re-admits every bad export in the file at once.")

    heading(6, "Overrides: a human ruling wins, and is recorded as a ruling")
    rows = []
    for key, override in sorted(overrides.items()):
        line = book.by_key(key)
        rows.append([key, fmt_money(override.amount), override.ruled_by,
                     override.ruled_on, line.status, override.reason])
    print(render_table(
        ["work order", "ruled", "by", "on", "status", "reason"],
        rows, ["left", "right", "left", "left", "left", "left"],
    ))
    print()
    print("The rule outcome is still computed and still written to the trail, so the")
    print("reader can see what the machine would have done and what the person did.")

    heading(7, "The resolved book")
    print(render_book(book))

    heading(8, "One owner per figure, proved")
    report = assert_one_owner(book)
    print(report.render())
    print()
    print("Six invariants, asserted rather than hoped for. tests/test_partition.py")
    print("feeds in a deliberately overlapping policy and checks this fails loudly.")

    heading(9, "Drift against the published book")
    published = drift_module.load_published_book(PUBLISHED_BOOK)
    drift_report = drift_module.compare(published, book)
    print(drift_report.render())

    heading(10, "Defending a single number")
    trail_key = "wo6488"
    trail = book.trails[trail_key]
    raw_codes = keys_module.group_raw_codes(
        [c.as_keyed_row() for c in book.candidates]
    ).get(trail_key, ())
    print(trail.render(raw_codes=raw_codes, dispositions=book.dispositions))
    print()
    print("Try another: python main.py --audit WO-4471")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Resolve three disagreeing cost sources into one defensible book.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--demo", action="store_true", help="the whole story, end to end")
    group.add_argument("--resolve", action="store_true", help="build and print the book")
    group.add_argument("--drift", action="store_true", help="diff against the published book")
    group.add_argument("--audit", metavar="WORK_ORDER", help="full audit trail for one line")
    args = parser.parse_args(argv)

    if args.demo:
        return cmd_demo()
    if args.resolve:
        return cmd_resolve()
    if args.drift:
        return cmd_drift()
    return cmd_audit(args.audit)


if __name__ == "__main__":
    sys.exit(main())
