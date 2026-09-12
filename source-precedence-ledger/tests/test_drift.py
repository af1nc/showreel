"""Drift: real movement, no movement, and never having run at all."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import drift as drift_module
from drift import PublishedLine, compare, load_published_book
from resolver import load_candidates, load_overrides, resolve
from rules import Policy

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(HERE, "data")
PUBLISHED = os.path.join(DATA_DIR, "published_book.csv")


def shipped_book():
    policy = Policy()
    policy.validate()
    return resolve(load_candidates(DATA_DIR), policy, load_overrides(DATA_DIR))


def as_published(book):
    """Freeze a book as though it had been published, for a like for like diff."""
    return {
        line.key: PublishedLine(
            key=line.key, site=line.site, category=line.category, period=line.period,
            amount=line.amount, winning_source=line.winning_source, status=line.status,
        )
        for line in book.lines
    }


class TestDriftAgainstTheFixture(unittest.TestCase):
    def report(self):
        return compare(load_published_book(PUBLISHED), shipped_book())

    def test_the_check_ran(self):
        self.assertTrue(self.report().ran)

    def test_it_finds_the_source_flip(self):
        moved = {m.key: m for m in self.report().movements}
        self.assertEqual(moved["wo4471"].kind, drift_module.BOTH)
        self.assertIn("6,980.50", moved["wo4471"].before)
        self.assertIn("7,120.00", moved["wo4471"].after)

    def test_it_finds_a_line_that_stopped_resolving(self):
        moved = {m.key: m for m in self.report().movements}
        self.assertEqual(moved["wo6152"].kind, drift_module.STATUS)
        self.assertIn("ESCALATED", moved["wo6152"].after)
        self.assertIn("sanity bound", moved["wo6152"].reason)

    def test_it_finds_a_line_a_person_has_since_ruled_on(self):
        moved = {m.key: m for m in self.report().movements}
        self.assertIn("human ruling", moved["wo6488"].reason)

    def test_it_finds_the_newly_admitted_line(self):
        moved = {m.key: m for m in self.report().movements}
        self.assertEqual(moved["wo5203"].kind, drift_module.NEW)

    def test_it_finds_the_line_no_source_reports_any_more(self):
        moved = {m.key: m for m in self.report().movements}
        self.assertEqual(moved["wo9004"].kind, drift_module.DROPPED)

    def test_a_stable_line_is_not_reported_as_movement(self):
        moved = {m.key for m in self.report().movements}
        self.assertNotIn("wo5310", moved)
        self.assertNotIn("wo7120", moved)

    def test_every_movement_carries_a_reason(self):
        self.assertTrue(all(m.reason.strip() for m in self.report().movements))


class TestZeroMovementIsARealResult(unittest.TestCase):
    def test_re_resolving_the_same_inputs_moves_nothing(self):
        book = shipped_book()
        report = compare(as_published(book), book)
        self.assertTrue(report.ran)
        self.assertEqual(report.movements, [])

    def test_zero_movement_renders_as_having_run(self):
        book = shipped_book()
        rendered = compare(as_published(book), book).render()
        self.assertIn("ran against", rendered)
        self.assertIn("0 movements", rendered)
        self.assertNotIn("DID NOT RUN", rendered)


class TestNotRunIsNotZeroMovement(unittest.TestCase):
    def test_a_missing_published_book_does_not_pass_as_agreement(self):
        report = compare(load_published_book(os.path.join(DATA_DIR, "no_such_book.csv")),
                         shipped_book())
        self.assertFalse(report.ran)
        self.assertEqual(report.movements, [])

    def test_it_renders_as_plainly_not_having_run(self):
        rendered = compare(None, shipped_book()).render()
        self.assertIn("DID NOT RUN", rendered)
        self.assertNotIn("0 movements", rendered)

    def test_a_missing_file_reads_as_missing_not_as_an_empty_book(self):
        self.assertIsNone(load_published_book(os.path.join(DATA_DIR, "no_such_book.csv")))


if __name__ == "__main__":
    unittest.main()
