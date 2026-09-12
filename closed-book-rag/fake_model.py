"""The answerer, behind the interface a hosted model would sit behind.

    answer(system_prompt, question, passages) -> str

THIS IS A STAND-IN. In the original system this call went to a hosted language
model. Here it is a deterministic extractive synthesiser: it selects the sentences
from the supplied passages that best support the question, puts them back in
document order, and appends the citations. It writes nothing that is not already
in a passage, so it cannot confabulate, which also means it cannot paraphrase,
summarise or reason.

The interface is the real boundary, and it is the thing worth looking at. The
caller hands over a system prompt, a question and a list of passages, and gets
back a string. Swapping in a hosted model is a change to this file alone. Every
guarantee the surrounding system makes (the calibrated no-answer floor, the
reference blocks, mandatory citations, the refusal path) sits OUTSIDE this call
and holds whichever answerer is plugged in. That is the whole point: a guarantee
that depends on the model choosing to honour it is not a guarantee.

Note on prompt injection: this answerer takes its control flow from the
`system_prompt` and `question` arguments only. Passage text is matched against,
never interpreted. It is structurally incapable of obeying an instruction written
inside a document. A hosted model is not, which is exactly why the wrapper labels
document content as reference material, and why any sentence the retrieval layer
flags is barred from being quoted into an answer.
"""

import math
import re
from collections import namedtuple

from embed import stem, tokenize

# name is the document path used for citation, text is the raw passage, flagged
# holds sentences the retrieval layer has quarantined (suspected injection).
Passage = namedtuple("Passage", "name text flagged")

REFUSAL = (
    "The supplied handbook passages do not answer that question, so I am not going to answer it."
)

MAX_SENTENCES = 3

# A sentence must cover at least this share of the question's weighted content
# before it counts as an answer at all. Coverage rather than raw overlap, so the
# threshold does not drift with question length.
MIN_COVERAGE = 0.35

# And a supporting sentence must be at least this good relative to the best one.
# Without it the answerer always returns MAX_SENTENCES sentences and the last one
# is whatever scored highest among the irrelevant remainder, which reads as
# confident padding.
RELATIVE_KEEP = 0.75

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

_Candidate = namedtuple(
    "_Candidate", "passage_index sentence_index name sentence stems bigrams length"
)


def split_sentences(text):
    """Sentences, rebuilt across the markdown hard wrap.

    The corpus is hard wrapped at about 78 columns, so one sentence spans several
    lines. Splitting line by line put half sentences into answers, the sort of
    defect that only shows up when you read the output rather than the exit code.
    Lines are joined back into paragraphs first, headings are dropped, and the
    sentence split happens on the paragraph.
    """
    paragraphs = []
    buffer = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            if buffer:
                paragraphs.append(" ".join(buffer))
                buffer = []
            continue
        buffer.append(line)
    if buffer:
        paragraphs.append(" ".join(buffer))

    sentences = []
    for paragraph in paragraphs:
        for part in _SENTENCE_SPLIT.split(paragraph):
            part = part.strip()
            if part:
                sentences.append(part)
    return sentences


def _whole_sentences(sentences):
    """Chunk windows cut mid sentence and overlapping chunks repeat text, so the
    candidate pool holds fragments of sentences that also appear in full. Anything
    contained inside a longer candidate is dropped."""
    ordered = sorted(set(sentences), key=len, reverse=True)
    kept = []
    for sentence in ordered:
        if any(sentence in longer for longer in kept):
            continue
        kept.append(sentence)
    return set(kept)


def _candidates(passages):
    pool = _whole_sentences(
        [s for passage in passages for s in split_sentences(passage.text)]
    )
    seen = set()
    candidates = []
    for passage_index, passage in enumerate(passages):
        flagged = set(passage.flagged or ())
        for sentence_index, sentence in enumerate(split_sentences(passage.text)):
            if sentence not in pool or sentence in seen:
                continue
            if sentence in flagged:
                # Quarantined by the retrieval layer. Still visible to the model
                # as data, never lifted into an answer.
                continue
            seen.add(sentence)
            stems = [stem(token) for token in tokenize(sentence)]
            candidates.append(
                _Candidate(
                    passage_index=passage_index,
                    sentence_index=sentence_index,
                    name=passage.name,
                    sentence=sentence,
                    stems=set(stems),
                    bigrams=set(zip(stems, stems[1:])),
                    length=len(stems),
                )
            )
    return candidates


