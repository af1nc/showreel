```
███████ ██   ██  ██████  ██     ██ ██████  ███████ ███████ ██
██      ██   ██ ██    ██ ██     ██ ██   ██ ██      ██      ██
███████ ███████ ██    ██ ██  █  ██ ██████  █████   █████   ██
     ██ ██   ██ ██    ██ ██ ███ ██ ██   ██ ██      ██      ██
███████ ██   ██  ██████   ███ ███  ██   ██ ███████ ███████ ███████
```

<p align="center"><b>Twenty-one small engineering projects, each built to run on its own with a single command.</b></p>

<p align="center">
  <a href="https://github.com/af1nc/showreel/actions/workflows/demos.yml"><img src="https://github.com/af1nc/showreel/actions/workflows/demos.yml/badge.svg" alt="demos"></a>
  <img src="https://img.shields.io/badge/projects-21-2ea44f" alt="21 projects">
  <img src="https://img.shields.io/badge/demos-one%20command-orange" alt="one-command demos">
  <img src="https://img.shields.io/badge/TypeScript-3178c6?logo=typescript&logoColor=white" alt="TypeScript">
  <img src="https://img.shields.io/badge/Python-3776ab?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Node.js-339933?logo=nodedotjs&logoColor=white" alt="Node.js">
  <img src="https://img.shields.io/badge/React-149eca?logo=react&logoColor=white" alt="React">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license">
</p>

Every project takes a real problem, keeps the part that is actually interesting, and
ships with a demo you can run in about a minute. No accounts, no API keys, nothing to
sign up for. Everything runs offline on synthetic data.

The badge above is not decoration. Every demo here is installed from scratch and run end
to end by CI, on a runner with no credentials configured, on every push. A project that
quietly grows a dependency on a network service fails there rather than in your terminal.

## What is inside

```mermaid
flowchart LR
  subgraph DS["Data science and ML"]
    direction TB
    P1("bayesian-mmm-runner")
    P2("causal-impact-model")
    P3("sos-revenue-econometrics")
    P4("bayesian-ab-engine")
    P5("reach-frequency-dedup")
  end
  subgraph AI["AI and agents"]
    direction TB
    P6("agentic-sql-assistant")
    P7("closed-book-rag")
    P8("share-of-ai-equity")
    P9("vision-ad-classifier")
    P10("correction-taught-classifier")
  end
  subgraph GRD["AI guardrails"]
    direction TB
    P11("publish-gate")
    P12("ai-output-watchdog")
    P13("fail-closed-gateway")
  end
  subgraph DE["Data engineering"]
    direction TB
    P14("source-precedence-ledger")
    P15("resilient-snapshot-pipeline")
  end
  subgraph FP["Formats and protocols"]
    direction TB
    P16("streaming-xlsx-export")
    P17("udp-request-reply")
    P18("hum-to-midi-tracker")
    P19("chat-export-voice")
  end
  subgraph VIZ["Data visualisation"]
    direction TB
    P20("great-circle-route-map")
    P21("dataviz-techniques")
  end

  classDef ds fill:#dbeafe,stroke:#3b82f6,stroke-width:1px,color:#1e3a8a
  classDef ai fill:#ede9fe,stroke:#8b5cf6,stroke-width:1px,color:#4c1d95
  classDef grd fill:#ffe4e6,stroke:#e11d48,stroke-width:1px,color:#881337
  classDef de fill:#e0f2fe,stroke:#0ea5e9,stroke-width:1px,color:#075985
  classDef fp fill:#fef3c7,stroke:#f59e0b,stroke-width:1px,color:#78350f
  classDef viz fill:#dcfce7,stroke:#22c55e,stroke-width:1px,color:#14532d
  classDef group fill:transparent,stroke:#9ca3af,stroke-width:1px,color:#6b7280

  class P1,P2,P3,P4,P5 ds
  class P6,P7,P8,P9,P10 ai
  class P11,P12,P13 grd
  class P14,P15 de
  class P16,P17,P18,P19 fp
  class P20,P21 viz
  class DS,AI,GRD,DE,FP,VIZ group
```

## The projects

