/**
 * Streaming, chunked XLSX export toolkit.
 *
 * The design has three moving parts, all independent of any particular data
 * source or web framework:
 *
 *  1. `writeRowsToXlsxStream` - streams rows straight into a Writable using
 *     ExcelJS's WorkbookWriter with shared strings and styles turned off, so an
 *     arbitrarily large result set is never held in memory all at once. It
 *     accepts a plain array OR a (sync / async) generator, so a caller can feed
 *     rows lazily and let each row be written and garbage-collected.
 *
 *  2. A chunked / paged transport: a count handler reports the total rows and
 *     how many 50,000-row parts the download splits into; an export handler
 *     streams a single part. A client loops part 1..N, downloading each file in
 *     turn. No single file, request or buffer ever grows without bound.
 *
 *  3. Higher-order handler factories (`makeCountHandler` / `makeExportHandler`)
 *     that take an injected slice function and count function. Point them at any
 *     data source (a SQL warehouse, an in-memory list, a REST paginator) and the
 *     same streaming machinery serves it.
 */

import type { Writable } from "node:stream";
import ExcelJS from "exceljs";
import { sanitizeCellValue } from "./csvSanitize";

/** Rows per exported file part. Keeps each file and each fetch bounded. */
export const PART_SIZE = 50_000;

/** A single output record: a flat map of column name to cell value. */
export type Row = Record<string, unknown>;

/** Opaque, caller-defined filter/selection object passed through untouched. */
export type Filters = Record<string, unknown>;

/** Injected fetcher: return up to `limit` rows starting at `offset`. */
export type SliceFn = (filters: Filters, limit: number, offset: number) => Promise<Row[]>;

/** Injected counter: total rows for these filters, ignoring pagination. */
export type CountFn = (filters: Filters) => Promise<number>;

/**
 * Flatten a warehouse-style wrapped date value.
 *
 * Some analytics warehouses return DATE columns as an object of the shape
 * `{ value: 'YYYY-MM-DD' }` rather than a scalar. Unwrap that to the inner
 * value so it renders as a plain cell. Anything else is returned unchanged.
 */
export function flattenWarehouseDate(value: unknown): unknown {
  if (value && typeof value === "object" && "value" in (value as object)) {
    return (value as { value: unknown }).value;
  }
  return value;
}

/** Options for the streaming writer. */
export interface WriteXlsxOptions {
  /** Worksheet name. Defaults to "Data". */
  sheetName?: string;
  /**
   * Explicit column order. If omitted, columns are taken from the keys of the
   * first row. Provide this when feeding a generator so the header is
   * deterministic and never depends on peeking the stream.
   */
  columns?: string[];
  /** Column width applied to every column. Defaults to 18. */
  columnWidth?: number;
  /** Message written as a single cell when there are zero rows. */
  emptyMessage?: string;
}

/**
 * Stream rows into `stream` as an XLSX workbook.
 *
 * Every cell is unwrapped (warehouse date objects) and sanitised (formula
 * injection guard) before it is committed. Rows are committed one at a time and
 * released, so peak memory stays flat regardless of the total row count.
 *
 * @returns the number of data rows written.
 */
