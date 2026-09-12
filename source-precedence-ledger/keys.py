"""Work order key normalisation, plus the guard that stops a careless rule
folding two genuinely different work orders into one.

Three systems spell the same work order three different ways:

    WO-4471        WO 4471 (rev2)        wo4471

They are one job. Compared literally they are three jobs, so the ledger would
publish three figures for one piece of work. Normalisation is therefore the
first thing that happens to every input row.

The temptation is to normalise hard enough that everything matches. That is the
trap. WO-4471 and WO-4471-B are different jobs at the same site, and a rule that
strips "a trailing letter, probably a revision" merges them and silently loses
one of them. This module normalises conservatively and then proves what a more
aggressive rule would have destroyed.
"""

from dataclasses import dataclass
from typing import Iterable, Sequence

# Suffixes we are prepared to treat as a revision marker, longest first so that
# "revision2" is not mistaken for a bare "v" plus junk. A bare "r" is NOT in the
# list: "wo88r2" is more likely a room number than revision 2, and guessing
# wrong here costs a whole line.
REVISION_MARKERS = ("revision", "rev", "v")


def squash(raw: str) -> str:
    """Lowercase, keep alphanumerics only. 'WO 4471 (rev2)' -> 'wo4471rev2'."""
    return "".join(ch for ch in raw.lower() if ch.isalnum())


def strip_revision(key: str) -> str:
    """Remove a trailing revision marker plus its number: 'wo4471rev2' -> 'wo4471'.

    Only fires when the marker is spelled out. A key ending in digits alone
    ('wo4471') keeps every digit: those digits are the work order number.
    """
    cut = len(key)
    while cut > 0 and key[cut - 1].isdigit():
        cut -= 1
    if cut == len(key):
        return key  # no trailing number, so no revision suffix
    stem = key[:cut]
    for marker in REVISION_MARKERS:
        if stem.endswith(marker) and len(stem) > len(marker):
            return stem[: -len(marker)]
    return key


def canonical(raw: str) -> str:
    """The join key the ledger actually uses."""
    return strip_revision(squash(raw))


def careless(raw: str) -> str:
    """The normalisation someone reaches for when a few lines will not join:
    canonical, and then drop a trailing letter that follows a digit on the
    assumption it is a revision letter.

    Kept in the codebase on purpose, never used to key the book. It exists so
    find_collisions can report exactly what it would have merged.
    """
    key = canonical(raw)
    if len(key) > 1 and key[-1].isalpha() and key[-2].isdigit():
        return key[:-1]
    return key


@dataclass(frozen=True)
class KeyedRow:
    """The minimum a row needs for key work: where it came from and what it is."""

    source: str
    raw_code: str
    site: str
    category: str

    @property
    def key(self) -> str:
        return canonical(self.raw_code)


@dataclass(frozen=True)
class Collision:
    """Two or more distinct work orders that a careless rule would merge."""

    careless_key: str
    keys: tuple
    evidence: str

    def describe(self) -> str:
        joined = " + ".join(self.keys)
        return "'{0}' would merge {1} ({2})".format(self.careless_key, joined, self.evidence)


def group_raw_codes(rows: Iterable[KeyedRow]) -> dict:
    """canonical key -> sorted tuple of the raw spellings that fed it."""
    seen: dict = {}
    for row in rows:
        seen.setdefault(row.key, set()).add(row.raw_code)
    return {key: tuple(sorted(raws)) for key, raws in sorted(seen.items())}


def find_collisions(rows: Sequence[KeyedRow]) -> list:
    """Report every place the careless rule would have merged distinct keys.

    The guard is not a warning printed next to a merge that happened anyway. The
    book is keyed on canonical(), so the merge never happens. This function is
    the proof: it names the keys that stayed apart and the attribute that shows
    they are different jobs.
    """
    buckets: dict = {}
    for row in rows:
        buckets.setdefault(careless(row.raw_code), {}).setdefault(row.key, set()).add(
            (row.site, row.category)
        )

    collisions = []
    for careless_key, by_key in sorted(buckets.items()):
        if len(by_key) < 2:
            continue
        keys = tuple(sorted(by_key))
        categories = {cat for attrs in by_key.values() for (_site, cat) in attrs}
        sites = {site for attrs in by_key.values() for (site, _cat) in attrs}
        if len(categories) > 1:
            evidence = "different categories: " + ", ".join(sorted(categories))
        elif len(sites) > 1:
            evidence = "different sites: " + ", ".join(sorted(sites))
        else:
            evidence = "same site and category, still separately numbered"
        collisions.append(Collision(careless_key=careless_key, keys=keys, evidence=evidence))
    return collisions
