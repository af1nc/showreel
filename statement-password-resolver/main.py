"""Banks lock their statements with passwords they print in the email.

Financial institutions encrypt PDF statements with *formulaic* passwords — a few
digits of your birth date, a fragment of your name, the tail of your phone number —
and each institution invents its own recipe. Automate statement ingestion across
several of them and you face a choice: let every extractor roll its own derivation
logic (and drift), or centralise the recipes in one resolver with one audit point.

This is the resolver. Design rules that survived production:

  * one derivation matrix — every institution's recipe in one reviewable table
  * candidates, not answers — some institutions use different shapes per document
    type, so the resolver returns an ordered list to try
  * the resolver never decrypts — plaintext candidates flow straight to the caller
    and are never written anywhere
  * missing credentials are a routing outcome ("ask the user"), not an exception

Institutions here are synthetic ("Meridian", "Cobalt", "Northgate"), but each recipe
shape is real — this is what retail banks actually do.

Run:  python main.py --demo        (stdlib only)
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from datetime import date


# ---------------------------------------------------------------------------
# 1. The customer's identity — the ingredients recipes draw on.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Identity:
    full_name: str
    date_of_birth: date
    customer_number: str | None = None
    mobile: str | None = None


# ---------------------------------------------------------------------------
# 2. The derivation matrix. One table, one audit point.
#    Each recipe: (institution, shape) → ordered candidate builders.
# ---------------------------------------------------------------------------

def _ddmm(d: date) -> str:
    return f"{d.day:02d}{d.month:02d}"


def _name4(name: str) -> str:
    """First four letters of the first name, uppercased, zero-padded if short."""
    first = name.split()[0].upper()
    return (first + "0000")[:4]


def derive(institution: str, shape: str, who: Identity) -> list[str]:
    """Return ordered password candidates, or [] when credentials are missing."""
    dob = who.date_of_birth

    if institution == "meridian":
        if not who.customer_number:
            return []
        if shape == "transfer_advice":
            # customer number (6) + DDMM — used only for transfer advices
            return [f"{who.customer_number[:6]}{_ddmm(dob)}"]
        # every other Meridian document: ddmmyy + customer number (6)
        return [f"{dob.day:02d}{dob.month:02d}{dob.year % 100:02d}{who.customer_number[:6]}"]

    if institution == "cobalt":
        # one shape for everything: NAME4 + DDMM
        return [f"{_name4(who.full_name)}{_ddmm(dob)}"]

    if institution == "northgate":
        # primary shape, then a legacy fallback some accounts still use
        candidates = [f"{_name4(who.full_name)}{_ddmm(dob)}"]
        if who.mobile:
            candidates.append(who.mobile[-7:])  # last 7 digits of mobile
        return candidates

    return []


# ---------------------------------------------------------------------------
# 3. A stand-in for the encrypted document. The real system hands candidates to
#    a PDF decryptor; the demo "encrypts" with a key derived from the password
#    so the try-in-order behaviour is identical and verifiable.
# ---------------------------------------------------------------------------

@dataclass
class SealedStatement:
    institution: str
    shape: str
    _lock: str  # hash of the true password — the document knows, we do not

    def unlock(self, candidate: str) -> bool:
        return hashlib.sha256(candidate.encode()).hexdigest() == self._lock


def seal(institution: str, shape: str, true_password: str) -> SealedStatement:
    return SealedStatement(
        institution, shape, hashlib.sha256(true_password.encode()).hexdigest()
    )


def open_statement(doc: SealedStatement, who: Identity) -> tuple[str, list[str]]:
    """Try candidates in order. Returns (outcome, audit_trail)."""
    trail: list[str] = []
    candidates = derive(doc.institution, doc.shape, who)
    if not candidates:
        trail.append("no credentials on file → route to settings, ask the user")
        return "NEEDS_CREDENTIALS", trail
    for i, candidate in enumerate(candidates, 1):
        masked = candidate[0] + "•" * (len(candidate) - 2) + candidate[-1]
        if doc.unlock(candidate):
            trail.append(f"candidate {i}/{len(candidates)} ({masked}) → unlocked")
            return "UNLOCKED", trail
        trail.append(f"candidate {i}/{len(candidates)} ({masked}) → rejected")
    trail.append("all candidates rejected → recipe drift? flag for review")
    return "FAILED", trail


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def demo() -> None:
    alex = Identity(
        full_name="Alex Rivera",
        date_of_birth=date(1988, 3, 7),
        customer_number="481529",
        mobile="0501234567",
    )
    # A second household member with no customer number on file yet.
    sam = Identity(full_name="Sam Chen", date_of_birth=date(1991, 11, 22))

    inbox = [
        ("meridian statement (regular)", seal("meridian", "card_statement", "070388481529"), alex),
        ("meridian transfer advice", seal("meridian", "transfer_advice", "4815290703"), alex),
        ("cobalt statement", seal("cobalt", "statement", "ALEX0703"), alex),
        ("northgate (legacy account)", seal("northgate", "statement", "1234567"), alex),
        ("meridian statement for Sam", seal("meridian", "card_statement", "221191xxxxxx"), sam),
    ]

    for label, doc, who in inbox:
        outcome, trail = open_statement(doc, who)
        print(f"{label:<32} {outcome}")
        for line in trail:
            print(f"    {line}")
        print()

    print("plaintext candidates lived only on the call stack — nothing was persisted.")


if __name__ == "__main__":
    if "--demo" not in sys.argv:
        print(__doc__)
        sys.exit(0)
    demo()
