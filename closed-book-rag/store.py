"""JSON backed vector store with cosine top-k search.

A real deployment would put this in a vector database. The interface here is the
one that matters: documents keyed on a stable id, chunks owned by a document,
whole document replacement, pruning, and a top-k search. Nothing above this file
knows how it is stored.

Two properties are deliberate:

  * Writes are atomic. The store serialises to a temporary file in the same
    directory and then os.replace() over the live file, which is atomic on POSIX
    and on Windows. A crash mid write leaves the previous complete index, never a
    half written one.
  * The file is deterministic. Keys are sorted and floats are rounded to a fixed
    precision, so two runs over the same corpus produce identical bytes.
"""

import hashlib
import json
import os

from embed import DIM, EMBEDDER_VERSION, distance

FLOAT_PRECISION = 6


class Hit:
    """One retrieved chunk."""

    __slots__ = ("doc_key", "doc_name", "path", "text", "ordinal", "distance")

    def __init__(self, doc_key, doc_name, path, text, ordinal, distance):
        self.doc_key = doc_key
        self.doc_name = doc_name
        self.path = path
        self.text = text
        self.ordinal = ordinal
        self.distance = distance

    def __repr__(self):
        return "Hit(%s#%d, distance=%.4f)" % (self.doc_name, self.ordinal, self.distance)


class VectorStore:
    def __init__(self, path, dim=DIM):
        self.path = path
        self.dim = dim
        self.embedder = EMBEDDER_VERSION
        self.documents = {}
        self.chunks = []

    # ------------------------------------------------------------------ io

    @classmethod
    def load(cls, path, dim=DIM):
        store = cls(path, dim=dim)
        if not os.path.exists(path):
            return store
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if raw.get("embedder") != EMBEDDER_VERSION or raw.get("dim") != dim:
            # Vectors from a different embedder are not comparable with new ones.
            # Start clean rather than mix them.
            return store
        store.documents = raw.get("documents", {})
        store.chunks = raw.get("chunks", [])
        return store

    def save(self):
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        payload = {
            "embedder": self.embedder,
            "dim": self.dim,
            "documents": self.documents,
            "chunks": self.chunks,
        }
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        os.replace(tmp, self.path)

    # ----------------------------------------------------------- documents

    def put_document(self, key, record):
        self.documents[key] = record

    def get_document(self, key):
        return self.documents.get(key)

    def document_keys(self):
        return sorted(self.documents)

    def replace_chunks(self, doc_key, texts, vectors):
        """Delete every chunk this document owns, then append the new ones.

        Delete before append, never the other way round, and never an in place
        edit. If the process dies between the two, the document simply has no
        chunks and the next run sees a content hash mismatch and redoes it. The
        opposite order would leave duplicated chunks that nothing ever cleans up.
        """
        self.delete_chunks(doc_key)
        for ordinal, (text, vector) in enumerate(zip(texts, vectors)):
            self.chunks.append(
                {
                    "doc": doc_key,
                    "ord": ordinal,
                    "text": text,
                    "vec": [round(v, FLOAT_PRECISION) for v in vector],
                }
            )

    def delete_chunks(self, doc_key):
        self.chunks = [c for c in self.chunks if c["doc"] != doc_key]

    def delete_document(self, doc_key):
        self.delete_chunks(doc_key)
        self.documents.pop(doc_key, None)

    def chunk_count(self, doc_key=None):
        if doc_key is None:
            return len(self.chunks)
        return sum(1 for c in self.chunks if c["doc"] == doc_key)

    # -------------------------------------------------------------- search

    def search(self, query_vector, k=8):
        """Top-k chunks by cosine distance, ascending. Ties break on document key
        then chunk ordinal so the result is stable across runs."""
        scored = []
        for chunk in self.chunks:
            scored.append(
                (distance(query_vector, chunk["vec"]), chunk["doc"], chunk["ord"], chunk)
            )
        scored.sort(key=lambda row: (row[0], row[1], row[2]))
        hits = []
        for dist, doc_key, ordinal, chunk in scored[:k]:
            document = self.documents.get(doc_key, {})
            hits.append(
                Hit(
                    doc_key=doc_key,
                    doc_name=document.get("name", doc_key),
                    path=document.get("path", doc_key),
                    text=chunk["text"],
                    ordinal=ordinal,
                    distance=dist,
                )
            )
        return hits

    # --------------------------------------------------------- fingerprint

    def fingerprint(self):
        """Identifies the exact content of this index.

        The calibrated floor is stored against this value. Change the corpus and
        the fingerprint changes, which marks the stored floor stale rather than
        letting a number measured against a different corpus keep being used.
        """
        digest = hashlib.sha256()
        digest.update(EMBEDDER_VERSION.encode("utf-8"))
        digest.update(str(self.dim).encode("utf-8"))
        for key in sorted(self.documents):
            record = self.documents[key]
            digest.update(key.encode("utf-8"))
            digest.update(str(record.get("content_hash", "")).encode("utf-8"))
            digest.update(str(record.get("duplicate_of", "")).encode("utf-8"))
        return digest.hexdigest()[:16]
