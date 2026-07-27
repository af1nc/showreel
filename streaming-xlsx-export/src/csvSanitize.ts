/**
 * Formula-injection guard for CSV / XLSX cells.
 *
 * When a spreadsheet cell starts with `=`, `+`, `-`, `@`, TAB or CR, Excel and
 * Google Sheets interpret it as a formula. That includes dangerous DDE payloads
 * (for example `=cmd|' /C calc'!A0`) that can execute commands the moment a user
 * opens an otherwise "just data" export. Prefixing the value with a tab forces
 * text interpretation while staying visually invisible in the rendered cell.
 *
 * Most export code forgets this step entirely. It lives here as a pure,
 * unit-testable function so it can be reused by any writer (XLSX, CSV, etc.).
 */

/** Characters that make a spreadsheet treat a leading string as a formula. */
const FORMULA_TRIGGER = /^[=+\-@\t\r]/;

/**
 * Sanitise a single value for safe use as a spreadsheet cell.
 *
 * - Numbers, booleans and dates pass through unchanged (not injectable).
 * - Strings that begin with a formula trigger get a leading tab.
 * - null / undefined are returned as-is (the writer renders them empty).
 */
export function sanitizeCellValue(value: unknown): unknown {
  if (value === null || value === undefined) return value;
  if (typeof value !== "string") return value;
  if (FORMULA_TRIGGER.test(value)) {
    return `\t${value}`;
  }
  return value;
}

/**
 * Sanitise every value in a row object, returning a new object.
 * Handy when a whole record needs guarding before it reaches a writer.
 */
export function sanitizeRow<T extends Record<string, unknown>>(row: T): T {
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(row)) {
    out[key] = sanitizeCellValue(row[key]);
  }
  return out as T;
}
