"""Admission on value, precedence, the sanity bound, exceptions and overrides."""

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit import render_book
from resolver import (
    ESCALATED,
    OVERRIDDEN,
    RESOLVED,
    Candidate,
    Override,
    admit,
    label_filtered,
    load_candidates,
    load_overrides,
    ratio_between,
    resolve,
)
from rules import BoundException, Policy

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def candidate(source, code, amount, category="electrical", site="Ashford Depot",
              period="2026-03", label="ok"):
    return Candidate(
        source=source,
        raw_code=code,
        site=site,
        category=category,
        period=period,
        amount=Decimal(amount),
        label=label,
    )


class TestAdmission(unittest.TestCase):
    def test_a_cancelled_row_carrying_real_cost_is_admitted(self):
        rows = [candidate("vendor", "WO-5203", "4820.00", label="cancelled")]
        admitted, rejected = admit(rows)
        self.assertEqual(len(admitted), 1)
        self.assertEqual(rejected, [])

    def test_a_zero_row_is_rejected_whatever_its_label_says(self):
        rows = [candidate("vendor", "WO-5209", "0.00", label="invoiced")]
        admitted, rejected = admit(rows)
        self.assertEqual(admitted, [])
        self.assertEqual(len(rejected), 1)
        self.assertIn("no value", rejected[0].reason)

    def test_a_label_filter_would_lose_real_money_on_the_fixtures(self):
        candidates = load_candidates(DATA_DIR)
        _kept, dropped = label_filtered(candidates)
        lost = sum((row.amount for row in dropped), Decimal("0.00"))
        self.assertEqual(lost, Decimal("4820.00"))

    def test_the_label_filtered_line_is_the_only_record_of_that_job(self):
        candidates = load_candidates(DATA_DIR)
        for_that_line = [c for c in candidates if c.key == "wo5203"]
        self.assertEqual(len(for_that_line), 1)
        self.assertEqual(for_that_line[0].label, "cancelled")


class TestPrecedence(unittest.TestCase):
    def test_the_ranked_source_wins_an_ordinary_line(self):
        book = resolve(
            [candidate("plan", "WO-1", "100.00"),
             candidate("vendor", "WO-1", "110.00"),
             candidate("system", "WO-1", "120.00")],
            Policy(),
        )
        line = book.by_key("wo1")
        self.assertEqual(line.status, RESOLVED)
        self.assertEqual(line.winning_source, "system")
        self.assertEqual(line.amount, Decimal("120.00"))

    def test_precedence_differs_by_category(self):
        book = resolve(
            [candidate("vendor", "WO-2", "110.00", category="plumbing"),
             candidate("system", "WO-2", "120.00", category="plumbing")],
            Policy(),
        )
        self.assertEqual(book.by_key("wo2").winning_source, "vendor")

    def test_a_sole_source_is_taken_and_said_to_be_sole(self):
        book = resolve([candidate("plan", "WO-3", "90.00", category="grounds")], Policy())
        self.assertEqual(book.by_key("wo3").amount, Decimal("90.00"))
        self.assertIn("only admitted source",
                     " ".join(e.detail for e in book.trails["wo3"].entries))


