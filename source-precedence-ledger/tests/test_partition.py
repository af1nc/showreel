"""The one owner per figure assertion, including a rule set built to break it."""

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from partition import PartitionError, assert_one_owner, check_partition
from resolver import SUPPRESSED, WINNER, load_candidates, load_overrides, resolve
from rules import DEFAULT_BOUND, Policy, Rule

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


class OverlappingPolicy(Policy):
    """A policy where two rules govern the same line.

    This is not a contrived failure. It is what happens the day somebody adds a
    carve out for one site and leaves the general rule in place: both rules
    match, the line is claimed twice, and the total quietly goes up.
    """

    def rules_for(self, category, site):
        governing = super().rules_for(category, site)
        shadow = Rule(
            category=category,
            site=None,
            order=("plan", "vendor", "system"),
            bound=DEFAULT_BOUND,
            note="a second rule that should never have been added",
        )
        return governing + (shadow,)


def shipped_book():
    policy = Policy()
    policy.validate()
    return resolve(load_candidates(DATA_DIR), policy, load_overrides(DATA_DIR))


class TestPartitionHolds(unittest.TestCase):
    def test_the_shipped_book_partitions_its_inputs(self):
        report = assert_one_owner(shipped_book())
        self.assertTrue(report.ok)

    def test_every_input_row_has_exactly_one_disposition(self):
        book = shipped_book()
        self.assertEqual(len(book.dispositions), len(book.candidates))

    def test_the_total_is_the_sum_of_the_winning_claims(self):
        book = shipped_book()
        winners = sum((d.amount for d in book.dispositions if d.kind == WINNER), Decimal("0.00"))
        overrides = sum((amount for _key, amount in book.override_claims), Decimal("0.00"))
        self.assertEqual(winners + overrides, book.total())

    def test_a_suppressed_amount_is_never_also_published(self):
        book = shipped_book()
        for disposition in book.dispositions:
            if disposition.kind != SUPPRESSED:
                continue
            line = book.by_key(disposition.key)
            if line.winning_source == disposition.source:
                self.fail("{0} was suppressed and published at once".format(disposition.key))

    def test_the_rejected_row_is_accounted_for_rather_than_vanishing(self):
        book = shipped_book()
        self.assertEqual(len(book.rejected), 1)
        self.assertTrue(all(d.reason for d in book.rejected))


class TestPartitionFailsLoudly(unittest.TestCase):
    def test_an_overlapping_rule_set_trips_the_assertion(self):
        book = resolve(load_candidates(DATA_DIR), OverlappingPolicy(), load_overrides(DATA_DIR))
        with self.assertRaises(PartitionError) as caught:
            assert_one_owner(book)
        self.assertIn("claimed", str(caught.exception))

    def test_the_failing_report_names_the_doubled_lines(self):
        book = resolve(load_candidates(DATA_DIR), OverlappingPolicy(), load_overrides(DATA_DIR))
        report = check_partition(book)
        self.assertFalse(report.ok)
        failed = [check.name for check in report.failures()]
        self.assertIn("every admitted line is claimed exactly once", failed)

    def test_the_doubled_book_really_does_inflate_the_total(self):
        # The point of the assertion: the broken book looks entirely plausible.
        broken = resolve(load_candidates(DATA_DIR), OverlappingPolicy(), load_overrides(DATA_DIR))
        self.assertGreater(broken.total(), shipped_book().total())

    def test_policy_validate_catches_the_overlap_earlier(self):
        rules = Policy().rules + (
            Rule(category="grounds", site=None, order=("plan",), bound=DEFAULT_BOUND, note="dup"),
        )
        with self.assertRaises(ValueError):
            Policy(rules=rules).validate()

    def test_policy_validate_rejects_a_rule_that_names_a_source_twice(self):
        rules = (Rule(category="grounds", site=None, order=("plan", "plan"),
                      bound=DEFAULT_BOUND, note="dup source"),)
        with self.assertRaises(ValueError):
            Policy(rules=rules).validate()

    def test_policy_validate_rejects_an_unknown_source(self):
        rules = (Rule(category="grounds", site=None, order=("plan", "hearsay"),
                      bound=DEFAULT_BOUND, note="unknown source"),)
        with self.assertRaises(ValueError):
            Policy(rules=rules).validate()


if __name__ == "__main__":
    unittest.main()
