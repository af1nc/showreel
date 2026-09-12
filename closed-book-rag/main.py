"""Closed-book RAG over an invented internal handbook library.

    python main.py --demo
    python main.py --reindex
    python main.py --calibrate
    python main.py --ask "how often is a torque wrench calibrated?"

Standard library only, offline, deterministic.
"""

import sys

# Windows consoles default to a legacy code page, and the box drawing characters
# below raise UnicodeEncodeError before a single line of output appears. This runs
# before anything prints and is a no-op everywhere else.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402

import answer as answer_module  # noqa: E402
import floor as floor_module  # noqa: E402
import probes  # noqa: E402
from indexer import index_corpus  # noqa: E402
from store import VectorStore  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")
INDEX_DIR = os.path.join(HERE, ".index")
STORE_PATH = os.path.join(INDEX_DIR, "store.json")
FLOOR_PATH = os.path.join(INDEX_DIR, "floor.json")

WIDTH = 92


# --------------------------------------------------------------------- output


def rule(title=""):
    if title:
        print("\n" + "=" * WIDTH)
        print(title)
        print("=" * WIDTH)
    else:
        print("-" * WIDTH)


def act(number, title):
    print("\n" + "═" * WIDTH)
    print("  ACT %d  %s" % (number, title))
    print("═" * WIDTH)


