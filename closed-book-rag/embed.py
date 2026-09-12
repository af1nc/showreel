"""Deterministic hashed character n-gram embedder, standard library only.

This is a STAND-IN for a real sentence embedding model. It exists so the whole
project runs offline, with no install, no download and no API key, and so that
every run produces byte-identical vectors.

What it does preserve from a real embedder:
  * a fixed dimensional dense vector per text,
  * cosine similarity as the distance metric,
  * graded similarity rather than exact match (shared word stems and shared
    character n-grams pull two texts together),
  * a stable, order independent representation.

What it does NOT preserve:
  * semantics. "out of calibration" and "past its due date" are near synonyms to
    a trained model and near strangers here. This embedder is lexical.
  * any notion of negation, paraphrase, or word order beyond adjacent bigrams.

Everything downstream (chunking, the store, the calibrated floor, the answer
wrapper) is written against the vector interface, not against this file, so
swapping in a real embedder is a one function change plus a re-index.
"""

import hashlib
import math
import re

# Bump when the feature extraction changes. The store records it so a stale
# index cannot be silently mixed with vectors from a different embedder.
EMBEDDER_VERSION = "hashed-ngram-stem-1"

DIM = 512

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Dropped entirely: these tokens contribute neither word nor n-gram features.
# Leaving them in would let two texts look similar purely because both are
# written in English.
STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those there here
    is are was were be been being am do does did doing done
    have has had having will would shall should can could may might must
    of in on at to for from by with without within into onto over under
    as it its it's they them their we us our you your i me my he she his her
    not no nor only own same so too very s t just now also any each few more most
    other some such about after again against all before below between both during
    further how what when where which who whom why
    """.split()
)

_NGRAM_SIZES = (4, 5)

# Feature weights, chosen by measuring probe separation rather than by taste.
# Whole word stems carry the topic and get most of the vector mass, adjacent
# stem pairs carry a little phrase structure, and character n-grams get a small
# weight as partial credit for morphology the stemmer misses. An earlier version
# had the n-gram weight high enough that n-grams held about three quarters of the
# mass, which gave every pair of English sentences a similarity floor of roughly
# 0.1 and pushed the two probe distributions together.
_W_WORD = 8.0
_W_BIGRAM = 4.0
_W_NGRAM = 0.6

_STEM_SUFFIXES = ("ing", "ed", "es", "s", "y")


def stem(token):
    """A crude suffix stripper, not a linguistic one.

    It exists to make "micrometer" match "micrometers" and "injured" match
    "injury", which is most of the win, and it is applied to the word and bigram
    features only. It will happily produce a nonsense stem; that is fine, because
    both sides of every comparison are stemmed the same way.
    """
    if len(token) < 5:
        return token
    for suffix in _STEM_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def tokenize(text):
    """Lowercase alphanumeric tokens, stopwords removed."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def _features(text):
    """Yield (feature string, weight) pairs for one text."""
    tokens = tokenize(text)
    stems = [stem(token) for token in tokens]
    for token, stemmed in zip(tokens, stems):
        yield "w:" + stemmed, _W_WORD
        padded = "^" + token + "$"
        for n in _NGRAM_SIZES:
            if len(padded) < n:
                continue
            for i in range(len(padded) - n + 1):
                yield "g:" + padded[i : i + n], _W_NGRAM
    for left, right in zip(stems, stems[1:]):
        yield "b:" + left + "_" + right, _W_BIGRAM


def _hash_feature(feature):
    """Stable 64 bit hash. Python's built in hash() is salted per process and is
    therefore useless for anything written to disk."""
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def embed(text, dim=DIM):
    """Return an L2 normalised dense vector of length dim.

    Signed hashing: the bucket comes from the low bits and the sign from a
    different slice of the same digest, so unrelated features cancel instead of
    piling up. Two unrelated texts land near zero similarity rather than at some
    positive floor, which is exactly what the calibration step needs.
    """
    vec = [0.0] * dim
    for feature, weight in _features(text):
        h = _hash_feature(feature)
        bucket = h % dim
        sign = 1.0 if ((h // dim) & 1) else -1.0
        vec[bucket] += sign * weight
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        # A text with no content tokens at all. Returned as the zero vector, which
        # scores zero similarity against everything and so gets refused.
        return vec
    return [v / norm for v in vec]


def cosine(a, b):
    """Cosine similarity of two vectors that are already L2 normalised."""
    return sum(x * y for x, y in zip(a, b))


def distance(a, b):
    """Cosine distance. 0.0 is identical, 1.0 is orthogonal."""
    return 1.0 - cosine(a, b)
