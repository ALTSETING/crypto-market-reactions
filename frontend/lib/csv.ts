import { SOURCE_TYPE_LABELS, type EventListItem } from "@/types/events";

export const CSV_MAX_ROWS = 50;

const CSV_COLUMNS = [
  "event_id",
  "slug",
  "title",
  "published_at",
  "source",
  "source_type",
  "primary_asset",
  "related_assets",
  "category",
  "sentiment",
  "importance",
  "btc_1h",
  "btc_24h",
  "eth_1h",
  "eth_24h",
  "sol_1h",
  "sol_24h",
] as const;

type CsvColumn = (typeof CSV_COLUMNS)[number];

function csvValue(event: EventListItem, column: CsvColumn): unknown {
  if (column === "related_assets") return event.related_assets.join("|");
  if (column === "source_type") return SOURCE_TYPE_LABELS[event.source_type];
  return event[column];
}

function escapeCsvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  let text = String(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

export function serializeCurrentPageCsv(items: EventListItem[]): string {
  const rows = items.slice(0, CSV_MAX_ROWS).map((event) =>
    CSV_COLUMNS.map((column) => escapeCsvCell(csvValue(event, column))).join(","),
  );
  return [CSV_COLUMNS.join(","), ...rows].join("\r\n") + "\r\n";
}
