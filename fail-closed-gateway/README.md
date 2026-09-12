[← Showreel](..)

# 🚦 Fail-Closed Gateway

![AI guardrails](https://img.shields.io/badge/AI_guardrails-e11d48) ![Node.js](https://img.shields.io/badge/Node.js-339933?logo=nodedotjs&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

**A limiter outage must never become free compute.** In front of a paid LLM endpoint
sit two guards, a rate limiter and a content gate. The design question nobody asks
until it hurts: what happens when a *guard* fails? Most implementations fail open: the
limiter's store times out, the check is skipped, and an outage becomes an invitation.

## Try it

```bash
node main.mjs --demo
```

Zero dependencies. The demo runs the same burst of traffic through both philosophies,
kills the limiter's store mid-burst, and prints the running bill: fail-closed refused
through the outage ($0.12); fail-open generated through it ($0.40). Same traffic, same
outage, and the difference is a design decision.

## The interesting part

- **Both guards fail closed.** A guard that cannot answer is a guard saying no. On a
  paid compute path the user sees a clean 503; the bill sees nothing.
- **The refusal taxonomy is part of the API.** 429 with retry-after for limits, 400
  for blocked content, 503 for a guard outage, three different truths, three
  different status codes, no lies.
- **Atomicity lives in the store.** The sliding window is one atomic operation per
  (action, key) bucket (in production, a single database statement) because a
  check-then-write limiter is a race condition wearing a seatbelt.

## package.json

```json
{ "scripts": { "demo": "node main.mjs --demo" } }
```