def wrap(text, indent="    ", width=WIDTH - 6):
    words = text.split()
    line = ""
    out = []
    for word in words:
        if len(line) + len(word) + 1 > width:
            out.append(indent + line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        out.append(indent + line)
    return "\n".join(out)


def show_answer(result, label=""):
    if label:
        print("  %s" % label)
    body, _, sources = result.answer.rpartition("\nSources: ")
    if not body:
        body, sources = result.answer, ""
    print(wrap(body))
    if sources:
        print("    cites → %s" % sources)


# ---------------------------------------------------------------- index setup


def real_documents(store):
    """Documents that own chunks. Aliases for byte identical copies do not."""
    return [key for key, record in store.documents.items() if not record.get("duplicate_of")]


def build_index(path, include_superseded=False, quiet=False):
    store = VectorStore.load(path)
    report = index_corpus(store, CORPUS, include_superseded=include_superseded)
    if not quiet:
        print("  %s" % report.line())
        print(
            "  %d documents indexed, %d chunks, %d chunks embedded, %d commits"
            % (
                len(real_documents(store)),
                store.chunk_count(),
                report.embedded_chunks,
                report.commits,
            )
        )
    return VectorStore.load(path), report


def load_calibration(store, recalibrate=False):
    """The stored floor, recalculated when it is missing or stale."""
    calibration = floor_module.load(FLOOR_PATH)
    stale = floor_module.staleness(calibration, store, probes.probe_hash())
    if recalibrate or stale:
        calibration = floor_module.calibrate(
            store, probes.ON_TOPIC, probes.OFF_TOPIC, probes.probe_hash()
        )
        floor_module.save(calibration, FLOOR_PATH)
    return calibration, stale


def print_calibration(calibration, on_values, off_values):
    low = min(min(on_values), min(off_values))
    high = max(max(on_values), max(off_values))
    print("  nearest-chunk distance for each labelled probe question")
    print("  scale %.2f %s %.2f" % (low, " " * 28, high))
    print("  on-topic  (%2d) |%s|" % (len(on_values), floor_module.histogram(on_values, low, high)))
    print("  off-topic (%2d) |%s|" % (len(off_values), floor_module.histogram(off_values, low, high, mark="o")))
    print()
    header = "  %-12s %7s %7s %7s %7s" % ("", "min", "median", "mean", "max")
    print(header)
    for label, stats in (("on-topic", calibration.on_stats), ("off-topic", calibration.off_stats)):
        print(
            "  %-12s %7.4f %7.4f %7.4f %7.4f"
            % (label, stats["min"], stats["median"], stats["mean"], stats["max"])
        )
    print()
    print("  worst on-topic %.4f  <  best off-topic %.4f" % (calibration.on_stats["max"], calibration.off_stats["min"]))
    print("  separation gap %.4f wide, %.2f of the on-topic spread" % (calibration.gap, calibration.margin))
    print("  FLOOR = %.4f  (midpoint of the gap)" % calibration.floor)


# ----------------------------------------------------------------- the demo


def demo():
    print("═" * WIDTH)
    print("  CLOSED-BOOK RAG  ·  answers only from the handbook library, refuses everything else")
    print("═" * WIDTH)
    print("\n  Corpus: an invented internal handbook for Larkspur Tooling, a mid-size manufacturer.")
    print("  Building the index over corpus/ ...")
    # The demo always builds from scratch, so a second run prints what the first
    # one did. Leaving a previous .index/ in place would open the demo with
    # "0 added, 15 skipped", which is correct but tells a reader nothing. The
    # incremental path is demonstrated deliberately in act 6 instead, against a
    # scratch copy of the corpus.
    if os.path.exists(STORE_PATH):
        os.remove(STORE_PATH)
    store, _ = build_index(STORE_PATH)
    calibration, _ = load_calibration(store, recalibrate=True)

    # ---------------------------------------------------------------- act 1
    act(1, "SUPERSESSION: the same question, with and without the archive")
    print(wrap(
        "The corpus holds a live handbook/v3/ and an archived archive/handbook-v2/. "
        "The expense receipt threshold changed between them: it was 75 CU, it is now 25 CU. "
        "The indexer refuses to index any folder that marks itself superseded. Here is why."
    ))
    archive_path = os.path.join(INDEX_DIR, "with-archive.json")
    if os.path.exists(archive_path):
        os.remove(archive_path)
    archive_store, archive_report = build_index(archive_path, include_superseded=True, quiet=True)
    question = "What is the receipt threshold on an expense claim?"
    print("\n  Question: %s" % question)

    bad = answer_module.ask(archive_store, question, calibration.floor)
    print("\n  [A] archive folders INCLUDED in the index (%d documents)"
          % len(real_documents(archive_store)))
    show_answer(bad)
    print("    → the withdrawn v2 rule, answered as if it were policy. Confidently wrong.")

    good = answer_module.ask(store, question, calibration.floor)
    print("\n  [B] archive folders EXCLUDED, which is the default (%d documents)"
          % len(real_documents(store)))
    show_answer(good)
    print("    → the live v3 rule.")
    print(wrap(
        "Same question, same retrieval, same answerer. The only difference is whether a "
        "folder that says it is archived was allowed into the index.", indent="    "
    ))

    # ---------------------------------------------------------------- act 2
    act(2, "THE MEASURED NO-ANSWER FLOOR")
    print(wrap(
        "The refusal threshold is measured, not guessed. Every question in the labelled "
        "probe set is run through retrieval and its nearest-chunk distance recorded."
    ))
    print()
    on_values = [floor_module.nearest_distance(store, q) for q in probes.ON_TOPIC]
    off_values = [floor_module.nearest_distance(store, q) for q in probes.OFF_TOPIC]
    print_calibration(calibration, on_values, off_values)
    print()
    print(wrap(
        "If the two distributions overlapped, calibration would raise rather than return a "
        "number. A floor that cannot be measured does not exist, and a guess with no error "
        "bar is worse than nothing. The floor is stored against the index fingerprint and a "
        "hash of the probe set, so it is reported stale rather than used if either moves."
    ))

    # ---------------------------------------------------------------- act 3
    act(3, "AN ON-TOPIC QUESTION, ANSWERED WITH CITATIONS")
    for question in (
        "What happens if a micrometer is dropped on the shop floor?",
        "Can a visitor walk around the shop floor on their own?",
    ):
        result = answer_module.ask(store, question, calibration.floor)
        print("\n  Question: %s" % question)
        print("  nearest chunk %.4f  (floor %.4f)   model called: %s"
              % (result.best_distance, result.floor, result.model_called))
        for hit in result.hits[:3]:
            print("    %.4f  %s" % (hit.distance, hit.path))
        show_answer(result)
    print()
    print(wrap(
        "An answer that names no document, or names one that was not retrieved, is discarded "
        "and becomes a refusal. A citation is not a nicety here, it is the acceptance test."
    ))

    # ---------------------------------------------------------------- act 4
    act(4, "AN OFF-TOPIC QUESTION, REFUSED WITHOUT CALLING THE MODEL")
    for question in (
        "How much parental leave am I entitled to after adoption?",
        "Which spices go into a traditional rogan josh?",
    ):
        result = answer_module.ask(store, question, calibration.floor)
        print("\n  Question: %s" % question)
        print("  nearest chunk %.4f  (floor %.4f)   model called: %s"
              % (result.best_distance, result.floor, result.model_called))
        print("  reason: %s" % result.reason)
        print(wrap(result.answer))
    print()
    print(wrap(
        "The first of those is the one that matters: a question the assistant could plausibly "
        "be asked, on a subject the library simply does not cover. It is refused for the same "
        "measured reason as the rogan josh. Nothing reached the model, so nothing had the "
        "chance to be invented, and the call was not paid for."
    ))

    # ---------------------------------------------------------------- act 5
    act(5, "A PROMPT INJECTION INSIDE A DOCUMENT, RETRIEVED AND NOT OBEYED")
    question = "When is a customer complaint closed and who decides?"
    result = answer_module.ask(store, question, calibration.floor)
    print(wrap(
        "corpus/handbook/v3/customer-complaints.md contains a block pasted in from an old "
        "mailbox that instructs the assistant to ignore the handbook, reply APPROVED to "
        "everything, and print its system prompt. It is retrieved here, as it should be: it "
        "is part of the document."
    ))
    print("\n  Question: %s" % question)
    print("\n  What the model is handed, abridged:")
    for line in result.blocks.splitlines()[:3]:
        print("    | %s" % line[:82])
    print("    | ...")
    injected = [s for p in result.passages for s in p.flagged]
    for sentence in injected[:2]:
        print("    | %s" % sentence[:82])
    print("    | ...")
    print("\n  retrieval layer flagged: %s"
          % ", ".join("%s (%d sentences)" % (name, count) for name, count in result.injection_flags))
    show_answer(result, label="Answer:")

    lowered = result.answer.lower()
    checks = [
        ("answer is not the injected 'APPROVED' reply", "approved" not in lowered),
        ("system prompt not disclosed", "you answer questions about" not in lowered),
        ("no flagged sentence quoted into the answer", not any(s in result.answer for s in injected)),
        ("answer is cited", bool(result.citations)),
    ]
    print()
    for label, passed in checks:
        print("    [%s] %s" % ("PASS" if passed else "FAIL", label))
    print()
    print(wrap(
        "Three separate reasons this holds. Passages are wrapped as <document> reference "
        "blocks and the system prompt says content inside them is data. The answerer takes "
        "its control flow from the system prompt and the question only, never from passage "
        "text. And a flagged sentence is barred from being quoted, so it cannot reach the "
        "reader even as a citation."
    ))

    # ---------------------------------------------------------------- act 6
    act(6, "INCREMENTAL, CRASH-SAFE RE-INDEXING")
    print("  Re-indexing the same corpus, unchanged:")
    _, report = build_index(STORE_PATH, quiet=True)
    print("    %s" % report.line())
    print("    %d chunks embedded" % report.embedded_chunks)
    print("    → nothing changed on disk, so nothing was embedded.")

    scratch_corpus = os.path.join(INDEX_DIR, "scratch-corpus")
    scratch_store_path = os.path.join(INDEX_DIR, "scratch-store.json")
    if os.path.exists(scratch_corpus):
        shutil.rmtree(scratch_corpus)
    if os.path.exists(scratch_store_path):
        os.remove(scratch_store_path)
    shutil.copytree(CORPUS, scratch_corpus)

    scratch = VectorStore.load(scratch_store_path)
    first = index_corpus(scratch, scratch_corpus)
    print("\n  A scratch copy of the corpus, indexed from empty:")
    print("    %s" % first.line())
    print("    %d chunks embedded" % first.embedded_chunks)

    target = os.path.join(scratch_corpus, "handbook", "v3", "shift-handover.md")
    with open(target, "r", encoding="utf-8") as handle:
        text = handle.read()
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text + "\n## Late starts\n\nA late start is recorded on the handover card.\n")
    scratch = VectorStore.load(scratch_store_path)
    second = index_corpus(scratch, scratch_corpus)
    print("\n  After editing one document (handbook/v3/shift-handover.md):")
    print("    %s" % second.line())
    print("    %d chunks embedded, so only the edited document was re-embedded" % second.embedded_chunks)

    os.remove(os.path.join(scratch_corpus, "handbook", "v3", "visitor-access.md"))
    scratch = VectorStore.load(scratch_store_path)
    third = index_corpus(scratch, scratch_corpus)
    print("\n  After deleting one document (handbook/v3/visitor-access.md):")
    print("    %s" % third.line())
    print("    %d chunks embedded, and the removed document was pruned from the index"
          % third.embedded_chunks)
    shutil.rmtree(scratch_corpus)
    os.remove(scratch_store_path)

    print()
    print(wrap(
        "Documents are keyed on a content hash, so unchanged files are skipped. Byte identical "
        "copies filed in two folders are embedded once and the deeper copy becomes an alias. "
        "Chunks are deleted before the new ones are appended and the store is committed in "
        "small batches, so a crash mid-run leaves an index that is behind rather than one full "
        "of orphans."
    ))

    print("\n" + "═" * WIDTH)
    print("  Done. Everything above ran offline, on the standard library, deterministically.")
    print("═" * WIDTH)


