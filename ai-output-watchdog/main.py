"""Who audits the AI when nobody is looking?

A generative system produces a daily briefing from a dozen data pipelines. On a good
day a human reads it. On most days nobody checks whether the pipelines feeding it
have quietly died — and a briefing built on stale data looks exactly like a briefing.

This is the deterministic layer of the audit: a nightly job, stdlib only, that never
has an opinion about *quality* (that is judgment work) but is relentless about
*mechanics* — freshness per source, output recency, and dead pipelines. Verdicts:

  RED    — the output is starved or a core source is dead; a human must look
  AMBER  — something is degraded; the next review should start here
  GREEN  — the mechanical floor passes (which is a floor, not an endorsement)

The design decision that matters most is about silence: some sources have NO expected
cadence — a voice-note pipeline is silent whenever nobody speaks, and that is a
customer choice, not a fault. Flagging it forever trains the reader to ignore the
whole report. Silence without an expected cadence is INFO, never RED.

Run:  python main.py --demo
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: Freshness thresholds per source, in hours: (amber_after, red_after).
#: Continuous local sources should tick constantly; polled integrations run on
#: longer cycles; device-pushed sources depend on someone carrying the device.
FRESHNESS_HOURS: dict[str, tuple[float, float]] = {
    "calendar": (6, 48),
    "messages": (6, 48),
    "email": (6, 48),
    "wearable": (26, 72),
    "utility-meter": (30, 96),
}

#: Sources with no expected cadence. Their silence is a choice, not a failure.
NO_EXPECTED_CADENCE = frozenset({"voice-notes", "documents-drop"})

OUTPUT_STALE_AMBER_H = 26.0
OUTPUT_STALE_RED_H = 50.0


@dataclass
class SourceVerdict:
    name: str
    level: str  # RED / AMBER / GREEN / INFO
    detail: str


def audit(state: dict, now: datetime) -> tuple[str, list[SourceVerdict]]:
    verdicts: list[SourceVerdict] = []

    def hours_since(iso: str | None) -> float | None:
        if not iso:
            return None
        return (now - datetime.fromisoformat(iso)).total_seconds() / 3600

    # --- the output itself -------------------------------------------------
    out_age = hours_since(state.get("last_output_at"))
    if out_age is None or out_age > OUTPUT_STALE_RED_H:
        verdicts.append(SourceVerdict("output", "RED", f"no output for {out_age:.0f}h" if out_age else "no output ever"))
    elif out_age > OUTPUT_STALE_AMBER_H:
        verdicts.append(SourceVerdict("output", "AMBER", f"last output {out_age:.0f}h ago"))
    else:
        verdicts.append(SourceVerdict("output", "GREEN", f"last output {out_age:.1f}h ago"))

    # --- every feeding pipeline -------------------------------------------
    for name, info in sorted(state.get("sources", {}).items()):
        age = hours_since(info.get("last_item_at"))
        failures = int(info.get("consecutive_poll_failures", 0))

        if failures >= 3:
            # A pipeline that ERRORS is broken regardless of cadence rules.
            verdicts.append(SourceVerdict(name, "RED", f"{failures} consecutive poll failures"))
            continue

        if name in NO_EXPECTED_CADENCE:
            note = f"silent {age:.0f}h — no expected cadence; silence is a choice" if age else "never used"
            verdicts.append(SourceVerdict(name, "INFO", note))
            continue

        amber_h, red_h = FRESHNESS_HOURS.get(name, (24, 72))
        if age is None or age > red_h:
            verdicts.append(SourceVerdict(name, "RED", f"stale {age:.0f}h (red at {red_h:.0f}h)" if age else "no data ever"))
        elif age > amber_h:
            verdicts.append(SourceVerdict(name, "AMBER", f"stale {age:.0f}h (amber at {amber_h:.0f}h)"))
        else:
            verdicts.append(SourceVerdict(name, "GREEN", f"fresh ({age:.1f}h)"))

    # --- overall: worst REAL level wins; INFO never escalates ---------------
    levels = [v.level for v in verdicts if v.level != "INFO"]
    overall = "RED" if "RED" in levels else "AMBER" if "AMBER" in levels else "GREEN"
    return overall, verdicts


def render(overall: str, verdicts: list[SourceVerdict], now: datetime) -> str:
    icon = {"RED": "🔴", "AMBER": "🟡", "GREEN": "🟢", "INFO": "·"}
    lines = [
        f"# Nightly audit — {now.date().isoformat()}",
        "",
        f"**Overall: {icon[overall]} {overall}**"
        + ("  ← a human must look" if overall == "RED" else ""),
        "",
    ]
    for v in verdicts:
        lines.append(f"- {icon[v.level]} `{v.name}` — {v.detail}")
    lines += [
        "",
        "_Mechanical floor only. GREEN means the pipes flow, not that the output is good —_",
        "_quality is judgment work, and judgment does not belong in a cron job._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Demo: one healthy morning, one quietly rotting one.
# ---------------------------------------------------------------------------

def demo() -> None:
    now = datetime(2026, 7, 27, 3, 0, tzinfo=timezone.utc)
    iso = lambda h: (now - timedelta(hours=h)).isoformat()

    healthy = {
        "last_output_at": iso(3),
        "sources": {
            "calendar": {"last_item_at": iso(1)},
            "messages": {"last_item_at": iso(2)},
            "email": {"last_item_at": iso(4)},
            "wearable": {"last_item_at": iso(20)},
            "utility-meter": {"last_item_at": iso(25)},
            "voice-notes": {"last_item_at": iso(1400)},  # two months of silence — fine
        },
    }

    rotting = {
        "last_output_at": iso(30),  # output still appearing… built on what?
        "sources": {
            "calendar": {"last_item_at": iso(1)},
            "messages": {"last_item_at": iso(60)},                     # dead
            "email": {"last_item_at": iso(9)},                         # degraded
            "wearable": {"last_item_at": iso(20), "consecutive_poll_failures": 4},  # erroring
            "utility-meter": {"last_item_at": iso(25)},
            "voice-notes": {"last_item_at": iso(1400)},                # still fine
        },
    }

    for label, state in [("A HEALTHY MORNING", healthy), ("A QUIETLY ROTTING ONE", rotting)]:
        overall, verdicts = audit(state, now)
        print(f"═══ {label} ═══\n")
        print(render(overall, verdicts, now))
        print()

    out = Path("audit-2026-07-27.md")
    overall, verdicts = audit(rotting, now)
    out.write_text(render(overall, verdicts, now))
    print(f"wrote {out} — the report a human finds waiting when things went wrong")


if __name__ == "__main__":
    if "--demo" not in sys.argv:
        print(__doc__)
        sys.exit(0)
    demo()
