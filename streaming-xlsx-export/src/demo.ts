/**
 * Runnable demo for the streaming XLSX exporter.
 *
 * It fabricates a large synthetic dataset (120,000 rows) via a generator, then
 * streams it to `./output/report_partN.xlsx` in 50,000-row parts. Memory usage
 * is printed before and after so you can see it stays flat instead of ballooning
 * with the row count.
 *
 * The generator here stands in for a real "warehouse slice" function. In
 * production `makeExportHandler` would call a paginated query; here it is a
 * deterministic row generator so the demo needs no database and no cloud.
 */

import { createWriteStream, mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";
import {
  PART_SIZE,
  Row,
  writeRowsToXlsxStream,
} from "./xlsxExport";
import { sanitizeCellValue } from "./csvSanitize";

/** Total synthetic rows. Big enough that streaming genuinely matters. */
const TOTAL_ROWS = 120_000;

/** Fixed column order for the report. */
const COLUMNS = [
  "report_date",
  "region",
  "channel",
  "campaign",
  "impressions",
  "clicks",
  "spend",
  "conversions",
  "note",
] as const;

/**
 * A classic formula-injection payload. Loaded as plain data into one row to
 * prove the guard neutralises it: the writer will store it as text, not as an
 * executable DDE formula.
 */
const INJECTION_PAYLOAD = `=2+5+cmd|' /C calc'!A0`;

const REGIONS = ["North", "South", "East", "West", "Central"];
const CHANNELS = ["Search", "Social", "Display", "Video", "Native"];

/**
 * Lazily yield the rows for a single window `[offset, offset + limit)`.
 *
 * Rows are produced one at a time and never accumulated, mirroring how a real
 * paginated slice would stream from a warehouse. One row (index 42) carries the
 * injection payload so every generated part-1 file exercises the guard.
 */
function* generateRowWindow(offset: number, limit: number): Generator<Row> {
  const dayMs = 24 * 60 * 60 * 1000;
  const epoch = Date.UTC(2024, 0, 1);

  for (let i = offset; i < offset + limit; i += 1) {
    // Spread rows across a plausible date range and wrap the date the way an
    // analytics warehouse often does: { value: 'YYYY-MM-DD' }.
    const iso = new Date(epoch + (i % 365) * dayMs).toISOString().slice(0, 10);
    const impressions = 1_000 + ((i * 37) % 90_000);
    const clicks = 10 + ((i * 7) % 900);
    const conversions = (i * 3) % 120;
    const spend = Number((clicks * 1.37).toFixed(2));

    yield {
      report_date: { value: iso },
      region: REGIONS[i % REGIONS.length],
      channel: CHANNELS[i % CHANNELS.length],
      campaign: `campaign_${(i % 500).toString().padStart(4, "0")}`,
      impressions,
      clicks,
      spend,
      conversions,
      note: i === 42 ? INJECTION_PAYLOAD : "ok",
    };
  }
}

/** Format a byte count as megabytes with one decimal place. */
function mb(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Print a labelled snapshot of current process memory. */
function reportMemory(label: string): void {
  const usage = process.memoryUsage();
  console.log(`  ${label.padEnd(22)} rss=${mb(usage.rss)}  heapUsed=${mb(usage.heapUsed)}`);
}

/** Await a write stream reaching completion (or failing). */
function streamFinished(stream: NodeJS.WritableStream): Promise<void> {
  return new Promise((resolve, reject) => {
    stream.once("finish", () => resolve());
    stream.once("error", reject);
  });
}

async function main(): Promise<void> {
  const here = dirname(fileURLToPath(import.meta.url));
  const outDir = join(here, "..", "output");
  mkdirSync(outDir, { recursive: true });

  const parts = Math.ceil(TOTAL_ROWS / PART_SIZE);

  console.log("Streaming XLSX export demo");
  console.log(`  rows        : ${TOTAL_ROWS.toLocaleString()}`);
  console.log(`  part size   : ${PART_SIZE.toLocaleString()}`);
  console.log(`  parts       : ${parts}`);
  console.log("");

  // Prove the injection guard before writing anything. The guarded value shows
  // a leading \t, which forces spreadsheets to render it as text.
  console.log("Formula-injection guard:");
  console.log(`  raw     : ${JSON.stringify(INJECTION_PAYLOAD)}`);
  console.log(`  guarded : ${JSON.stringify(sanitizeCellValue(INJECTION_PAYLOAD))}`);
  console.log("");

  console.log("Memory:");
  reportMemory("before export");

  let totalWritten = 0;

  for (let part = 1; part <= parts; part += 1) {
    const offset = (part - 1) * PART_SIZE;
    const limit = Math.min(PART_SIZE, TOTAL_ROWS - offset);
    const filePath = join(outDir, `report_part${part}.xlsx`);

    const fileStream = createWriteStream(filePath);
    const finished = streamFinished(fileStream);

    const written = await writeRowsToXlsxStream(
      generateRowWindow(offset, limit),
      fileStream,
      { columns: [...COLUMNS], sheetName: "Report" },
    );
    await finished;

    totalWritten += written;
    reportMemory(`after part ${part}`);
  }

  reportMemory("after export");
  console.log("");
  console.log(`Wrote ${totalWritten.toLocaleString()} rows across ${parts} file(s) to ./output`);
  console.log("Row 43 (index 42) carries the neutralised formula payload in its 'note' cell.");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
