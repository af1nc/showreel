[← Showreel](..)

# 🕰️ AI Output Watchdog

![AI guardrails](https://img.shields.io/badge/AI_guardrails-e11d48) ![Python](https://img.shields.io/badge/Python-3776ab?logo=python&logoColor=white) ![stdlib only](https://img.shields.io/badge/stdlib-only-2ea44f) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

**Who audits the AI when nobody is looking?** A generative system that briefs you daily
will keep producing confident output long after the pipelines feeding it have quietly
died, and stale data reads exactly like fresh data. This is the deterministic layer of the
audit: a nightly stdlib-only job that is relentless about mechanics and silent about
quality.

## Try it

```bash
python main.py --demo
```

Two mornings: a healthy one, and one quietly rotting: a dead message source, a
degraded email poller, a wearable erroring on every poll, with RED/AMBER/GREEN
verdicts and a dated markdown report a human finds waiting.

## The interesting part

- **Silence is not failure.** Sources with no expected cadence (voice notes exist only
  when someone speaks) report as INFO, never RED. Flag them forever and you train the
  reader to ignore the whole report, and the alert that always fires protects nothing.
- **Errors outrank staleness.** Three consecutive poll failures is RED regardless of
  cadence rules; a pipeline that *errors* is broken even if its data isn't old yet.
- **GREEN is a floor, not an endorsement.** The job checks that the pipes flow.
  Whether the output is any *good* is judgment work, and judgment does not belong in
  a cron job, and the report says so, on every report.
- **Per-source thresholds, two levels each.** Continuous sources amber in hours;
  polled integrations get a day; device-pushed sources get the benefit of a weekend.
