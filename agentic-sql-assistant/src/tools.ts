/**
 * tools - the concrete capabilities the agent can call.
 *
 * This replaces a dozen cloud-specific tools (a document-store knowledge search,
 * a cloud data-warehouse query runner, usage analytics, etc.) with three
 * generic, fully-local ones so the demo runs offline:
 *
 *   - run_sql     read-only SQL against a local SQLite database, guarded by the
 *                 SQL guard, with a row cap AND a result-byte cap.
 *   - get_schema  the database schema (tables + columns), so the model never
 *                 has to guess column names.
 *   - save_memory persist a durable fact to a local JSON file.
 *
 * Swapping in a real backend is a matter of reimplementing `execute` - the
 * agent only sees the `Toolset` shape.
 *
 * The database is Node's built-in `node:sqlite` (zero dependencies, no native
 * build). `better-sqlite3` is a drop-in alternative - it exposes the same
 * `prepare().all()` / `prepare().run()` / `exec()` surface used here.
 */
import { DatabaseSync } from "node:sqlite";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { validateSql } from "./sqlGuard";
import type { ToolSchema } from "./llmClient";

/** Max rows returned to the model from a single query. */
export const MAX_SQL_ROWS = 300;
/** Max serialized size of a tool result handed back to the model. */
export const MAX_RESULT_BYTES = 256 * 1024;

/**
 * A tool that reads live data. Answers that used a volatile tool must NEVER be
 * cached, so fresh numbers are never served stale. `run_sql` is the only
 * volatile tool here; `get_schema` and `save_memory` are stable.
 */
const VOLATILE_TOOLS = new Set(["run_sql"]);

export interface Toolset {
  /** Schemas advertised to the model. */
  schemas: ToolSchema[];
  /** Run one tool call and return its result plus a short human-readable detail. */
  execute(
    name: string,
    args: Record<string, unknown>,
  ): Promise<{ result: unknown; detail: string }>;
  /** Whether a tool's output is time-sensitive (uncacheable). */
  isVolatile(name: string): boolean;
}

function quoteIdent(name: string): string {
  return '"' + name.replace(/"/g, '""') + '"';
}

/** Build a Toolset bound to a SQLite database and a JSON memory file. */
export function createToolset(
  db: DatabaseSync,
  memoryPath: string,
): Toolset {
  const schemas: ToolSchema[] = [
    {
      name: "get_schema",
      description:
        "Get the tables and their columns in the database. ALWAYS call this before querying a table for the first time - never guess column names. Pass a table name to inspect just that table, or omit it to list everything.",
      parameters: {
        type: "object",
        properties: {
          table: {
            type: "string",
            description: "Optional table name to inspect. Omit to list all tables.",
          },
        },
      },
    },
    {
      name: "run_sql",
      description:
        "Run a read-only SQL SELECT and get rows back (max 300). Use for any factual number. Always aggregate (GROUP BY) rather than pulling raw rows, and always include a LIMIT.",
      parameters: {
        type: "object",
        properties: {
          sql: {
            type: "string",
            description: "A single read-only SELECT / WITH statement",
          },
          reason: {
            type: "string",
            description: "One line: what question this answers",
          },
        },
        required: ["sql", "reason"],
      },
    },
    {
      name: "save_memory",
      description:
        "Persist a durable fact worth remembering across conversations (user preferences, corrections, recurring context). Use sparingly, only for genuinely reusable facts.",
      parameters: {
        type: "object",
        properties: {
          fact: {
            type: "string",
            description: "The fact to remember, one or two sentences",
          },
        },
        required: ["fact"],
      },
    },
  ];

  async function execute(
    name: string,
    args: Record<string, unknown>,
  ): Promise<{ result: unknown; detail: string }> {
    switch (name) {
      case "get_schema": {
        const only = args.table ? String(args.table) : null;
        const tables = db
          .prepare(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
          )
          .all()
          .map((r: any) => r.name as string);
        const targets = only ? tables.filter((t) => t === only) : tables;
        if (only && targets.length === 0) {
          return {
            result: { error: `Unknown table: ${only}`, tables },
            detail: `${only} (not found)`,
          };
        }
        const schema = targets.map((t) => ({
          table: t,
          // PRAGMA cannot be parameterized; `t` is sourced from sqlite_master
          // (trusted), and quoted defensively.
          columns: db
            .prepare(`PRAGMA table_info(${quoteIdent(t)})`)
            .all()
            .map((c: any) => ({ column: c.name as string, type: c.type as string })),
        }));
        return { result: schema, detail: `${schema.length} table(s)` };
      }

      case "run_sql": {
        const sql = validateSql(String(args.sql ?? ""));
        const reason = String(args.reason ?? "query");
        // Audit trail: every model-authored query is logged before execution.
        // Wire the actor identity in from your auth layer in production.
        console.log(
          `[audit] run_sql reason="${reason}" sql=${sql.replace(/\s+/g, " ").slice(0, 300)}`,
        );

        const allRows = db.prepare(sql).all() as unknown[];
        const rowCount = allRows.length;
        const truncated = rowCount > MAX_SQL_ROWS;
        let rows = allRows.slice(0, MAX_SQL_ROWS);

        // Result-byte cap: shrink the row window until it fits, so a wide result
        // set can't blow the context window (a second cost-DoS guard).
        while (
          rows.length > 1 &&
          Buffer.byteLength(JSON.stringify(rows), "utf8") > MAX_RESULT_BYTES
        ) {
          rows = rows.slice(0, Math.ceil(rows.length / 2));
        }

        return {
          result: { rows, rowCount, truncated: truncated || rows.length < allRows.length },
          detail: `${reason} → ${rowCount} row(s)${rowCount > rows.length ? " (truncated)" : ""}`,
        };
      }

      case "save_memory": {
        const fact = String(args.fact ?? "").slice(0, 500);
        if (!fact) throw new Error("fact is required");
        mkdirSync(dirname(memoryPath), { recursive: true });
        const list: Array<{ fact: string; created_at: string }> = existsSync(memoryPath)
          ? JSON.parse(readFileSync(memoryPath, "utf8"))
          : [];
        list.push({ fact, created_at: new Date().toISOString() });
        writeFileSync(memoryPath, JSON.stringify(list, null, 2));
        return { result: { saved: true }, detail: fact.slice(0, 80) };
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  }

  return { schemas, execute, isVolatile: (n) => VOLATILE_TOOLS.has(n) };
}
