/**
 * demo - seeds a tiny SQLite database and runs the agent end-to-end, offline.
 *
 *   npm run demo
 *
 * It walks through the five ideas that make the loop interesting:
 *   1. a live SQL question (volatile -> never cached)
 *   2. a stable schema question (cacheable -> instant on the second ask)
 *   3. parallel tool calls in a single round
 *   4. soft-deadline degradation
 *   5. the read-only SQL guard blocking hostile queries
 */
import { DatabaseSync } from "node:sqlite";
import { resolve } from "node:path";
import { Agent, InMemoryAnswerCache } from "./agent";
import { validateSql } from "./sqlGuard";
import { createToolset } from "./tools";
import {
  MockLLM,
  lastToolTurnResults,
  type LLMMessage,
  type MockScript,
} from "./llmClient";

// ---------------------------------------------------------------------------
// Seed a generic `sales` table spanning the last few calendar months.
// ---------------------------------------------------------------------------

function seedDb(): DatabaseSync {
  const db = new DatabaseSync(":memory:");
  db.exec(`
    CREATE TABLE sales (
      id         INTEGER PRIMARY KEY,
      order_date TEXT    NOT NULL,
      region     TEXT    NOT NULL,
      product    TEXT    NOT NULL,
      amount     REAL    NOT NULL
    );
  `);

  const now = new Date();
  const y = now.getUTCFullYear();
  const m = now.getUTCMonth();
  const dateIn = (monthOffset: number, day: number) =>
    new Date(Date.UTC(y, m + monthOffset, day)).toISOString().slice(0, 10);

  const rows: Array<[string, string, string, number]> = [
    // this month so far -> total 2,400
    [dateIn(0, 3), "North", "Widget", 1500],
    [dateIn(0, 6), "South", "Gadget", 900],
    // last month -> total 4,200 across 3 orders
    [dateIn(-1, 4), "North", "Widget", 1200],
    [dateIn(-1, 12), "East", "Gadget", 1800],
    [dateIn(-1, 22), "West", "Widget", 1200],
    // two months ago
    [dateIn(-2, 8), "North", "Gadget", 800],
    [dateIn(-2, 19), "South", "Widget", 1100],
  ];

  const insert = db.prepare(
    "INSERT INTO sales (order_date, region, product, amount) VALUES (?, ?, ?, ?)",
  );
  db.exec("BEGIN");
  for (const r of rows) insert.run(...r);
  db.exec("COMMIT");
  return db;
}

// ---------------------------------------------------------------------------
// Scripted LLM behaviour (deterministic, offline)
// ---------------------------------------------------------------------------

const LAST_MONTH_TOTAL =
  "SELECT SUM(amount) AS total_sales, COUNT(*) AS orders FROM sales " +
  "WHERE order_date >= date('now','start of month','-1 month') " +
  "AND order_date < date('now','start of month')";

const usd = (n: number) =>
  "$" + Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

const scripts: MockScript[] = [
  {
    // "What were total sales last month?"  -> schema, then SQL, then answer.
    match: "total sales last month",
    steps: [
      { call: [{ name: "get_schema", args: { table: "sales" } }] },
      {
        call: [
          { name: "run_sql", args: { sql: LAST_MONTH_TOTAL, reason: "total sales last month" } },
        ],
      },
      {
        final: (m: LLMMessage[]) => {
          const row = (lastToolTurnResults(m)[0]?.response.result as any)?.rows?.[0] ?? {};
          const total = Number(row.total_sales ?? 0);
          const orders = Number(row.orders ?? 0);
          return (
            `Total sales last month were ${usd(total)} across ${orders} orders ` +
            "(queried the `sales` table, filtered to the previous calendar month).\n\n" +
            "Confidence: High - grounded in a live SUM over the sales table for the previous month."
          );
        },
      },
    ],
  },
  {
    // "What columns does the sales table have?"  -> schema, then answer.
    // Uses only get_schema (non-volatile) so the answer is cacheable.
    match: "columns",
    steps: [
      { call: [{ name: "get_schema", args: { table: "sales" } }] },
      {
        final: (m: LLMMessage[]) => {
          const schema = lastToolTurnResults(m)[0]?.response.result as Array<{
            table: string;
            columns: Array<{ column: string; type: string }>;
          }>;
          const t = schema?.[0];
          const cols = (t?.columns ?? []).map((c) => `${c.column} (${c.type})`).join(", ");
          return (
            `The \`${t?.table ?? "sales"}\` table has these columns: ${cols}.\n\n` +
            "Confidence: High - read directly from the database schema."
          );
        },
      },
    ],
  },
  {
    // "Compare sales this month vs last month."  -> TWO SQL calls in ONE round.
    match: "compare",
    steps: [
      {
        call: [
          { name: "run_sql", args: { sql: LAST_MONTH_TOTAL, reason: "sales last month" } },
          {
            name: "run_sql",
            args: {
              sql: "SELECT SUM(amount) AS total FROM sales WHERE order_date >= date('now','start of month')",
              reason: "sales this month so far",
            },
          },
        ],
      },
      {
        final: (m: LLMMessage[]) => {
          const res = lastToolTurnResults(m);
          const last = Number((res[0]?.response.result as any)?.rows?.[0]?.total_sales ?? 0);
          const curr = Number((res[1]?.response.result as any)?.rows?.[0]?.total ?? 0);
          const delta = curr - last;
          return (
            `Last month: ${usd(last)}. This month so far: ${usd(curr)} ` +
            `(${delta >= 0 ? "+" : "-"}${usd(Math.abs(delta))} vs last month).\n\n` +
            "Confidence: Medium - this month is month-to-date, so the comparison is partial."
          );
        },
      },
    ],
  },
];

