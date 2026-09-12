"""The floor is measured, and it fails loudly when it cannot be."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import answer  # noqa: E402
import floor  # noqa: E402
import probes  # noqa: E402
from indexer import index_corpus  # noqa: E402
from store import VectorStore  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(ROOT, "corpus")


class FloorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="closed-book-rag-floor-")
        path = os.path.join(cls.tmp, "store.json")
        store = VectorStore.load(path)
        index_corpus(store, CORPUS)
        cls.store = VectorStore.load(path)
        cls.calibration = floor.calibrate(
            cls.store, probes.ON_TOPIC, probes.OFF_TOPIC, probes.probe_hash()
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_probe_sets_separate(self):
        self.assertGreater(self.calibration.gap, 0.0)
        self.assertLess(
            self.calibration.on_stats["max"], self.calibration.off_stats["min"]
        )

    def test_floor_sits_inside_the_gap(self):
        self.assertGreater(self.calibration.floor, self.calibration.on_stats["max"])
        self.assertLess(self.calibration.floor, self.calibration.off_stats["min"])

    def test_every_on_topic_probe_is_accepted(self):
        for question in probes.ON_TOPIC:
            distance = floor.nearest_distance(self.store, question)
            self.assertLessEqual(
                distance, self.calibration.floor, "wrongly refused: %s" % question
            )

    def test_every_off_topic_probe_is_refused(self):
        for question in probes.OFF_TOPIC:
            distance = floor.nearest_distance(self.store, question)
            self.assertGreater(
                distance, self.calibration.floor, "wrongly answered: %s" % question
            )

    def test_every_on_topic_probe_produces_a_cited_answer(self):
        # End to end, not just past the floor: an accepted question that then gets
        # refused by the answerer is a refusal the user cannot tell apart from the
        # measured one, and it went unnoticed until this test existed.
        for question in probes.ON_TOPIC:
            result = answer.ask(self.store, question, self.calibration.floor)
            self.assertFalse(result.refused, "refused an on-topic probe: %s" % question)
            self.assertTrue(result.citations, "uncited answer to: %s" % question)

    def test_no_off_topic_probe_reaches_the_answerer(self):
        for question in probes.OFF_TOPIC:
            result = answer.ask(self.store, question, self.calibration.floor)
            self.assertTrue(result.refused)
            self.assertFalse(result.model_called, "model called for: %s" % question)

    def test_overlapping_probes_raise_instead_of_returning_a_number(self):
        # Same questions on both sides: the distributions are identical, so there
        # is no gap and no honest floor to place in it.
        with self.assertRaises(floor.FloorNotSeparable):
            floor.calibrate(
                self.store, probes.ON_TOPIC, probes.ON_TOPIC, probes.probe_hash()
            )

    def test_empty_probe_set_raises(self):
        with self.assertRaises(floor.FloorNotSeparable):
            floor.calibrate(self.store, [], probes.OFF_TOPIC, probes.probe_hash())

    def test_stored_floor_goes_stale_when_the_probe_set_changes(self):
        self.assertEqual(
            "", floor.staleness(self.calibration, self.store, probes.probe_hash())
        )
        reason = floor.staleness(self.calibration, self.store, "different-hash")
        self.assertIn("probe set has changed", reason)

    def test_calibration_survives_a_round_trip(self):
        path = os.path.join(self.tmp, "floor.json")
        floor.save(self.calibration, path)
        loaded = floor.load(path)
        self.assertEqual(self.calibration.floor, loaded.floor)
        self.assertEqual(self.calibration.fingerprint, loaded.fingerprint)


if __name__ == "__main__":
    unittest.main()
