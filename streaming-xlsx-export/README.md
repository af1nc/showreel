[← Showreel](..)

# 📤 Streaming XLSX Export

![Formats & protocols](https://img.shields.io/badge/Formats_%26_protocols-f59e0b) ![TypeScript](https://img.shields.io/badge/TypeScript-3178c6?logo=typescript&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

A small TypeScript toolkit for exporting large tabular datasets to Excel without
running out of memory, without leaking spreadsheet formula-injection payloads,
and without being tied to any one data source.

It streams rows straight into a Writable (an HTTP response or a file), splits
oversized exports into fixed-size part files, and hardens every cell against
formula injection. The row source is injected, so the same code serves a SQL
warehouse, an in-memory list, or a REST paginator.

## The interesting part

Three things most hand-rolled "export to Excel" endpoints get wrong:

1. **Streaming to avoid OOM on huge exports.** The writer uses ExcelJS's
   `stream.xlsx.WorkbookWriter` with `useSharedStrings: false` and
   `useStyles: false`, committing rows one at a time. The full workbook is never
   materialised in memory, so a result with millions of rows costs roughly the
   same memory as one with a thousand. On top of that, exports are chunked into
   50,000-row parts: a `count` endpoint reports how many parts a download needs,
   and an `export` endpoint streams a single part, so no request, file, or buffer
   grows without bound. The writer accepts a plain array or a generator, so rows
   can be produced lazily and garbage-collected as they are written.

2. **The injected slice / count design.** `makeCountHandler(countFn, ...)` and
   `makeExportHandler(sliceFn, ...)` are higher-order factories. They own all of
   the paging math, headers, filenames, streaming, and sanitisation. You inject
   two functions: one that returns a total count, one that returns up to `limit`
   rows from an `offset`. Point them at any backend and the same machinery works.
   The handlers use minimal structural request/response types, so they mount
   directly on Express (see `src/server.ts`) without the core depending on it.

3. **The spreadsheet formula-injection guard most exports forget.** A cell whose
   text begins with `=`, `+`, `-`, `@`, TAB, or CR is treated as a formula by
   Excel and Google Sheets, including dangerous DDE payloads like
   `=cmd|' /C calc'!A0` that can run the moment the file is opened. The guard
   prefixes such strings with a tab so they render as inert text. Numbers, dates,
   and booleans pass through untouched. It lives in `src/csvSanitize.ts` as a
   pure, unit-testable function.

There is also a small helper, `flattenWarehouseDate`, that unwraps the
`{ value: 'YYYY-MM-DD' }` date objects some analytics warehouses return, so those
columns render as plain scalars.

## Run it

```bash
npm install
npm run demo
```

The demo fabricates 120,000 synthetic rows through a generator and streams them
to `./output/report_part1.xlsx` ... `report_part3.xlsx` in 50,000-row parts. It
prints process memory before and after each part so you can watch it stay flat
instead of growing with the row count, and it loads one row whose `note` cell
starts with `=` to prove the injection guard neutralises it (the guarded value
gains a leading `\t`).

Type-check everything:

```bash
npm run check
```

Optional Express example (documented, not needed for the demo):

```bash
npm run server
# GET http://localhost:3000/report/export-count
# GET http://localhost:3000/report/export-xlsx?part=1&parts=1
```

## Files

| File | Purpose |
| --- | --- |
| `src/csvSanitize.ts` | Pure formula-injection guard for spreadsheet cells. |
| `src/xlsxExport.ts` | Streaming writer, `flattenWarehouseDate`, and the `makeCount` / `makeExport` handler factories. |
| `src/demo.ts` | Generates a synthetic 120,000-row dataset and streams it to `./output` in parts, reporting memory. |
| `src/server.ts` | Optional Express wiring example. |

## What was stubbed

In a real deployment the injected `sliceFn` runs a paginated warehouse query
(`... LIMIT @limit OFFSET @offset`) and `countFn` runs a `COUNT(*)`. Here they
are replaced by a deterministic synthetic row generator (`generateRowWindow` in
`src/demo.ts`) and a tiny in-memory list (`src/server.ts`), so the project runs
with no database and no cloud. Everything else, the streaming writer, the paging
and part logic, and the sanitiser, is the real implementation.

---

MIT · Part of [Showreel](..), twelve standalone engineering projects.
