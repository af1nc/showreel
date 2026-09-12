"""Re-indexing does the minimum work, and never leaves the index inconsistent."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexer import index_corpus  # noqa: E402
from store import VectorStore  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(ROOT, "corpus")

CANONICAL_DUPLICATE = "handbook/v3/tool-calibration.md"
ALIAS_DUPLICATE = "handbook/v3/site-copies/tool-calibration.md"


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="closed-book-rag-incremental-")
        self.corpus = os.path.join(self.tmp, "corpus")
        shutil.copytree(CORPUS, self.corpus)
        self.path = os.path.join(self.tmp, "store.json")
        self.first = self.reindex()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def reindex(self, **kwargs):
        store = VectorStore.load(self.path)
        report = index_corpus(store, self.corpus, **kwargs)
        self.store = VectorStore.load(self.path)
        return report

    def document(self, relative):
        return os.path.join(self.corpus, *relative.split("/"))

    # ------------------------------------------------------------------ tests

    def test_first_run_adds_everything_once(self):
        self.assertGreater(self.first.added, 0)
        self.assertEqual(0, self.first.changed)
        self.assertEqual(0, self.first.skipped)
        self.assertEqual(self.first.embedded_chunks, self.store.chunk_count())

    def test_second_run_changes_nothing_and_embeds_nothing(self):
        second = self.reindex()
        self.assertEqual(0, second.added)
        self.assertEqual(0, second.changed)
        self.assertEqual(0, second.pruned)
        self.assertEqual(0, second.embedded_chunks)
        self.assertEqual(len(self.store.documents), second.skipped)

    def test_editing_one_document_re_embeds_only_that_document(self):
        before = self.store.chunk_count()
        target = self.document("handbook/v3/shift-handover.md")
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("\n## Late starts\n\nA late start is recorded on the card.\n")

        report = self.reindex()
        self.assertEqual(1, report.changed)
        self.assertEqual(0, report.added)
        self.assertEqual(len(self.store.documents) - 1, report.skipped)
        self.assertGreater(report.embedded_chunks, 0)
        self.assertLess(report.embedded_chunks, before)
        self.assertEqual(
            report.embedded_chunks,
            self.store.chunk_count("handbook/v3/shift-handover.md"),
        )

    def test_a_removed_document_is_pruned_with_its_chunks(self):
        removed = "handbook/v3/visitor-access.md"
        self.assertGreater(self.store.chunk_count(removed), 0)
        os.remove(self.document(removed))

        report = self.reindex()
        self.assertEqual(1, report.pruned)
        self.assertNotIn(removed, self.store.documents)
        self.assertEqual(0, self.store.chunk_count(removed))

    def test_byte_identical_copies_are_embedded_once(self):
        self.assertEqual(1, self.first.duplicates)
        self.assertIn(CANONICAL_DUPLICATE, self.store.documents)
        self.assertIn(ALIAS_DUPLICATE, self.store.documents)
        self.assertGreater(self.store.chunk_count(CANONICAL_DUPLICATE), 0)
        self.assertEqual(0, self.store.chunk_count(ALIAS_DUPLICATE))
        self.assertEqual(
            CANONICAL_DUPLICATE,
            self.store.documents[ALIAS_DUPLICATE]["duplicate_of"],
            "the shallower copy should be the canonical one",
        )

    def test_editing_one_copy_of_a_duplicate_pair_splits_them(self):
        with open(self.document(ALIAS_DUPLICATE), "a", encoding="utf-8") as handle:
            handle.write("\n## Site note\n\nThe red cabinet is by the goods lift.\n")

        report = self.reindex()
        self.assertEqual(1, report.changed)
        self.assertGreater(self.store.chunk_count(ALIAS_DUPLICATE), 0)
        self.assertIsNone(self.store.documents[ALIAS_DUPLICATE].get("duplicate_of"))

    def test_the_store_on_disk_is_valid_json_after_every_run(self):
        with open(self.path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        self.assertEqual(sorted(raw), ["chunks", "dim", "documents", "embedder"])
        self.assertFalse(os.path.exists(self.path + ".tmp"), "temp file left behind")

    def test_no_orphan_chunks_survive_a_re_index(self):
        for _ in range(2):
            self.reindex()
        owners = set(self.store.documents)
        for chunk in self.store.chunks:
            self.assertIn(chunk["doc"], owners)
        counted = {}
        for chunk in self.store.chunks:
            counted[chunk["doc"]] = counted.get(chunk["doc"], 0) + 1
        for key, record in self.store.documents.items():
            self.assertEqual(record.get("chunks", 0), counted.get(key, 0))

    def test_a_partially_written_index_is_repaired_on_the_next_run(self):
        # Simulate a crash after the delete half of a delete-then-append: the
        # document record survives with no chunks behind it.
        victim = "handbook/v3/press-line-lockout.md"
        store = VectorStore.load(self.path)
        store.delete_chunks(victim)
        store.documents[victim]["content_hash"] = "interrupted"
        store.save()

        report = self.reindex()
        self.assertEqual(1, report.changed)
        self.assertGreater(self.store.chunk_count(victim), 0)

    def test_the_fingerprint_moves_only_when_the_corpus_moves(self):
        before = self.store.fingerprint()
        self.reindex()
        self.assertEqual(before, self.store.fingerprint())
        with open(self.document("handbook/v3/training-records.md"), "a", encoding="utf-8") as handle:
            handle.write("\nRecords are audited annually.\n")
        self.reindex()
        self.assertNotEqual(before, self.store.fingerprint())


if __name__ == "__main__":
    unittest.main()
