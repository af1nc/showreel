[← Showreel](..)

# 🧠 Share of AI

![AI & agents](https://img.shields.io/badge/AI_%26_agents-8b5cf6) ![Node.js](https://img.shields.io/badge/Node.js-339933?logo=nodedotjs&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

Measure a brand's share of voice inside generative AI answers.

When people used to ask Google "what is the best project management tool", brands
competed for the ten blue links. Now people ask an AI assistant the same question
and get one synthesised answer that names a handful of brands, in order, with
citations. **Share of AI** is the metric for that new surface: of all the brand
mentions an answer engine produces for your category, how many are yours, how
early do you appear, and which sources is the model citing. This is the core of
the emerging "answer engine optimisation" (AEO) discipline.

This repository is a small, self-contained, runnable implementation of the idea.
It runs fully offline against a mock answer engine, so you can see the whole
pipeline work without an API key or any cloud services.

## The interesting part

Four things carry the weight here:

1. **Grounded generation.** A useful answer engine does not just generate text,
   it grounds that text on live web search and returns the sources it used. The
   client interface captures exactly that: `ask(question)` returns both the
   answer `text` and its `citations`. Citation parsing turns raw grounding
   metadata into clean `{ title, url, domain }` records.

2. **First-appearance ranking.** Inside a single answer, being named first is
   worth more than being named last. Each brand is ranked by the character
   position of its first mention, and the headline score weights each appearance
   by `1 / rank`. A brand that consistently leads answers wins even if a rival is
   mentioned more times overall.

3. **Word-boundary matching.** Brand detection uses whole-word regex matching
   (`\b ... \b`). This is what stops a short brand token from false-matching
   inside a longer, unrelated phrase. In the demo, the answer for "best project
   management tools" mentions the phrase "Brand Analytics"; the matcher correctly
   does **not** count that as a mention of the brand "Brand A". Variants of a
   brand are also sorted longest-first so the most specific spelling wins.

4. **A simple, explainable score.** No black box. Share of AI is a brand's
   rank-weighted points as a percentage of all brands' points across every
   answer, reported alongside plain visibility, mention share, and average rank
   so you can see how the headline number is built.

## Run it

Requires Node 18 or newer. No dependencies, no install step, no API key.

```bash
npm run demo
```

You will see:

- a **Share of AI scoreboard** ranking each brand by first-appearance-weighted
  score, with visibility, mention share, and average rank alongside,
- the **per-answer first-appearance ranking** for every question, and
- a **citations-by-domain** summary of the grounding sources.

The full structured result set is written to `output/results.json` (one record
per question, with the ranked brand list, citations, and per-answer scores).

## How it fits together

```
config/queries.json   category questions (global + per-market templates)
config/brands.json    tracked brands, aliases, and grouping
        |
        v
src/llmClient.js      ask(question) -> { text, citations }   (MockLLM here)
        |
        v
src/shareOfAi.js      brand matching -> first-appearance ranking -> citations
                      -> per-answer rows -> Share of AI scoreboard
        |
        v
src/demo.js           prints tables + writes output/results.json
```

## Plugging in a real answer engine

Everything routes through one interface in `src/llmClient.js`:

```js
ask(question) -> Promise<{ text: string, citations: Array<{ title, url }> }>
```

To track real Share of AI, implement that one method against a real grounded LLM
(for example Gemini or OpenAI, with web / search grounding turned on), map the
provider's grounding metadata into the `{ title, url }` citation shape, and pass
your class to `runShareOfAi` in place of `MockLLM`. Nothing else changes. Read a
secret only from the environment, with no hard-coded fallback:

```js
const key = process.env.LLM_API_KEY; // throw if missing; never inline a default
```

## What was stubbed (and why)

This is a portfolio extract of a production module, reduced to its reusable core.
Three things are deliberately swapped for local, generic equivalents:

- **The grounded LLM is a MockLLM behind an interface.** The real system calls a
  hosted answer engine with search grounding on a schedule. Here, `MockLLM`
  returns canned, deterministic answers so the demo is reproducible offline.
  Swapping in a real provider means implementing the single `ask()` method.
- **The data warehouse is local JSON.** The real system writes one row per
  (question, market, run) into a partitioned analytics warehouse table. Here the
  same rows are written to `output/results.json`.
- **The brands and questions are generic.** Real deployments track a named brand
  against its named competitors in a specific category. Here everything is
  neutral: "Brand A" through "Brand E" across generic software categories
  (project management, cloud databases, CRM), with a small set of example
  markets.

## Extending

- **Questions:** edit `config/queries.json`. Each entry needs `id`, `scope`
  (`global` or `per-market`), `topic`, `journey`, `audience`, and `text`.
  Per-market questions use `{market_label}` as a placeholder.
- **Markets:** edit `config/queries.json` under `markets`. Each needs `code`,
  `label` (substituted into per-market text), and `dashboard_code`.
- **Brands:** edit `config/brands.json`. Add real spelling variants as
  `aliases`; never add bare generic words as aliases, or you will get false
  matches.

---

MIT · Part of [Showreel](..), twelve standalone engineering projects.
