"""Normalisation joins what should join, and the guard refuses what should not."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from keys import KeyedRow, canonical, careless, find_collisions, group_raw_codes, squash


class TestNormalisation(unittest.TestCase):
    def test_the_three_spellings_of_one_work_order_join(self):
        spellings = ["WO-4471", "wo4471", "WO 4471 (rev2)", "  wo_4471  ", "WO/4471"]
        self.assertEqual({canonical(s) for s in spellings}, {"wo4471"})

    def test_squash_keeps_alphanumerics_only(self):
        self.assertEqual(squash("WO 4471 (rev2)"), "wo4471rev2")

    def test_spelled_out_revision_suffixes_are_stripped(self):
        self.assertEqual(canonical("WO-5310-rev1"), "wo5310")
        self.assertEqual(canonical("WO-6310 rev2"), "wo6310")
        self.assertEqual(canonical("wo6310revision3"), "wo6310")
        self.assertEqual(canonical("WO-6310v4"), "wo6310")

    def test_the_work_order_number_itself_is_never_mistaken_for_a_revision(self):
        self.assertEqual(canonical("WO-4471"), "wo4471")
        self.assertEqual(canonical("4471"), "4471")

    def test_a_trailing_letter_is_not_treated_as_a_revision(self):
        # This is the conservative half of the design. WO-4471-B is its own job.
        self.assertEqual(canonical("WO-4471-B"), "wo4471b")
        self.assertNotEqual(canonical("WO-4471-B"), canonical("WO-4471"))

    def test_a_bare_r_is_not_a_revision_marker(self):
        # 'r2' is more likely a room than revision 2, so it stays in the key.
        self.assertEqual(canonical("WO-8800-r2"), "wo8800r2")

    def test_normalisation_is_idempotent(self):
        once = canonical("WO 4471 (rev2)")
        self.assertEqual(canonical(once), once)

    def test_group_raw_codes_reports_what_joined(self):
        rows = [
            KeyedRow("plan", "WO-4471", "Site A", "electrical"),
            KeyedRow("vendor", "wo4471", "Site A", "electrical"),
            KeyedRow("system", "WO 4471 (rev2)", "Site A", "electrical"),
        ]
        self.assertEqual(
            group_raw_codes(rows)["wo4471"],
            ("WO 4471 (rev2)", "WO-4471", "wo4471"),
        )


class TestCollisionGuard(unittest.TestCase):
    def rows(self):
        return [
            KeyedRow("plan", "WO-4471", "Ashford Depot", "electrical"),
            KeyedRow("vendor", "wo4471", "Ashford Depot", "electrical"),
            KeyedRow("plan", "WO-4471-B", "Ashford Depot", "plumbing"),
        ]

    def test_the_careless_rule_really_would_merge_them(self):
        # The guard is only worth having if the danger is real, so prove it is.
        self.assertEqual(careless("WO-4471-B"), careless("WO-4471"))

    def test_the_collision_is_reported_with_evidence(self):
        collisions = find_collisions(self.rows())
        self.assertEqual(len(collisions), 1)
        collision = collisions[0]
        self.assertEqual(collision.careless_key, "wo4471")
        self.assertEqual(collision.keys, ("wo4471", "wo4471b"))
        self.assertIn("different categories", collision.evidence)

    def test_the_keys_stay_apart_regardless(self):
        # The book is keyed on canonical(), so the merge never happens at all.
        keyed = {row.key for row in self.rows()}
        self.assertEqual(keyed, {"wo4471", "wo4471b"})

    def test_clean_data_reports_no_collisions(self):
        rows = [
            KeyedRow("plan", "WO-1000", "Site A", "grounds"),
            KeyedRow("vendor", "wo1000", "Site A", "grounds"),
            KeyedRow("plan", "WO-2000", "Site A", "grounds"),
        ]
        self.assertEqual(find_collisions(rows), [])

    def test_same_number_at_two_sites_is_also_caught(self):
        rows = [
            KeyedRow("plan", "WO-7000-A", "Ashford Depot", "grounds"),
            KeyedRow("vendor", "WO-7000-B", "Kilbride Yard", "grounds"),
        ]
        collisions = find_collisions(rows)
        self.assertEqual(len(collisions), 1)
        self.assertIn("different sites", collisions[0].evidence)


if __name__ == "__main__":
    unittest.main()
