"""A superseded folder must not be answerable from."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import answer  # noqa: E402
import floor  # noqa: E402
import probes  # noqa: E402
from indexer import index_corpus, is_superseded, read_document  # noqa: E402
from store import VectorStore  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(ROOT, "corpus")

QUESTION = "What is the receipt threshold on an expense claim?"
LIVE_RULE = "25 CU"
WITHDRAWN_RULE = "75 CU"


def build(tmp, name, include_superseded):
    path = os.path.join(tmp, name)
    store = VectorStore.load(path)
    report = index_corpus(store, CORPUS, include_superseded=include_superseded)
    return VectorStore.load(path), report


class SupersessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="closed-book-rag-supersede-")
        cls.live, cls.live_report = build(cls.tmp, "live.json", False)
        cls.all_docs, cls.all_report = build(cls.tmp, "all.json", True)
        cls.floor = floor.calibrate(
            cls.live, probes.ON_TOPIC, probes.OFF_TOPIC, probes.probe_hash()
        ).floor

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_superseded_paths_are_recognised(self):
        self.assertTrue(is_superseded("archive/handbook-v2/expense-claims.md"))
        self.assertTrue(is_superseded("old-drafts/shift-handover-draft.md"))
        self.assertTrue(is_superseded("handbook/ARCHIVE/thing.md"))
        self.assertFalse(is_superseded("handbook/v3/expense-claims.md"))
        self.assertFalse(is_superseded("handbook/v3/site-copies/tool-calibration.md"))

    def test_archive_is_excluded_from_the_default_index(self):
        self.assertGreater(self.live_report.excluded, 0)
        for key in self.live.documents:
            self.assertFalse(is_superseded(key), "indexed a superseded document: %s" % key)

    def test_the_archive_really_does_hold_a_contradicting_policy(self):
        # Guards the fixture itself: if the two versions ever agree, this test
        # would pass for the wrong reason.
        self.assertIn("archive/handbook-v2/expense-claims.md", self.all_docs.documents)
        live_text = read_document(
            os.path.join(CORPUS, "handbook", "v3", "expense-claims.md")
        )
        archived_text = read_document(
            os.path.join(CORPUS, "archive", "handbook-v2", "expense-claims.md")
        )
        self.assertIn(LIVE_RULE, live_text)
        self.assertNotIn(WITHDRAWN_RULE, live_text)
        self.assertIn(WITHDRAWN_RULE, archived_text)

    def test_including_the_archive_produces_the_stale_answer(self):
        result = answer.ask(self.all_docs, QUESTION, self.floor)
        self.assertFalse(result.refused)
        self.assertIn(WITHDRAWN_RULE, result.answer)
        self.assertTrue(
            any(is_superseded(path) for path in result.citations),
            "expected the stale answer to cite the archive, got %s" % result.citations,
        )

    def test_excluding_the_archive_produces_the_live_answer(self):
        result = answer.ask(self.live, QUESTION, self.floor)
        self.assertFalse(result.refused)
        self.assertIn(LIVE_RULE, result.answer)
        self.assertNotIn(WITHDRAWN_RULE, result.answer)
        self.assertEqual(["handbook/v3/expense-claims.md"], result.citations)

    def test_a_document_moved_into_an_archive_folder_is_pruned(self):
        scratch_corpus = os.path.join(self.tmp, "corpus-copy")
        shutil.copytree(CORPUS, scratch_corpus)
        path = os.path.join(self.tmp, "moving.json")
        store = VectorStore.load(path)
        index_corpus(store, scratch_corpus)
        self.assertIn("handbook/v3/visitor-access.md", store.documents)

        os.makedirs(os.path.join(scratch_corpus, "archive", "handbook-v2"), exist_ok=True)
        shutil.move(
            os.path.join(scratch_corpus, "handbook", "v3", "visitor-access.md"),
            os.path.join(scratch_corpus, "archive", "handbook-v2", "visitor-access.md"),
        )
        store = VectorStore.load(path)
        report = index_corpus(store, scratch_corpus)
        self.assertEqual(1, report.pruned)
        self.assertNotIn("handbook/v3/visitor-access.md", store.documents)
        self.assertNotIn("archive/handbook-v2/visitor-access.md", store.documents)
        shutil.rmtree(scratch_corpus, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
