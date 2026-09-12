"""The precedence policy, expressed as data.

Which source wins is a policy question, not a programming one. Written as
nested conditionals it becomes unreadable within about four categories and
nobody outside the team can check it. Written as a table, the whole policy fits
on one screen and a non-programmer can audit it.

The policy in one sentence: the job-tracking system wins where it directly
measures the work, the contractor invoice wins where the work was subcontracted
and the tracker only sees a stub, and the plan is never authoritative, only ever
the last resort when nobody actually reported the job.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Sequence

SOURCES = ("plan", "vendor", "system")

# Precedence may not flip to a figure more than this multiple of the figure it
# beats. See resolver.sanity_bound for why, and why lowering it is the wrong fix.
DEFAULT_BOUND = Decimal("2.0")


@dataclass(frozen=True)
class Rule:
    """One row of the policy table.

    category: the category this rule governs.
    site:     None for every site, or a single site for a local carve out.
    order:    sources best first. A source missing from the order can never win.
    bound:    the sanity multiple for a flip under this rule.
    note:     why the order is what it is, in words, for the audit trail.
    """

    category: str
    site: Optional[str]
    order: tuple
    bound: Decimal
    note: str

    @property
    def name(self) -> str:
        scope = self.category if self.site is None else "{0} @ {1}".format(self.category, self.site)
        return "{0}: {1}".format(scope, " > ".join(self.order))

    def matches(self, category: str, site: str) -> bool:
        if self.category != category:
            return False
        return self.site is None or self.site == site


@dataclass(frozen=True)
class BoundException:
    """A named, reasoned permission for one line to flip beyond its bound.

    This is the only correct response to an escalation that was not a real
    problem. Lowering DEFAULT_BOUND to make one line pass quietly re-admits
    every bad export in the file.
    """

    key: str
    granted_by: str
    granted_on: str
    reason: str


POLICY_RULES = (
    Rule(
        category="electrical",
        site=None,
        order=("system", "vendor", "plan"),
        bound=DEFAULT_BOUND,
        note="metered in house, so the tracker measures the real job",
    ),
    Rule(
        category="hvac",
        site=None,
        order=("system", "vendor", "plan"),
        bound=DEFAULT_BOUND,
        note="tracker reads the plant directly",
    ),
    Rule(
        category="plumbing",
        site=None,
        order=("vendor", "system", "plan"),
        bound=DEFAULT_BOUND,
        note="subcontracted, so the invoice is the primary record",
    ),
    Rule(
        category="grounds",
        site=None,
        order=("vendor", "plan", "system"),
        bound=DEFAULT_BOUND,
        note="subcontracted and the tracker only logs a visit stub, so it ranks last",
    ),
)

# Nobody reported a category we have a rule for. Publish the plan and say so.
FALLBACK_RULE = Rule(
    category="*",
    site=None,
    order=("plan", "vendor", "system"),
    bound=DEFAULT_BOUND,
    note="no policy for this category, plan only, review before publishing",
)

BOUND_EXCEPTIONS = (
    BoundException(
        key="wo6310",
        granted_by="R. Alcott",
        granted_on="2026-04-28",
        reason="the contractor invoiced a deposit only, the measured figure is the whole job",
    ),
)


class Policy:
    """The policy table plus its lookups. Validate it before you trust it."""

    def __init__(
        self,
        rules: Sequence[Rule] = POLICY_RULES,
        fallback: Rule = FALLBACK_RULE,
        exceptions: Sequence[BoundException] = BOUND_EXCEPTIONS,
    ):
        self.rules = tuple(rules)
        self.fallback = fallback
        self.exceptions = tuple(exceptions)

    def validate(self) -> None:
        """Refuse a policy where two rules govern the same line.

        Overlapping rules are how a line gets claimed twice, and a line claimed
        twice is money counted twice. partition.assert_one_owner is the backstop
        if a policy gets past this.
        """
        scopes = [(rule.category, rule.site) for rule in self.rules]
        duplicates = sorted({scope for scope in scopes if scopes.count(scope) > 1})
        if duplicates:
            raise ValueError("policy has overlapping rules for: {0}".format(duplicates))
        for rule in self.rules + (self.fallback,):
            unknown = [src for src in rule.order if src not in SOURCES]
            if unknown:
                raise ValueError("rule '{0}' names unknown sources {1}".format(rule.name, unknown))
            if len(set(rule.order)) != len(rule.order):
                raise ValueError("rule '{0}' lists a source twice".format(rule.name))

    def rules_for(self, category: str, site: str) -> tuple:
        """Every rule that governs this line. The contract is exactly one.

        Site scoped rules beat category wide rules, so a carve out is returned
        alone rather than alongside the general rule.
        """
        matched = [rule for rule in self.rules if rule.matches(category, site)]
        if not matched:
            return (self.fallback,)
        specific = [rule for rule in matched if rule.site is not None]
        return tuple(specific) if specific else tuple(matched)

    def exception_for(self, key: str) -> Optional[BoundException]:
        for exception in self.exceptions:
            if exception.key == key:
                return exception
        return None

    def table(self) -> list:
        """The whole policy as printable rows."""
        rows = [(rule.category, rule.site or "all sites", " > ".join(rule.order),
                 str(rule.bound) + "x", rule.note) for rule in self.rules]
        rows.append((self.fallback.category, "all sites", " > ".join(self.fallback.order),
                     str(self.fallback.bound) + "x", self.fallback.note))
        return rows
