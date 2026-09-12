"""Heading aware chunks with overlap.

A handbook is already chunked by the person who wrote it: each "## " section is
one topic, written to be read on its own. Cutting blind word windows across those
boundaries mixes two topics into one vector and blurs both, and it was measurable
here: with blind windows, "what happens if a micrometer is dropped" retrieved a
permits document, because the window that held the word "dropped" also held a lot
of unrelated text.

So sections are the unit. A section longer than the cap is split into overlapping
windows, so a sentence that straddles a cut still appears whole in one of the two
neighbours. Every chunk carries the document title and the section heading, since
a chunk lifted out of the middle of a document otherwise loses the one piece of
context that says what it is about.
"""

import re

MAX_CHUNK_WORDS = 90
OVERLAP_WORDS = 25

_H1_RE = re.compile(r"^#\s+(.*)$", re.MULTILINE)
_WS_RE = re.compile(r"[ \t]+")


def title_of(text, fallback=""):
    """The first level one markdown heading, or the fallback."""
    match = _H1_RE.search(text)
    return match.group(1).strip() if match else fallback


def normalise(text):
    """Collapse runs of spaces and repeated blank lines, keep line structure."""
    lines = [_WS_RE.sub(" ", line).strip() for line in text.splitlines()]
    out = []
    for line in lines:
        if not line and out and not out[-1]:
            continue
        out.append(line)
    return "\n".join(out).strip()


def split_sections(text):
    """[(heading or None, body text)] in document order."""
    sections = []
    heading = None
    buffer = []
    for line in text.splitlines():
        if line.startswith("## "):
            if any(buffer):
                sections.append((heading, "\n".join(buffer).strip()))
            heading = line[3:].strip()
            buffer = []
        elif line.startswith("# "):
            continue
        else:
            buffer.append(line)
    if any(buffer):
        sections.append((heading, "\n".join(buffer).strip()))
    return sections


def chunk_document(
    text, name, max_words=MAX_CHUNK_WORDS, overlap_words=OVERLAP_WORDS
):
    """Split one document into chunks, each prefixed with its context header."""
    if overlap_words >= max_words:
        raise ValueError("overlap must be smaller than the chunk size")

    body = normalise(text)
    title = title_of(body, fallback=name)
    chunks = []

    for heading, section in split_sections(body):
        section = section.strip()
        if not section:
            continue
        header = "# " + title
        if heading:
            header += "\n## " + heading
        words = section.split()
        if len(words) <= max_words:
            chunks.append(header + "\n" + section)
            continue
        step = max_words - overlap_words
        start = 0
        while start < len(words):
            window = " ".join(words[start : start + max_words])
            chunks.append(header + "\n" + window)
            if start + max_words >= len(words):
                break
            start += step
    return chunks
