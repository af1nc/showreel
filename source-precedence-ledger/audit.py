"""The audit trail and everything that renders.

The trail is the deliverable, not a debug log. The test it has to pass is that
somebody who was not in the room can pick any published figure, read its trail,
and defend the number: which sources reported, which rule fired, which source
won, what was suppressed and why, and what a human ruled if anyone did.
"""

from dataclasses import dataclass, field
from decimal import Decimal

STAGE_WIDTH = 11


def fmt_money(amount):
    """Money as a right sized string. None means the line has no figure yet."""
    if amount is None:
        return "-"
    return "{0:,.2f}".format(amount)


@dataclass
class AuditEntry:
    stage: str
    detail: str


@dataclass
class AuditTrail:
    """One line's complete history, in the order it happened."""

    key: str
    site: str
    category: str
    period: str
    entries: list = field(default_factory=list)

    def add(self, stage, detail):
        self.entries.append(AuditEntry(stage=stage, detail=detail))

    def stages(self):
        return [entry.stage for entry in self.entries]

    def render(self, raw_codes=(), dispositions=()):
        out = []
        out.append("Audit trail: {0}  ({1}, {2}, {3})".format(
            self.key, self.site, self.category, self.period))
        if raw_codes:
            out.append("Raw codes seen: " + ", ".join(raw_codes))
        out.append("-" * 78)
        for entry in self.entries:
            out.append("  {0} {1}".format(entry.stage.ljust(STAGE_WIDTH), entry.detail))
        suppressed = [d for d in dispositions if d.key == self.key and d.kind != "WINNER"]
        if suppressed:
            out.append("-" * 78)
            out.append("  Suppressed and why:")
            for disposition in sorted(suppressed, key=lambda d: d.source):
                out.append("    {0} {1}  {2}".format(
                    disposition.source.ljust(8),
                    fmt_money(disposition.amount).rjust(10),
                    disposition.reason,
                ))
        return "\n".join(out)


def render_table(headers, rows, aligns=None):
    """A plain box drawn table. Columns size themselves to their contents."""
    aligns = aligns or ["left"] * len(headers)
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))

    def line(left, mid, right):
        return left + mid.join("─" * (width + 2) for width in widths) + right

    def format_row(cells):
        parts = []
        for index, cell in enumerate(cells):
            text = str(cell)
            parts.append(" " + (text.rjust(widths[index]) if aligns[index] == "right"
                                else text.ljust(widths[index])) + " ")
        return "│" + "│".join(parts) + "│"

    out = [line("┌", "┬", "┐"), format_row(headers), line("├", "┼", "┤")]
    out.extend(format_row(row) for row in rows)
    out.append(line("└", "┴", "┘"))
    return "\n".join(out)


def render_book(book):
    """The resolved book, one row per line, with the winning source on show."""
    headers = ["work order", "site", "category", "period", "status", "source", "amount", "rule"]
    rows = []
    for line in book.lines:
        rows.append([
            line.key,
            line.site,
            line.category,
            line.period,
            line.status,
            line.winning_source,
            fmt_money(line.amount),
            line.rule_fired,
        ])
    aligns = ["left", "left", "left", "left", "left", "left", "right", "left"]
    table = render_table(headers, rows, aligns)
    published = book.published()
    footer = "Published {0} of {1} lines, total {2}. {3} escalated, awaiting a decision.".format(
        len(published), len(book.lines), fmt_money(book.total()),
        len(book.lines) - len(published))
    return table + "\n" + footer


def render_queue(book):
    """The human decision queue: both figures, and the rule that would have fired."""
    if not book.queue:
        return "Decision queue is empty."
    headers = ["work order", "rule that would have fired", "would take", "over", "gap", "bound"]
    rows = []
    for item in book.queue:
        gap = "unbounded" if item.ratio is None else "{0}x".format(item.ratio)
        rows.append([
            item.key,
            item.rule_name,
            "{0} {1}".format(item.contender.source, fmt_money(item.contender.amount)),
            "{0} {1}".format(item.incumbent.source, fmt_money(item.incumbent.amount)),
            gap,
            "{0}x".format(item.bound),
        ])
    return render_table(headers, rows, ["left", "left", "right", "right", "right", "right"])


def render_sources(candidates):
    """The raw disagreement, before anything has been decided."""
    headers = ["source", "raw code", "site", "category", "period", "label", "amount"]
    rows = []
    for candidate in sorted(candidates, key=lambda c: (c.period, c.key, c.source)):
        rows.append([
            candidate.source,
            candidate.raw_code,
            candidate.site,
            candidate.category,
            candidate.period,
            candidate.label,
            fmt_money(candidate.amount),
        ])
    aligns = ["left", "left", "left", "left", "left", "left", "right"]
    return render_table(headers, rows, aligns)
