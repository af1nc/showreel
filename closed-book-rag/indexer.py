"""Incremental, crash safe indexing.

Four behaviours, each of which exists because the naive version of it caused a
real problem:

  * Content hash keying. A document is re-embedded only when its bytes change.
    Re-indexing an unchanged corpus does no embedding work at all.
  * Supersession filter. A folder that marks itself as superseded (archive, old,
    deprecated and friends) is not indexed. A retrieval system that can reach the
    previous version of a policy will eventually answer from it, and an answer
    from a withdrawn policy is worse than no answer.
  * Duplicate collapse. Two byte identical files filed in two folders are
    embedded once. The second becomes an alias pointing at the first, so it costs
    nothing and cannot push a genuinely different document out of the top-k.
  * Batched commits, delete before append. The store is written every few chunks,
    and a document's old chunks are deleted before its new ones are appended, so
    an interrupted run leaves an index that is behind, never one with orphans.
"""

import hashlib
import os

from chunker import chunk_document
from embed import embed

# Folder names that declare their own contents superseded. Matched case
# insensitively against any path segment below the corpus root.
SUPERSEDED_DIRS = frozenset(
    {
        "archive",
        "archived",
        "old",
        "old-drafts",
        "previous",
        "superseded",
        "deprecated",
        "retired",
        "do-not-use",
    }
)

DOCUMENT_SUFFIXES = (".md", ".txt")

DEFAULT_BATCH_CHUNKS = 24


class IndexReport:
    def __init__(self):
        self.added = 0
        self.changed = 0
        self.skipped = 0
        self.pruned = 0
        self.duplicates = 0
        self.excluded = 0
        self.embedded_chunks = 0
        self.commits = 0

    def line(self):
        return (
            "%d added, %d changed, %d skipped, %d pruned, "
            "%d duplicate collapsed, %d excluded as superseded"
            % (
                self.added,
                self.changed,
                self.skipped,
                self.pruned,
                self.duplicates,
                self.excluded,
            )
        )

    def __repr__(self):
        return "IndexReport(%s)" % self.line()


def is_superseded(relative_path):
    """True when any folder on the path marks itself superseded."""
    parts = relative_path.replace("\\", "/").split("/")[:-1]
    return any(part.lower() in SUPERSEDED_DIRS for part in parts)


def discover(corpus_root, include_superseded=False):
    """Every document under the corpus root as (relative path, absolute path).

    Ordered by folder depth first and then alphabetically, for two reasons: the
    order is identical on every machine, and of two byte identical copies the one
    nearer the top of the tree is reached first. That makes the shallower copy the
    canonical document and the one filed away in a subfolder the alias, which is
    the way round a reader expects to see it cited.
    """
    found = []
    for directory, subdirs, filenames in os.walk(corpus_root):
        subdirs.sort()
        for filename in sorted(filenames):
            if not filename.lower().endswith(DOCUMENT_SUFFIXES):
                continue
            absolute = os.path.join(directory, filename)
            relative = os.path.relpath(absolute, corpus_root).replace("\\", "/")
            if not include_superseded and is_superseded(relative):
                continue
            found.append((relative, absolute))
    found.sort(key=lambda pair: (pair[0].count("/"), pair[0]))
    return found


def read_document(absolute_path):
    """Always explicit UTF-8. The platform default encoding is not the same thing
    on every machine and a corpus is not going to be re-authored per platform."""
    with open(absolute_path, "r", encoding="utf-8") as handle:
        return handle.read()


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def index_corpus(
    store,
    corpus_root,
    include_superseded=False,
    batch_chunks=DEFAULT_BATCH_CHUNKS,
    on_document=None,
):
    """Bring the store in line with the corpus on disk. Returns an IndexReport."""
    report = IndexReport()

    all_files = discover(corpus_root, include_superseded=True)
    if not include_superseded:
        report.excluded = sum(1 for rel, _ in all_files if is_superseded(rel))
    wanted = [pair for pair in all_files if include_superseded or not is_superseded(pair[0])]

    seen_keys = set()
    hash_to_key = {}
    pending = 0

    # Canonical owner of a hash is whichever document already holds chunks for it,
    # so a re-index does not flip which copy of a duplicate pair is the real one.
    for key in sorted(store.documents):
        record = store.documents[key]
        if not record.get("duplicate_of") and record.get("content_hash"):
            hash_to_key.setdefault(record["content_hash"], key)

    for relative, absolute in wanted:
        key = relative
        seen_keys.add(key)
        text = read_document(absolute)
        digest = content_hash(text)
        existing = store.get_document(key)

        canonical = hash_to_key.get(digest)
        if canonical is not None and canonical != key:
            # Byte identical to a document already indexed. Record the alias and
            # embed nothing.
            if existing and existing.get("duplicate_of") == canonical:
                report.skipped += 1
            else:
                store.delete_chunks(key)
                store.put_document(
                    key,
                    {
                        "name": os.path.basename(relative),
                        "path": relative,
                        "content_hash": digest,
                        "duplicate_of": canonical,
                        "chunks": 0,
                    },
                )
                report.duplicates += 1
                pending += 1
            if on_document:
                on_document(relative, "duplicate")
            continue

        if existing and existing.get("content_hash") == digest and not existing.get("duplicate_of"):
            report.skipped += 1
            hash_to_key.setdefault(digest, key)
            if on_document:
                on_document(relative, "skipped")
            continue

        chunks = chunk_document(text, name=os.path.basename(relative))
        vectors = [embed(chunk) for chunk in chunks]
        store.replace_chunks(key, chunks, vectors)
        store.put_document(
            key,
            {
                "name": os.path.basename(relative),
                "path": relative,
                "content_hash": digest,
                "chunks": len(chunks),
            },
        )
        hash_to_key.setdefault(digest, key)
        report.embedded_chunks += len(chunks)
        if existing:
            report.changed += 1
        else:
            report.added += 1
        if on_document:
            on_document(relative, "changed" if existing else "added")

        pending += len(chunks)
        if pending >= batch_chunks:
            store.save()
            report.commits += 1
            pending = 0

    # Prune anything the corpus no longer contains, including documents that have
    # just moved into a superseded folder.
    for key in sorted(set(store.documents) - seen_keys):
        store.delete_document(key)
        report.pruned += 1
        pending += 1
        if on_document:
            on_document(key, "pruned")

    # Any alias whose canonical document has gone is promoted back to a real
    # document on the next run, because its recorded hash no longer matches.
    for key in sorted(store.documents):
        record = store.documents[key]
        target = record.get("duplicate_of")
        if target and target not in store.documents:
            record.pop("duplicate_of", None)
            record["content_hash"] = "orphaned-alias"

    store.save()
    report.commits += 1
    return report


def resolve_alias(store, doc_key):
    """Follow a duplicate alias to the document that actually holds the chunks."""
    record = store.get_document(doc_key) or {}
    target = record.get("duplicate_of")
    return target if target else doc_key