|   | Project | What it is | Built with | Try it |
|---|---------|------------|------------|--------|
| 📊 | [bayesian-mmm-runner](./bayesian-mmm-runner) | Works out how much each marketing channel actually drives sales, with honest uncertainty ranges, and suggests a better budget split | Python, Meridian | `python main.py --demo` |
| 🧪 | [causal-impact-model](./causal-impact-model) | Measures the true effect of an intervention by modelling what would have happened without it | Python, statsmodels | `python main.py --demo` |
| 📈 | [sos-revenue-econometrics](./sos-revenue-econometrics) | Tests whether brand demand sits on the path from spend to revenue, and with what time lag | Python, statsmodels | `python main.py --demo` |
| 🎲 | [bayesian-ab-engine](./bayesian-ab-engine) | An A/B test analyser that reports "B beats A with 92% probability" instead of a hard-to-read p-value | TypeScript | `npm run demo` |
| 📡 | [reach-frequency-dedup](./reach-frequency-dedup) | Counts how many real people a campaign reached without double-counting the overlap between channels | TypeScript | `npm run demo` |
| 🤖 | [agentic-sql-assistant](./agentic-sql-assistant) | An AI assistant that answers questions by writing and running its own database queries, behind a read-only guard | TypeScript | `npm run demo` |
| 📚 | [closed-book-rag](./closed-book-rag) | Answers only from a document library and refuses everything else, with the refusal threshold measured from the corpus rather than guessed | Python, stdlib | `python main.py --demo` |
| 🧠 | [share-of-ai-equity](./share-of-ai-equity) | Measures a brand's share of voice inside AI-generated answers, the new answer-engine visibility metric | Node.js | `npm run demo` |
| 🖼️ | [vision-ad-classifier](./vision-ad-classifier) | Sorts images by type, using an image model for the content and plain pixel maths for the format | Node.js | `npm run demo` |
| 🎓 | [correction-taught-classifier](./correction-taught-classifier) | A classifier that learns from human corrections immediately: retrieval with a similarity floor, cache-aware prompt injection, no retraining | Python, stdlib | `python main.py --demo` |
| 🚧 | [publish-gate](./publish-gate) | Refuses to publish machine-written copy until every checkable claim in it has been recomputed from the data it claims to describe | TypeScript | `npm run demo` |
| 🕰️ | [ai-output-watchdog](./ai-output-watchdog) | A deterministic nightly auditor for a generative system's pipelines, and the rule that silence is not failure | Python, stdlib | `python main.py --demo` |
| 🚦 | [fail-closed-gateway](./fail-closed-gateway) | Rate limiting and moderation for a paid LLM endpoint where a guard outage never becomes free compute | Node.js | `npm run demo` |
| ⚖️ | [source-precedence-ledger](./source-precedence-ledger) | Three systems report the same costs and disagree; this publishes one defensible figure per line, with the audit trail to back it | Python, stdlib | `python main.py --demo` |
| 🛡️ | [resilient-snapshot-pipeline](./resilient-snapshot-pipeline) | Keeps a dashboard from ever going blank when the data source it relies on is slow or flaky | TypeScript, SQLite | `npm run demo` |
| 📤 | [streaming-xlsx-export](./streaming-xlsx-export) | Streams huge spreadsheet exports without running out of memory, and blocks formula injection in cells | TypeScript | `npm run demo` |
| 📻 | [udp-request-reply](./udp-request-reply) | Builds request/response conversations on top of a fire-and-forget UDP protocol, including shared-port correlation | Python, stdlib | `python main.py --demo` |
| 🎤 | [hum-to-midi-tracker](./hum-to-midi-tracker) | Turns a hummed melody into real MIDI notes: pitch tracking, note segmentation and humane quantisation, from scratch | Python, numpy | `python main.py --demo` |
| 🗣️ | [chat-export-voice](./chat-export-voice) | Extracts only the human's messages from chat exports and distils how they actually write | Node.js | `npm run demo` |
| 🗺️ | [great-circle-route-map](./great-circle-route-map) | A world map with curved routes, drawn entirely by hand in SVG with no mapping library | React, Vite | `npm run dev` |
| 🎨 | [dataviz-techniques](./dataviz-techniques) | Three reusable chart techniques: a masked confidence band, a diverging heatmap scale, and an SVG gauge | React, Recharts | `npm run dev` |

## A bit more on each

### Data science and ML

**📊 bayesian-mmm-runner.** A marketing mix model. It reads years of weekly spend and sales,
estimates the return on each channel as a credible range rather than a single false-precision
number, then recommends how to rebalance the budget. The part worth reading is what makes a
research library behave safely in production.

**🧪 causal-impact-model.** Estimates the real effect of an intervention (a campaign starting, a
channel going dark) by modelling the counterfactual: what the metric would have done if nothing
had changed. It tries three modelling backends in turn and falls all the way back to a structural
time-series estimator written from scratch, so it still works with only a basic stats install.

**📈 sos-revenue-econometrics.** A classic econometrics pipeline that asks whether a brand-demand
signal sits between marketing spend and revenue, and how long the effect takes. Granger causality,
a vector auto-regression with automatic lag selection, and impulse-response curves with
bootstrapped confidence bands.

**🎲 bayesian-ab-engine.** A Bayesian take on A/B testing. It reports the probability that one
option beats another, and the expected cost of choosing wrong, both far easier to act on than a
p-value. The statistics are written from scratch with no libraries.

**📡 reach-frequency-dedup.** Audience reach is not additive, because audiences overlap. This
estimates the real de-duplicated reach and average frequency, and wraps the slow calculation in a
cache that answers instantly while it refreshes in the background.

### AI and agents

**🤖 agentic-sql-assistant.** Ask a question in plain English and it decides which database queries
to run, runs them, and answers. The core is a strict guard that lets only read-only queries
through, plus caching that never serves a stale live number.

**📚 closed-book-rag.** Retrieval over a document library that answers from the library or not at
all. The centrepiece is the refusal threshold. Rather than hand-waving a similarity cutoff, it runs
a labelled probe set through retrieval, measures where on-topic and off-topic questions actually
separate, and derives the floor from the gap, so an off-topic question is refused without the model
ever being called. It also treats answering from a superseded version of a document as worse than
not answering at all, which is a policy about the index, not about the model.

