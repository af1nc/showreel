[← Showreel](..)

# 🤖 Agentic SQL Assistant

![AI & agents](https://img.shields.io/badge/AI_%26_agents-8b5cf6) ![TypeScript](https://img.shields.io/badge/TypeScript-3178c6?logo=typescript&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

A small, production-shaped **agentic RAG-over-SQL assistant**: you ask a question
in natural language, and a bounded LLM tool-calling loop inspects the database
schema, writes read-only SQL, runs it, and answers with the real numbers.

It is deliberately built on a **raw LLM tool-calling loop - no LangChain, no
agent framework.** The whole agent is one bounded `while` loop you can read in a
few minutes (`src/agent.ts`). It runs **100% offline with no API key**: a
deterministic `MockLLM` plays the role of the model, and a local SQLite database
plays the role of the warehouse.

```
npm install
npm run demo     # runs the agent end-to-end, offline
npm test         # unit tests for the SQL guard (the star)
npm run check    # type-check
```

> Requires **Node 22.5+** (uses the built-in `node:sqlite` module). There are
> **no runtime dependencies** - `npm install` only pulls the dev tooling
> (`tsx`, `typescript`, `@types/node`), so nothing native is compiled.
> Prefer `better-sqlite3`? It is a drop-in swap: same `prepare().all()` API.

## What it is

The pattern is the same one that powers "chat with your data" assistants:

1. A **system prompt** tells the model it may only state numbers that came from a
   tool, and must end every answer with a confidence line.
2. The model is given a few **tools** (schema inspection, read-only SQL, memory).
3. A **loop** lets the model call tools, see the results, and call again until it
   has enough to answer - the [ReAct](https://arxiv.org/abs/2210.03629) pattern,
   hand-rolled.

The `LLMClient` interface (`src/llmClient.ts`) is the only thing that touches a
model. **Plugging in a real model = implementing that one interface** and
translating these neutral types to/from the provider's function-calling format:

```ts
class OpenAILLM implements LLMClient {
  async generate(messages, options) { /* call the provider, map the response */ }
}
```

## The interesting part

Four things lift this above a naive `while (true)` around a chat call.

### 1. The read-only SQL guard - `src/sqlGuard.ts`

An LLM authors SQL that runs against a real database, so **every query string is
treated as hostile.** `validateSql` is tiny, pure, and unit-tested. In order, it:

- **strips comments first**, so nothing can hide inside `-- ...` or `/* ... */`;
- enforces a **byte cap** on the query text (a cost-DoS guard - a runaway model
  can't ship a megabyte of SQL);
- rejects any surviving **`;`** → kills stacked-query injection
  (`SELECT 1; DROP TABLE t`);
- requires the statement to **begin with `SELECT` or `WITH`** - everything else
  fails closed;
- applies a **denylist** of mutating keywords as belt-and-suspenders.

It fails closed: a keyword inside a string literal (`WHERE action = 'delete'`) is
rejected rather than risk letting a mutation through. The `run_sql` tool layers a
**result row cap and result-byte cap** on top, and a real backend would add a
scan/cost cap at the driver level too.

### 2. Per-round parallel tool execution - `src/agent.ts`

When the model issues several independent calls in one turn (e.g. "this month"
and "last month" at once), they execute **concurrently** with `Promise.all`, and
the responses are fed back in the **same order** the model asked for them. Step 3
of the demo shows two SQL queries running in a single round.

### 3. Soft-deadline reasoning-budget degradation - `src/agent.ts`

Past a time budget, the agent **drops the tools and lowers the thinking level**
on the next model call. That forces the model to answer with what it already has
instead of hanging mid-investigation - graceful degradation instead of a
timeout. Step 4 of the demo forces this path.

### 4. Volatile-vs-stable answer caching - `src/agent.ts`

Answers are cached by a **normalized-question hash** - but **only when no
volatile tool was used**. `run_sql` is marked volatile, so any answer containing
a live number is never cached; a purely definitional/schema answer is. This
gives instant repeat answers for stable questions **without ever serving a stale
number.** Steps 1 and 2 of the demo show the same shape of question being cached in
one case and recomputed in the other.

## Files

| File | Role |
|---|---|
| `src/sqlGuard.ts` | The read-only SQL guard (the star). Pure + unit-tested. |
| `src/llmClient.ts` | `LLMClient` interface + deterministic `MockLLM`. |
| `src/agent.ts` | The tool loop, deadline degradation, and answer cache. |
| `src/tools.ts` | `run_sql`, `get_schema`, `save_memory` over `node:sqlite` + JSON. |
| `src/demo.ts` | Seeds a `sales` table and runs the five scenarios. |
| `src/sqlGuard.test.ts` | Unit tests for the guard. |

## What was stubbed (and why it doesn't change the architecture)

This module was extracted from a larger internal assistant. To make it a
standalone, runnable portfolio piece, the external dependencies were replaced
with local equivalents behind the same interfaces:

- **The model** (originally a hosted Gemini function-calling endpoint) → a
  deterministic `MockLLM` behind the `LLMClient` interface. Swap in
  Gemini/OpenAI by implementing that one interface.
- **The tools** (originally ~13 tools over a cloud data warehouse and a
  document store - knowledge-base search, data-recency checks, usage analytics,
  etc.) → three generic tools over a local **SQLite** DB (`node:sqlite`) and a
  **JSON** file: `run_sql`, `get_schema`, `save_memory`. The loop, the guard,
  the caching, and the parallelism are all identical to the original.
- **The answer cache / conversation store** (originally a hosted document store)
  → an in-memory `AnswerCache` implementation. Swap for Redis/SQLite/a document
  store by implementing the interface.

The interesting engineering - the bounded ReAct loop, the SQL guard, the
per-round parallelism, the soft-deadline degradation, and the volatile-vs-stable
cache - is real and unchanged.

---

MIT · Part of [Showreel](..), twelve standalone engineering projects.
