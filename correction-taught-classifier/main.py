"""A classifier that learns from being told off — without retraining.

Documents flow in; a classifier labels them; sometimes a human corrects one. Most
systems drop that correction into a log and keep making the same mistake until the
next fine-tune. This one turns every correction into teaching, immediately:

  1. each correction is stored with an embedding of the text it corrected
  2. new documents retrieve their most-similar past corrections (cosine similarity)
  3. a similarity floor keeps loose matches out — noise teaches nothing
  4. surviving examples are injected into the prompt AFTER the stable prefix, so an
     LLM's prompt cache keeps hitting on everything that never changes
  5. a near-exact match (>0.85) boosts confidence — the household has already taught
     this exact pattern, so stop second-guessing it

The demo uses a deterministic character-n-gram embedding and a nearest-centroid
"model" so the whole loop runs offline — the mechanism is the point, and it is
identical with a real embedding model and a real LLM behind it.

Run:  python main.py --demo        (stdlib only)
"""

from __future__ import annotations

import hashlib
import math
import sys
from dataclasses import dataclass, field

SIM_FLOOR = 0.70   # below this, a past correction is noise, not signal
BOOST_AT = 0.85    # above this, the pattern is known — boost confidence
DIMS = 256


# ---------------------------------------------------------------------------
# 1. Embeddings: deterministic char-trigram hashing. Swappable for a real model;
#    the retrieval, floor, and boost logic neither knows nor cares.
# ---------------------------------------------------------------------------

def embed(text: str) -> list[float]:
    v = [0.0] * DIMS
    t = f"  {text.lower()}  "
    for i in range(len(t) - 3):
        gram = t[i : i + 3]
        h = int(hashlib.md5(gram.encode()).hexdigest()[:8], 16)
        v[h % DIMS] += 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# 2. The correction store — the system's memory of being wrong.
# ---------------------------------------------------------------------------

@dataclass
class Correction:
    excerpt: str
    wrong: str
    right: str
    vector: list[float]


@dataclass
class ClassifierWithMemory:
    labels: tuple[str, ...] = ("receipt", "invoice", "newsletter", "travel")
    corrections: list[Correction] = field(default_factory=list)

    # -- the "model": nearest centroid over seed examples ------------------
    SEEDS = {
        "receipt": ["order confirmed thank you for your purchase total paid card ending"],
        "invoice": ["invoice number due date amount due payment terms bank transfer"],
        "newsletter": ["this week in unsubscribe view in browser our latest stories"],
        "travel": ["booking reference departure gate boarding pass itinerary flight"],
    }

    def __post_init__(self) -> None:
        self._centroids = {k: embed(v[0]) for k, v in self.SEEDS.items()}

    def _retrieve(self, vector: list[float]) -> list[tuple[float, Correction]]:
        scored = sorted(
            ((cosine(vector, c.vector), c) for c in self.corrections),
            key=lambda x: -x[0],
        )
        return [(s, c) for s, c in scored[:3] if s >= SIM_FLOOR]

    def classify(self, text: str) -> tuple[str, float, list[str]]:
        """Returns (label, confidence, prompt_log) — the log shows what an LLM
        would have been shown, cache-stable prefix first."""
        vector = embed(text)
        fewshot = self._retrieve(vector)

        # Prompt assembly order is the cache trick: stable prefix, THEN examples.
        prompt_log = ["[stable prefix] You label household documents…"]
        for sim, c in fewshot:
            prompt_log.append(
                f"[few-shot sim={sim:.2f}] previously corrected "
                f"'{c.excerpt[:34]}…': {c.wrong} → {c.right}"
            )

        # Few-shot examples outvote the base model where they apply.
        if fewshot:
            votes: dict[str, float] = {}
            for sim, c in fewshot:
                votes[c.right] = votes.get(c.right, 0.0) + sim
            label = max(votes, key=lambda k: votes[k])
            confidence = 0.62 + 0.1 * len(fewshot)
        else:
            scores = {k: cosine(vector, cv) for k, cv in self._centroids.items()}
            label = max(scores, key=lambda k: scores[k])
            confidence = 0.55 + max(scores.values()) * 0.3

        if fewshot and fewshot[0][0] > BOOST_AT:
            confidence = min(confidence + 0.05, 0.95)
            prompt_log.append(f"[boost] near-exact teaching match → +0.05 confidence")

        return label, round(confidence, 2), prompt_log

    def correct(self, text: str, wrong: str, right: str) -> None:
        self.corrections.append(Correction(text, wrong, right, embed(text)))


# ---------------------------------------------------------------------------
# Demo: the same mistake, made once.
# ---------------------------------------------------------------------------

def demo() -> None:
    clf = ClassifierWithMemory()

    # School mail reads like a newsletter to a base model — but this household
    # needs fee reminders filed as invoices, because money leaves when they arrive.
    school_fee = (
        "TERM 2 FEE REMINDER — a note from the school office. Tuition for the "
        "spring term is due this week. Our latest term dates are in this update."
    )
    school_fee_2 = (
        "TERM 3 FEE REMINDER — a note from the school office. Tuition for the "
        "autumn term is due this week. Our latest term dates are in this update."
    )
    flight = "Your booking reference ABC123 — departure 08:40, gate closes 08:10."

    print("— day 1: a school fee reminder arrives —")
    label, conf, log = clf.classify(school_fee)
    for line in log:
        print("   ", line)
    print(f"    verdict: {label} ({conf}) — WRONG: money leaves when these arrive\n")

    print("— the human corrects it: invoice —")
    clf.correct(school_fee, wrong=label, right="invoice")

    print("\n— day 30: the next term's reminder arrives (different words, same shape) —")
    label, conf, log = clf.classify(school_fee_2)
    for line in log:
        print("   ", line)
    print(f"    verdict: {label} ({conf}) — taught, not retrained\n")

    print("— an unrelated document is NOT dragged toward the correction —")
    label, conf, log = clf.classify(flight)
    for line in log:
        print("   ", line)
    print(f"    verdict: {label} ({conf}) — the similarity floor held the boundary")


if __name__ == "__main__":
    if "--demo" not in sys.argv:
        print(__doc__)
        sys.exit(0)
    demo()
