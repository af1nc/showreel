/**
 * Optional Express example: wiring the count and export endpoints.
 *
 * This is documentation-by-code. It shows how `makeCountHandler` and
 * `makeExportHandler` mount on a real HTTP server. It is NOT needed to run the
 * demo (`npm run demo` writes files directly).
 *
 * The injected `sliceFn` / `countFn` here read from a small in-memory list.
 * Swap them for a paginated warehouse query and nothing else changes.
 *
 * Run it (after `npm install`):  npm run server
 * Then:
 *   GET /report/export-count                       -> { count, parts, partSize }
 *   GET /report/export-xlsx?part=1&parts=1          -> streams an .xlsx download
 */

import express from "express";
import {
  Filters,
  Row,
  makeCountHandler,
  makeExportHandler,
} from "./xlsxExport";

/** Port for the example server. */
const PORT = 3000;

/** Stand-in dataset. In production this is a warehouse table. */
const DATASET: Row[] = Array.from({ length: 275 }, (_, i) => ({
  report_date: { value: "2024-01-01" },
  region: ["North", "South", "East"][i % 3],
  channel: ["Search", "Social", "Display"][i % 3],
  campaign: `campaign_${(i % 50).toString().padStart(4, "0")}`,
  impressions: 1_000 + i * 11,
  clicks: 10 + (i % 90),
  spend: Number(((10 + (i % 90)) * 1.37).toFixed(2)),
  conversions: i % 20,
  note: i === 3 ? "=HYPERLINK(0)" : "ok",
}));

/**
 * Injected filter parser. Pull whatever selection your UI sends (dates, market,
 * channel, etc.) off the query string. Kept trivial here.
 */
function parseFilters(req: { query: Record<string, unknown> }): Filters {
  return {
    startDate: req.query.startDate,
    endDate: req.query.endDate,
  };
}

/** Injected counter: total rows for these filters. */
async function countFn(_filters: Filters): Promise<number> {
  return DATASET.length;
}

/** Injected slice: return up to `limit` rows starting at `offset`. */
async function sliceFn(_filters: Filters, limit: number, offset: number): Promise<Row[]> {
  return DATASET.slice(offset, offset + limit);
}

const app = express();

app.get("/report/export-count", makeCountHandler(countFn, parseFilters));
app.get("/report/export-xlsx", makeExportHandler(sliceFn, parseFilters, "report"));

app.listen(PORT, () => {
  console.log(`Example export server listening on http://localhost:${PORT}`);
  console.log("  GET /report/export-count");
  console.log("  GET /report/export-xlsx?part=1&parts=1");
});