**🧠 share-of-ai-equity.** As people ask AI assistants "which product should I pick", this measures
how often and how prominently a brand appears in those answers, ranked by where it shows up and
backed by the answer's citations. A brand-visibility metric for the answer-engine era.

**🖼️ vision-ad-classifier.** It classifies images by what they show, using a vision model, and by
what format they are, using exact pixel dimensions. The demo shows why the split matters: the
pixel-based format stays stable across runs while the model guess wobbles.

**🎓 correction-taught-classifier.** A classifier that takes a human correction and applies it on
the very next document, with no retraining. Corrections are retrieved by similarity with a floor
that keeps loose matches out, and injected after the stable part of the prompt so the cache keeps
hitting on everything that never changes.

### AI guardrails

**🚧 publish-gate.** A generative system writes a weekly digest, and this refuses to publish it
until every claim in it that can be checked against data has been recomputed from that data. The
interesting parts are judgement rather than code. Tolerance is asymmetric, because counts only grow
and a claim sitting under the data is fine while one exceeding it is not. Claims are checked at the
altitude the copy actually aggregates at, because the first version blocked good editions by
testing something narrower than the sentence claimed. One implementation serves both the editor's
preview and the enforcing publish path, so the panel can never show green while the gate says red.
And the gate fails open, because a guard that becomes an outage is worse than no guard. It ships
with a backtest and a negative control, and is explicit that a backtest alone proves nothing, since
a validator that always passes scores perfectly on one.

**🕰️ ai-output-watchdog.** A generative system that briefs you daily will keep producing confident
output long after the pipelines feeding it have quietly died, because stale data reads exactly like
fresh data. This is the deterministic half of the audit: relentless about mechanics, silent about
quality, and careful not to flag sources whose silence is normal, because an alert that always
fires protects nothing.

**🚦 fail-closed-gateway.** Rate limiting and moderation in front of a paid model endpoint, built so
that an outage in the guard itself never turns into free compute for whoever noticed.

### Data engineering

**⚖️ source-precedence-ledger.** Three systems report the cost of the same work and none of them
agree. This resolves each line to one publishable figure with a full audit trail. Keys are
normalised before anything is compared, because real codes never match cleanly. Lines are admitted
on the value they carry rather than on what a status field claims. Precedence is expressed as data
rather than nested conditionals, so the whole policy is readable at a glance. And every precedence
flip carries a sanity bound, because taking the winning source silently when it disagrees by an
order of magnitude is exactly how one bad export becomes a published number. Beyond the bound a
line is escalated to a human rather than resolved.

**🛡️ resilient-snapshot-pipeline.** When the upstream source is slow and only returns part of the
data, this keeps the dashboard showing the last complete picture instead of a broken, half-empty
one. Built after a real incident where a single line of SQL blanked a live dashboard.

### Formats and protocols

**📤 streaming-xlsx-export.** Exports very large datasets to Excel by streaming rows straight to the
response instead of building the whole file in memory, so it never runs out of memory, and it
neutralises spreadsheet formula injection in every cell, a risk most exporters miss.

**📻 udp-request-reply.** Builds a request and response layer on top of a control protocol that is
pure fire-and-forget UDP: a codec written from scratch, a correlation table with timeouts, and
several processes sharing a single reply port.

**🎤 hum-to-midi-tracker.** Turns a hummed melody into real MIDI notes. The interesting part was
never the pitch model, it is what you have to do to raw pitch before it becomes music: segmenting a
wobbling contour into notes, and quantising human timing without flattening the phrasing.

**🗣️ chat-export-voice.** Pulls only the human's messages out of a chat export and distils how that
person actually writes.

### Data visualisation

**🗺️ great-circle-route-map.** A map with curved routes, built entirely by hand in SVG. The
projection, the curves, and the marker that points along the path are all done from first
principles, with no mapping library.

**🎨 dataviz-techniques.** Three small, reusable visualisation techniques shown side by side: a
confidence band faked with layer compositing (something the charting library cannot do natively), a
diverging colour scale anchored on a live midpoint, and a probability gauge drawn as a single SVG
arc.

## Running any project

Each folder is self-contained.

TypeScript and Node projects:

```bash
cd <project>
npm install && npm run demo
```

Five of the Python projects need nothing installed at all, because they are standard library only
(`closed-book-rag`, `source-precedence-ledger`, `ai-output-watchdog`,
`correction-taught-classifier`, `udp-request-reply`):

```bash
cd <project>
python main.py --demo
```

The four that do have dependencies (`bayesian-mmm-runner`, `causal-impact-model`,
`sos-revenue-econometrics`, `hum-to-midi-tracker`):

```bash
cd <project>
pip install -r requirements.txt && python main.py --demo
```

Web apps (`great-circle-route-map`, `dataviz-techniques`): `npm install && npm run dev`.

## Notes

Every data source in this repo is synthetic, every entity in it is invented, and every outside
service is faked behind a clean interface, so everything runs offline with no credentials and no
private data. Licensed under [MIT](./LICENSE).