const degraded = () =>
  "For a quick take: sales live in the `sales` table (amount by order_date). " +
  "Ask me to dig deeper and I'll run the exact figures.";

const SYSTEM_PROMPT = `You are an agentic data-analytics assistant. Today is ${new Date()
  .toISOString()
  .slice(0, 10)}.

# ACCURACY
1. NEVER invent a number, name, or date. Every figure you state must come from a tool result in THIS conversation (run_sql). If you have not retrieved it, do not state it.
2. Call get_schema before querying a table for the first time - never guess column names.
3. End every answer with a line in this exact format: "Confidence: High/Medium/Low - <one-line reason>."

# TOOLS
- get_schema: inspect the database schema.
- run_sql: run a read-only SELECT. Always aggregate (GROUP BY) and include a LIMIT.
- save_memory: persist a durable, reusable fact. Use sparingly.

# WORKFLOW
- Definitional / schema questions -> get_schema.
- "how much / how many" -> run_sql, then report with the filters you used.
- Batch INDEPENDENT queries into a SINGLE turn so they run in parallel.`;

// ---------------------------------------------------------------------------
// Pretty printing
// ---------------------------------------------------------------------------

function section(title: string): void {
  console.log("\n" + "=".repeat(72) + "\n" + title + "\n" + "=".repeat(72));
}

function printRound(info: {
  round: number;
  kind: string;
  overDeadline: boolean;
  calls?: Array<{ name: string; args: Record<string, unknown> }>;
}): void {
  if (info.kind === "tools" && info.calls) {
    const names = info.calls
      .map((c) => {
        const a = c.args.table
          ? `table=${c.args.table}`
          : c.args.reason
            ? `"${c.args.reason}"`
            : "";
        return `${c.name}(${a})`;
      })
      .join("  +  ");
    const parallel = info.calls.length > 1 ? `  [${info.calls.length} in parallel]` : "";
    console.log(`  round ${info.round}: -> ${names}${parallel}`);
  } else {
    const tag = info.overDeadline ? " (deadline: tools dropped, reasoning lowered)" : "";
    console.log(`  round ${info.round}: -> final answer${tag}`);
  }
}

async function run(agent: Agent, question: string): Promise<void> {
  console.log(`\nQ: ${question}`);
  const res = await agent.ask(question);
  const trace = res.toolTrace
    .map((t) => `${t.tool}${t.error ? " (error)" : ""} ${t.detail} [${t.ms}ms]`)
    .join("\n     ");
  console.log(`  cached: ${res.cached}`);
  console.log(`  tools: ${trace || "(none)"}`);
  console.log(`\n  A: ${res.reply.replace(/\n/g, "\n     ")}`);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const db = seedDb();
  const toolset = createToolset(db, resolve(".data/memory.json"));
  const cache = new InMemoryAnswerCache();
  const llm = new MockLLM(scripts, degraded);

  const agent = new Agent({
    llm,
    toolset,
    systemPrompt: SYSTEM_PROMPT,
    cache,
    onRound: printRound,
  });

  section("1) Live SQL question - uses run_sql (VOLATILE), so it is NOT cached");
  await run(agent, "What were total sales last month?");
  console.log("\n  -- ask the SAME question again --");
  await run(agent, "What were total sales last month?");
  console.log("\n  (recomputed both times: live numbers are never served stale)");

  section("2) Stable schema question - uses get_schema only, so it IS cached");
  await run(agent, "What columns does the sales table have?");
  console.log("\n  -- ask the SAME question again --");
  await run(agent, "What columns does the sales table have?");
  console.log("\n  (second ask returned instantly from the answer cache)");

  section("3) Parallel tool calls in one round (order preserved)");
  await run(agent, "Compare sales this month vs last month.");

  section("4) Soft-deadline degradation (tools dropped, reasoning lowered)");
  const impatient = new Agent({
    llm,
    toolset,
    systemPrompt: SYSTEM_PROMPT,
    softDeadlineMs: -1, // force "over deadline" on the very first round
    onRound: printRound,
  });
  await run(impatient, "What were total sales last month?");

  section("5) The read-only SQL guard (the star) blocking hostile queries");
  guardShowcase();

  db.close();
}

function guardShowcase(): void {
  const cases: Array<{ label: string; sql: string }> = [
    { label: "legit aggregate", sql: "SELECT COUNT(*) AS n FROM sales" },
    { label: "legit CTE", sql: "WITH t AS (SELECT 1 AS x) SELECT x FROM t" },
    { label: "DROP TABLE", sql: "DROP TABLE sales" },
    { label: "UPDATE", sql: "UPDATE sales SET amount = 0" },
    { label: "stacked statement", sql: "SELECT 1; DELETE FROM sales" },
    { label: "comment-smuggled statement", sql: "SELECT 1 /* hide */ ; DROP TABLE sales" },
    { label: "PRAGMA", sql: "PRAGMA table_info(sales)" },
    { label: "oversized query", sql: "SELECT " + "1,".repeat(6000) + "1" },
  ];
  for (const c of cases) {
    try {
      validateSql(c.sql);
      console.log(`  ALLOWED  ${c.label}`);
    } catch (e) {
      console.log(`  BLOCKED  ${c.label} -> ${(e as Error).message}`);
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