export async function writeRowsToXlsxStream(
  rows: Iterable<Row> | AsyncIterable<Row>,
  stream: Writable,
  options: WriteXlsxOptions = {},
): Promise<number> {
  const {
    sheetName = "Data",
    columnWidth = 18,
    emptyMessage = "No data for this selection",
  } = options;

  const workbook = new ExcelJS.stream.xlsx.WorkbookWriter({
    stream,
    useStyles: false,
    useSharedStrings: false,
  });
  const sheet = workbook.addWorksheet(sheetName);

  let columns = options.columns;
  let headerReady = false;

  const applyColumns = (cols: string[]): void => {
    sheet.columns = cols.map((name) => ({ header: name, key: name, width: columnWidth }));
    headerReady = true;
  };

  if (columns && columns.length > 0) {
    applyColumns(columns);
  }

  let written = 0;

  // `for await ... of` iterates both sync arrays and async generators, so a
  // caller can hand over a materialised slice or a lazy stream of rows.
  for await (const row of rows as AsyncIterable<Row>) {
    if (!headerReady) {
      columns = Object.keys(row);
      applyColumns(columns);
    }

    const flat: Row = {};
    for (const name of columns as string[]) {
      flat[name] = sanitizeCellValue(flattenWarehouseDate(row[name]));
    }
    sheet.addRow(flat).commit();
    written += 1;
  }

  if (written === 0) {
    sheet.addRow([emptyMessage]).commit();
  }

  await sheet.commit();
  await workbook.commit();
  return written;
}

/* -------------------------------------------------------------------------- */
/* Framework-agnostic HTTP glue                                               */
/*                                                                            */
/* These minimal interfaces describe only what the handlers touch. Express'   */
/* Request / Response / NextFunction are structurally compatible, so the       */
/* factories can be mounted directly on an Express app (see server.ts) without */
/* this module depending on Express.                                          */
/* -------------------------------------------------------------------------- */

/** Minimal request shape: just the parsed query string. */
export interface ExportRequest {
  query: Record<string, unknown>;
}

/** Minimal response shape: a Writable that can also set headers and send JSON. */
export interface ExportResponse extends Writable {
  setHeader(name: string, value: string): unknown;
  json(body: unknown): unknown;
}

/** Error-forwarding callback (Express-compatible). */
export type ExportNext = (err?: unknown) => void;

/** Coerce an unknown query value to a positive integer, with a fallback. */
function toInt(value: unknown, fallback: number): number {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/** Build a filename-safe `_START_to_END` suffix from date-like filters. */
function buildDateSuffix(filters: Filters): string {
  const clean = (value: unknown): string => String(value ?? "").replace(/[^0-9-]/g, "");
  const start = clean(filters.startDate);
  const end = clean(filters.endDate);
  return start && end ? `_${start}_to_${end}` : "";
}

/**
 * Build a count handler. Returns `{ count, parts, partSize }` so the client
 * knows how many part files to request.
 */
export function makeCountHandler(
  countFn: CountFn,
  parseFilters: (req: ExportRequest) => Filters,
) {
  return async (req: ExportRequest, res: ExportResponse, next: ExportNext): Promise<void> => {
    try {
      const filters = parseFilters(req);
      const count = await countFn(filters);
      const parts = count === 0 ? 0 : Math.ceil(count / PART_SIZE);
      res.json({ count, parts, partSize: PART_SIZE });
    } catch (err) {
      next(err);
    }
  };
}

/**
 * Build an export handler that streams a single part as an XLSX download.
 *
 * The injected `sliceFn` decides where rows come from. Everything else (paging
 * math, headers, filename, streaming, sanitisation) is handled here.
 */
export function makeExportHandler(
  sliceFn: SliceFn,
  parseFilters: (req: ExportRequest) => Filters,
  baseFilename: string,
) {
  return async (req: ExportRequest, res: ExportResponse, next: ExportNext): Promise<void> => {
    try {
      const filters = parseFilters(req);
      const part = Math.max(1, toInt(req.query.part, 1));
      const parts = Math.max(1, toInt(req.query.parts, 1));
      const offset = (part - 1) * PART_SIZE;

      const rows = await sliceFn(filters, PART_SIZE, offset);

      const dateSuffix = buildDateSuffix(filters);
      const partSuffix = parts > 1 ? `_part${part}of${parts}` : "";
      const filename = `${baseFilename}${dateSuffix}${partSuffix}.xlsx`;

      res.setHeader(
        "Content-Type",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      );
      res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);

      await writeRowsToXlsxStream(rows, res);
    } catch (err) {
      next(err);
    }
  };
}
