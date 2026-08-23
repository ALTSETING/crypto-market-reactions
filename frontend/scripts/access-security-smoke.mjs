const baseUrl = (process.env.SMOKE_BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function json(path) {
  const response = await fetch(`${baseUrl}${path}`);
  const body = await response.json();
  return { response, body };
}

const defaultPage = await json("/api/events");
assert(defaultPage.response.status === 200, "Default search request failed");
assert(defaultPage.body.pageSize === 25, "Default page size is not 25");
assert(defaultPage.body.items.length <= 25, "Default search returned more than 25 rows");

for (const query of ["limit=1000", "limit=100000", "pageSize=999999"]) {
  const result = await json(`/api/events?${query}`);
  assert(result.response.status === 200, `${query} did not normalize safely`);
  assert(result.body.pageSize === 50, `${query} was not clamped to 50`);
  assert(result.body.items.length <= 50, `${query} returned more than 50 rows`);
  for (const item of result.body.items) {
    assert(!("source_url" in item), `${query} exposed event-detail source_url`);
    assert(!("reaction_methodology" in item), `${query} exposed methodology metadata`);
    assert(!("search_vector" in item), `${query} exposed internal search_vector`);
  }
}

const negativeOffset = await json("/api/events?offset=-1");
assert(negativeOffset.response.status === 200, "Unknown negative offset was not safely ignored");
assert(negativeOffset.body.page === 1, "Unknown offset changed pagination");
assert(negativeOffset.body.items.length <= 25, "Unknown offset bypassed the default limit");

for (const query of ["page=-1", "page=0", "page=invalid", "limit=-1"]) {
  const result = await json(`/api/events?${query}`);
  assert(result.response.status === 400, `${query} must return HTTP 400`);
}

const csvResponse = await fetch(`${baseUrl}/api/events/export?limit=100000`);
const csv = await csvResponse.text();
assert(csvResponse.status === 200, "CSV export failed");
assert(csvResponse.headers.get("content-type")?.startsWith("text/csv"), "CSV content type is missing");
const csvLines = csv.trimEnd().split("\r\n");
assert(csvLines.length <= 51, "CSV export returned more than 50 data rows");
assert(!csvLines[0].includes("source_url"), "CSV exposed source_url");
assert(!csvLines[0].includes("reaction_methodology"), "CSV exposed methodology metadata");

console.log(
  JSON.stringify(
    {
      default_page_size: defaultPage.body.pageSize,
      maximum_search_rows: 50,
      maximum_csv_rows: csvLines.length - 1,
      oversized_limits_clamped: 3,
      invalid_pagination_rejected: 4,
      negative_offset_safely_ignored: true,
      detail_fields_blocked_from_list: true,
    },
    null,
    2,
  ),
);