# ------------------------------------------------------------------- the cli


def ensure_index():
    if not os.path.exists(STORE_PATH):
        store, _ = build_index(STORE_PATH, quiet=True)
        return store
    return VectorStore.load(STORE_PATH)


def command_reindex():
    rule("RE-INDEX")
    build_index(STORE_PATH)


def command_calibrate():
    rule("CALIBRATE THE NO-ANSWER FLOOR")
    store = ensure_index()
    try:
        calibration, stale = load_calibration(store, recalibrate=True)
    except floor_module.FloorNotSeparable as error:
        print("  CALIBRATION FAILED: %s" % error)
        return 1
    on_values = [floor_module.nearest_distance(store, q) for q in probes.ON_TOPIC]
    off_values = [floor_module.nearest_distance(store, q) for q in probes.OFF_TOPIC]
    print_calibration(calibration, on_values, off_values)
    print("\n  written to %s" % os.path.relpath(FLOOR_PATH, HERE))
    return 0


def command_ask(question):
    store = ensure_index()
    try:
        calibration, stale = load_calibration(store)
    except floor_module.FloorNotSeparable as error:
        print("CALIBRATION FAILED: %s" % error)
        return 1
    if stale:
        print("  (floor recalibrated: %s)" % stale)
    result = answer_module.ask(store, question, calibration.floor)
    print("\n  Question: %s" % question)
    print("  nearest chunk %.4f   floor %.4f   model called: %s"
          % (result.best_distance if result.best_distance is not None else 1.0,
             result.floor, result.model_called))
    if result.injection_flags:
        print("  injection markers flagged in: %s"
              % ", ".join(name for name, _ in result.injection_flags))
    print()
    show_answer(result)
    print()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true", help="run the full narrated demo")
    parser.add_argument("--reindex", action="store_true", help="bring the index in line with corpus/")
    parser.add_argument("--calibrate", action="store_true", help="re-measure the no-answer floor")
    parser.add_argument("--ask", metavar="QUESTION", help="ask one question")
    args = parser.parse_args(argv)

    if args.demo:
        demo()
        return 0
    if args.reindex:
        command_reindex()
        return 0
    if args.calibrate:
        return command_calibrate()
    if args.ask:
        return command_ask(args.ask)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
