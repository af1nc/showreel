"""The labelled probe set the floor is measured from.

ON_TOPIC: questions the handbook library genuinely answers. Phrased the way a
person on the shop floor would ask them, not copied out of the documents, because
a probe that quotes the document measures the corpus against itself.

OFF_TOPIC: questions it does not answer. Two kinds, deliberately:
  * plainly outside the library (general knowledge, hobbies, other trades),
  * plausible but absent, that is, the sort of internal question a person might
    well ask this assistant and which no document covers. These are the ones a
    hand-picked threshold gets wrong, and they are the reason the probe set is
    labelled by hand rather than generated.

Extend both lists as the corpus grows, then re-run the calibration. That is the
whole maintenance story for the floor.
"""

import hashlib

ON_TOPIC = (
    "What is the receipt threshold on an expense claim?",
    "Who has to approve a large expense claim?",
    "How long do I have to submit an expense claim?",
    "What checks do I do on a machine before I start my shift?",
    "How often is a torque wrench calibrated?",
    "What happens if a micrometer gets dropped on the floor?",
    "Who do I call when someone is injured badly enough to leave the first aid room?",
    "What goes on the handover card at the end of a shift?",
    "Can a visitor walk around the shop floor on their own?",
    "What score does a new supplier need to pass the quality assessment?",
    "Where does a returned part get booked in?",
    "How long is a hot work permit valid for?",
    "What do I do with a solvent drum that is in use?",
    "How often does lockout training need refreshing?",
    "What happens to material rejected at goods inwards?",
    "Do I need to lock off the hydraulic accumulator before working on a press?",
    "How quickly must a customer complaint be acknowledged?",
    "Who signs off that an operator is competent on a machine?",
)

OFF_TOPIC = (
    "What is the best way to get sourdough to rise in a cold kitchen?",
    "Who won the county cricket championship in 1994?",
    "How do I reset a home wireless router to factory settings?",
    "What is the difference between a sonnet and a haiku?",
    "Write me a short poem about a tabby cat asleep on a radiator.",
    "How many chromosomes does a domestic cat have?",
    "What is a good stretching routine before a long run?",
    "Which spices go into a traditional rogan josh?",
    "How do I change the timing belt on a diesel hatchback?",
    "What is the population of the largest city in South America?",
    "How do I convert a JPEG to a vector graphic?",
    "What are the rules of duplicate bridge scoring?",
    # Plausible but absent: the assistant could easily be asked these, and no
    # document in the library covers them.
    "How much parental leave am I entitled to after adoption?",
    "What is the company policy on working from home two days a week?",
    "How do I book annual leave over the shutdown period?",
    "What is the pension employer contribution rate?",
)


def probe_hash():
    """Identifies the exact probe set a floor was measured from."""
    digest = hashlib.sha256()
    for label, questions in (("on", ON_TOPIC), ("off", OFF_TOPIC)):
        digest.update(label.encode("utf-8"))
        for question in questions:
            digest.update(question.encode("utf-8"))
    return digest.hexdigest()[:16]
