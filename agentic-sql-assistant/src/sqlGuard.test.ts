/**
 * Unit tests for the read-only SQL guard.
 *
 *   npm test
 *
 * Pure, dependency-free (node:test + node:assert), so the star of the module is
 * auditable in isolation.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { MAX_SQL_BYTES, SqlGuardError, validateSql } from "./sqlGuard";

test("allows a simple SELECT", () => {
  assert.equal(validateSql("SELECT 1"), "SELECT 1");
});

test("allows a WITH/CTE query", () => {
  const sql = "WITH t AS (SELECT 1 AS x) SELECT x FROM t";
  assert.equal(validateSql(sql), sql);
});

test("is case-insensitive on the leading keyword", () => {
  assert.equal(validateSql("select * from sales"), "select * from sales");
});

test("strips a single trailing semicolon", () => {
  assert.equal(validateSql("SELECT 1;"), "SELECT 1");
});

test("strips a line comment", () => {
  assert.equal(validateSql("SELECT 1 -- a comment"), "SELECT 1");
});

test("strips a leading block comment", () => {
  assert.equal(validateSql("/* note */ SELECT 1"), "SELECT 1");
});

test("rejects empty input", () => {
  assert.throws(() => validateSql("   "), SqlGuardError);
});

test("rejects a stacked (multi) statement", () => {
  assert.throws(() => validateSql("SELECT 1; DROP TABLE t"), SqlGuardError);
});

test("a comment cannot smuggle a second statement", () => {
  assert.throws(() => validateSql("SELECT 1 /* x */ ; DROP TABLE t"), SqlGuardError);
});

test("rejects non-SELECT leading keyword (UPDATE)", () => {
  assert.throws(() => validateSql("UPDATE sales SET amount = 0"), SqlGuardError);
});

for (const kw of [
  "DROP TABLE sales",
  "DELETE FROM sales WHERE 1=1",
  "INSERT INTO sales VALUES (1)",
  "ALTER TABLE sales ADD COLUMN x INT",
  "TRUNCATE TABLE sales",
  "MERGE INTO sales USING x ON 1=1",
  "PRAGMA table_info(sales)",
  "ATTACH DATABASE 'x' AS y",
]) {
  test(`rejects mutating statement: ${kw.split(" ")[0]}`, () => {
    assert.throws(() => validateSql(kw), SqlGuardError);
  });
}

test("rejects a query over the byte cap", () => {
  const big = "SELECT " + "1,".repeat(MAX_SQL_BYTES) + "1";
  assert.throws(() => validateSql(big), SqlGuardError);
});

test("does not false-positive on the replace() scalar function", () => {
  const sql = "SELECT replace(region, 'a', 'b') AS r FROM sales";
  assert.equal(validateSql(sql), sql);
});