def _matches(term, stems):
    """Exact stem match, or a shared five character prefix for a longer term.

    The prefix rule is what carries "approve" to "approval", which the suffix
    stripper alone does not. Scoring and the term weighting below use the same
    rule on purpose: counting a term as absent while still scoring it as present
    dropped the one term that mattered out of the weighting.
    """
    if term in stems:
        return True
    return len(term) >= 5 and any(other.startswith(term[:5]) for other in stems)


def _term_weights(question_stems, candidates):
    """Weight each question term by how rare it is among the retrieved sentences.

    A term appearing in nearly every retrieved sentence says nothing about which
    sentence to pick. Before this, a question about how long you have to submit an
    expense claim pulled in a sentence about tying back long hair, because both
    contain "long" and nothing distinguished that match from a real one. The
    weighting is computed over the retrieved passages only, so it costs nothing
    and needs no corpus wide statistics.

    A term that appears in none of them is dropped rather than weighted, because a
    sentence cannot be marked down for failing to cover a word that is not in any
    of the retrieved text. Leaving those terms in the denominator made the
    coverage test refuse questions it had already accepted: "how often does
    lockout training need refreshing" was refused because "often" and "need"
    appear nowhere in the handbook.
    """
    total = max(len(candidates), 1)
    weights = {}
    for term in question_stems:
        seen_in = sum(1 for candidate in candidates if _matches(term, candidate.stems))
        if seen_in == 0:
            continue
        weights[term] = math.log(1.0 + total / (1.0 + seen_in))
    return weights


def _score(question_stems, question_bigrams, weights, candidate):
    score = 0.0
    for term in question_stems:
        weight = weights.get(term, 0.0)
        if weight <= 0.0:
            continue
        if term in candidate.stems:
            score += weight
        elif _matches(term, candidate.stems):
            score += 0.5 * weight
    for pair in question_bigrams & candidate.bigrams:
        score += 0.5 * (weights.get(pair[0], 0.0) + weights.get(pair[1], 0.0))
    # Mild length discount, so a long sentence cannot win on volume alone.
    return score / (1.0 + 0.01 * candidate.length)


class LocalAnswerer:
    """Deterministic stand-in answerer."""

    name = "local-extractive-stub"

    def answer(self, system_prompt, question, passages):
        # The system prompt is accepted and deliberately not parsed. A hosted
        # model would act on it; this stub enforces the same contract in code.
        if not isinstance(system_prompt, str) or not system_prompt:
            raise ValueError("a system prompt is required")

        question_stems = [stem(token) for token in tokenize(question)]
        question_bigrams = set(zip(question_stems, question_stems[1:]))
        if not question_stems:
            return REFUSAL

        candidates = _candidates(passages)
        if not candidates:
            return REFUSAL

        unique_stems = set(question_stems)
        weights = _term_weights(unique_stems, candidates)
        available = sum(weights.values())
        if available <= 0.0:
            return REFUSAL

        scored = [
            (_score(unique_stems, question_bigrams, weights, candidate), candidate)
            for candidate in candidates
        ]
        best = max(score for score, _ in scored)
        if best / available < MIN_COVERAGE:
            # Nothing in the passages covers enough of the question to answer it.
            # This is the second line of defence: the calibrated floor normally
            # stops a question like this before it ever reaches the answerer.
            return REFUSAL

        cutoff = max(RELATIVE_KEEP * best, MIN_COVERAGE * available)
        keep = [(score, candidate) for score, candidate in scored if score >= cutoff]
        keep.sort(key=lambda row: (-row[0], row[1].passage_index, row[1].sentence_index))
        keep = keep[:MAX_SENTENCES]

        # Read back in document order so the answer reads as prose.
        keep.sort(key=lambda row: (row[1].passage_index, row[1].sentence_index))
        body = " ".join(candidate.sentence for _, candidate in keep)

        cited = []
        for _, candidate in keep:
            if candidate.name not in cited:
                cited.append(candidate.name)
        return body + "\nSources: " + ", ".join(cited)