class TestSanityBound(unittest.TestCase):
    def two_sources(self, system_amount, vendor_amount):
        return [candidate("vendor", "WO-9", vendor_amount),
                candidate("system", "WO-9", system_amount)]

    def test_a_flip_inside_the_bound_is_taken(self):
        book = resolve(self.two_sources("1000.00", "600.00"), Policy())
        self.assertEqual(book.by_key("wo9").status, RESOLVED)
        self.assertEqual(book.queue, [])

    def test_a_flip_exactly_on_the_bound_is_taken(self):
        book = resolve(self.two_sources("1200.00", "600.00"), Policy())
        self.assertEqual(book.by_key("wo9").status, RESOLVED)

    def test_a_flip_beyond_the_bound_escalates_instead_of_publishing(self):
        book = resolve(self.two_sources("1500.00", "600.00"), Policy())
        line = book.by_key("wo9")
        self.assertEqual(line.status, ESCALATED)
        self.assertIsNone(line.amount)

    def test_the_escalation_carries_both_figures_and_the_rule(self):
        book = resolve(self.two_sources("1500.00", "600.00"), Policy())
        self.assertEqual(len(book.queue), 1)
        item = book.queue[0]
        self.assertEqual(item.contender.amount, Decimal("1500.00"))
        self.assertEqual(item.incumbent.amount, Decimal("600.00"))
        self.assertEqual(item.ratio, Decimal("2.500"))
        self.assertIn("electrical", item.rule_name)

    def test_an_escalated_line_contributes_nothing_to_the_total(self):
        book = resolve(self.two_sources("1500.00", "600.00"), Policy())
        self.assertEqual(book.total(), Decimal("0.00"))

    def test_a_zero_denominator_reads_as_unbounded_not_as_a_crash(self):
        self.assertIsNone(ratio_between(Decimal("100.00"), Decimal("0.00")))

    def test_a_named_exception_lets_one_line_through_without_moving_the_bound(self):
        policy = Policy(exceptions=(BoundException(
            key="wo9", granted_by="R. Alcott", granted_on="2026-04-28",
            reason="the invoice is a deposit only"),))
        book = resolve(self.two_sources("1500.00", "600.00"), policy)
        line = book.by_key("wo9")
        self.assertEqual(line.status, RESOLVED)
        self.assertEqual(line.amount, Decimal("1500.00"))
        self.assertEqual(book.queue, [])
        self.assertIn("EXCEPTION", book.trails["wo9"].stages())

    def test_the_exception_is_scoped_to_one_line_only(self):
        policy = Policy(exceptions=(BoundException(
            key="wo9", granted_by="R. Alcott", granted_on="2026-04-28", reason="deposit"),))
        rows = self.two_sources("1500.00", "600.00")
        rows += [candidate("vendor", "WO-10", "600.00"), candidate("system", "WO-10", "1500.00")]
        book = resolve(rows, policy)
        self.assertEqual(book.by_key("wo10").status, ESCALATED)


class TestOverrides(unittest.TestCase):
    def override(self, key="wo11", amount="500.00"):
        return {key: Override(key=key, raw_code="WO-11", amount=Decimal(amount),
                              ruled_by="R. Alcott", ruled_on="2026-05-02",
                              reason="site walk confirmed phase one only")}

    def test_an_override_beats_an_ordinary_resolution(self):
        book = resolve(
            [candidate("system", "WO-11", "1000.00"), candidate("vendor", "WO-11", "900.00")],
            Policy(), self.override())
        line = book.by_key("wo11")
        self.assertEqual(line.status, OVERRIDDEN)
        self.assertEqual(line.winning_source, "override")
        self.assertEqual(line.amount, Decimal("500.00"))

    def test_an_override_settles_a_line_the_bound_would_have_escalated(self):
        book = resolve(
            [candidate("system", "WO-11", "5000.00"), candidate("vendor", "WO-11", "900.00")],
            Policy(), self.override())
        self.assertEqual(book.by_key("wo11").status, OVERRIDDEN)
        self.assertEqual(book.queue, [], "a line a person has ruled on is not still queued")

    def test_the_ruling_is_recorded_as_a_ruling_with_who_and_why(self):
        book = resolve([candidate("system", "WO-11", "1000.00")], Policy(), self.override())
        trail = book.trails["wo11"]
        self.assertIn("OVERRIDE", trail.stages())
        detail = " ".join(entry.detail for entry in trail.entries)
        self.assertIn("R. Alcott", detail)
        self.assertIn("site walk confirmed phase one only", detail)

    def test_the_rule_outcome_is_still_recorded_underneath_the_override(self):
        book = resolve(
            [candidate("system", "WO-11", "1000.00"), candidate("vendor", "WO-11", "900.00")],
            Policy(), self.override())
        self.assertIn("PRECEDENCE", book.trails["wo11"].stages())


class TestFixturesEndToEnd(unittest.TestCase):
    def book(self):
        policy = Policy()
        policy.validate()
        return resolve(load_candidates(DATA_DIR), policy, load_overrides(DATA_DIR))

    def test_the_shipped_policy_validates(self):
        Policy().validate()

    def test_the_book_totals_what_it_should(self):
        self.assertEqual(self.book().total(), Decimal("34945.00"))

    def test_one_line_is_escalated_and_publishes_no_figure(self):
        book = self.book()
        escalated = [line for line in book.lines if line.status == ESCALATED]
        self.assertEqual([line.key for line in escalated], ["wo6152"])
        self.assertEqual(len(book.published()), len(book.lines) - 1)

    def test_resolution_is_deterministic(self):
        self.assertEqual(render_book(self.book()), render_book(self.book()))

    def test_money_never_goes_through_a_float(self):
        for line in self.book().published():
            self.assertIsInstance(line.amount, Decimal)


if __name__ == "__main__":
    unittest.main()
