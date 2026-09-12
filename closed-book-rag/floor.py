"""The measured no-answer floor.

A retrieval system needs a cutoff: how far away can the nearest passage be before
the honest answer is "not in the library". Most systems pick that number by feel,
usually 0.3 or 0.7 because it looked about right on a Tuesday, and then it decays
quietly as the corpus grows.

This measures it instead. A labelled probe set of questions the corpus does answer
and questions it does not is run through retrieval, the nearest chunk distance is
recorded for each, and the two distributions are compared. If they separate, the
floor is placed in the gap between them. If they do not separate, calibration
FAILS rather than emitting a number, because a floor that cannot be measured is a
floor that does not exist, and shipping a guess with an error bar of zero is worse
than shipping nothing.

The stored calibration carries the index fingerprint and a hash of the probe set,
so a floor measured against a corpus or probe set that has since changed is
reported as stale instead of being used.
"""

import json
import os

from embed import embed


class FloorNotSeparable(Exception):
    """Raised when on-topic and off-topic probes overlap. There is no honest
    floor to derive, so none is returned."""


class Calibration:
    def __init__(self, floor, on_stats, off_stats, gap, probe_hash, fingerprint, counts):
        self.floor = floor
        self.on_stats = on_stats
        self.off_stats = off_stats
        self.gap = gap
        self.probe_hash = probe_hash
        self.fingerprint = fingerprint
        self.counts = counts

    @property
    def margin(self):
        """Gap as a proportion of the on-topic spread. A larger number means the
        floor sits in a wider no man's land and is less sensitive to one odd
        question."""
        spread = max(self.on_stats["max"] - self.on_stats["min"], 1e-9)
        return self.gap / spread

    def to_dict(self):
        return {
            "floor": self.floor,
            "gap": self.gap,
            "on": self.on_stats,
            "off": self.off_stats,
            "probe_hash": self.probe_hash,
            "fingerprint": self.fingerprint,
            "counts": self.counts,
        }

    @classmethod
    def from_dict(cls, raw):
        return cls(
            floor=raw["floor"],
            on_stats=raw["on"],
            off_stats=raw["off"],
            gap=raw["gap"],
            probe_hash=raw["probe_hash"],
            fingerprint=raw["fingerprint"],
            counts=raw["counts"],
        )


def nearest_distance(store, question):
    """Distance from a question to the closest chunk in the index."""
    hits = store.search(embed(question), k=1)
    return hits[0].distance if hits else 1.0


def summarise(values):
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    median = (
        ordered[middle]
        if count % 2
        else (ordered[middle - 1] + ordered[middle]) / 2.0
    )
    return {
        "n": count,
        "min": round(ordered[0], 4),
        "median": round(median, 4),
        "mean": round(sum(ordered) / count, 4),
        "max": round(ordered[-1], 4),
    }


def calibrate(store, on_topic, off_topic, probe_hash):
    """Measure the floor from labelled probes. Raises FloorNotSeparable when the
    two distributions touch."""
    if not on_topic or not off_topic:
        raise FloorNotSeparable("both an on-topic and an off-topic probe set are required")

    on_values = [nearest_distance(store, question) for question in on_topic]
    off_values = [nearest_distance(store, question) for question in off_topic]

    worst_on = max(on_values)
    best_off = min(off_values)
    gap = best_off - worst_on

    if gap <= 0.0:
        raise FloorNotSeparable(
            "probe distributions overlap: worst on-topic %.4f is not closer than "
            "best off-topic %.4f. No floor can be derived, and guessing one would "
            "hide the overlap rather than fix it." % (worst_on, best_off)
        )

    # Midpoint of the gap: the furthest possible from both failure modes, given
    # only these probes. Equally far from refusing a question the corpus answers
    # and from answering one it does not.
    floor = round(worst_on + gap / 2.0, 4)

    return Calibration(
        floor=floor,
        on_stats=summarise(on_values),
        off_stats=summarise(off_values),
        gap=round(gap, 4),
        probe_hash=probe_hash,
        fingerprint=store.fingerprint(),
        counts={"on": len(on_values), "off": len(off_values)},
    )


def save(calibration, path):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(calibration.to_dict(), handle, sort_keys=True, indent=2)
    os.replace(tmp, path)


def load(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return Calibration.from_dict(json.load(handle))


def staleness(calibration, store, probe_hash):
    """Empty string when the stored floor still describes this index and probe
    set, otherwise a description of what moved."""
    if calibration is None:
        return "no floor has been calibrated yet"
    reasons = []
    if calibration.fingerprint != store.fingerprint():
        reasons.append("the index has changed since the floor was measured")
    if calibration.probe_hash != probe_hash:
        reasons.append("the probe set has changed since the floor was measured")
    return "; ".join(reasons)


def histogram(values, low, high, width=40, mark="#"):
    """A one line scale for the demo output, so the two distributions can be seen
    rather than taken on trust."""
    span = max(high - low, 1e-9)
    cells = [" "] * width
    for value in values:
        position = int(round((value - low) / span * (width - 1)))
        position = min(max(position, 0), width - 1)
        cells[position] = mark
    return "".join(cells)
