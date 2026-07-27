/**
 * sqlGuard - a read-only SQL guard for an LLM-driven `run_sql` tool.
 *
 * This is the security heart of the assistant. An LLM is allowed to author SQL
 * and run it against a real database, so EVERY string it produces is treated as
 * hostile until proven read-only. The guard is intentionally small, pure, and
 * unit-testable so it can be audited at a glance.
 *
 * It enforces five things, in order:
 *   1. Comments are stripped first, so nothing can be smuggled past the checks
 *      inside a `-- ...` line comment or a block comment.
 *   2. A single byte cap on the query text (a cost-DoS guard - a compromised or
 *      runaway model cannot ship a megabyte of SQL).
 *   3. Single statement only: any surviving `;` is rejected, which kills the
 *      classic "stacked query" injection (`SELECT 1; DROP TABLE t`).
 *   4. The statement MUST begin with SELECT or WITH (a CTE). Everything else
 *      (DDL/DML/transaction control) fails closed.
 *   5. A denylist of mutating keywords, as belt-and-suspenders behind (3)+(4).
 *
 * Note on (5): the denylist matches keywords even inside string literals, so a
 * legitimate `WHERE action = 'delete'` is rejected. That is deliberate - for a
 * security guard, failing closed on a rare false positive is the correct trade
 * versus ever letting a mutation through. Callers should also enforce a row/byte
 * cap on the RESULT and a scan/cost cap at the driver level (see tools.ts).
 */

/** Hard cap on the size of a single query string. */
export const MAX_SQL_BYTES = 8_000;

/**
 * Mutating / side-effecting keywords. `replace` is deliberately absent because
 * it collides with the SQL scalar function `replace(str, from, to)` used in
 * legitimate SELECTs; stacked-statement and leading-keyword checks cover the
 * `REPLACE INTO` DML form.
 */
const MUTATING_KEYWORDS =
  /\b(insert|update|delete|merge|drop|create|alter|truncate|grant|revoke|call|begin|commit|rollback|savepoint|attach|detach|pragma|vacuum|reindex|export|load|copy)\b/i;

export class SqlGuardError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SqlGuardError";
  }
}

/**
 * Validate that `sql` is a single read-only statement and return the cleaned,
 * comment-stripped SQL ready to execute. Throws {@link SqlGuardError} otherwise.
 */
export function validateSql(sql: string): string {
  const stripped = sql
    .replace(/--[^\n]*/g, " ") // line comments
    .replace(/\/\*[\s\S]*?\*\//g, " ") // block comments
    .trim()
    .replace(/;+\s*$/, ""); // a single trailing semicolon is fine

  if (!stripped) {
    throw new SqlGuardError("Empty SQL");
  }
  if (Buffer.byteLength(stripped, "utf8") > MAX_SQL_BYTES) {
    throw new SqlGuardError(
      `Query exceeds the ${MAX_SQL_BYTES}-byte cap (cost-DoS guard)`,
    );
  }
  if (stripped.includes(";")) {
    throw new SqlGuardError("Only a single SQL statement is allowed");
  }
  if (!/^(select|with)\b/i.test(stripped)) {
    throw new SqlGuardError("Only SELECT / WITH queries are allowed (read-only)");
  }
  if (MUTATING_KEYWORDS.test(stripped)) {
    throw new SqlGuardError("Query contains a forbidden keyword (read-only tool)");
  }
  return stripped;
}
