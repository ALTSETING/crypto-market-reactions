const baseUrl = (process.env.SMOKE_BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const expectedSiteUrl = (process.env.SITE_URL ?? baseUrl).replace(/\/$/, "");
let expectedEventCount = Number(process.env.EXPECTED_EVENT_COUNT ?? "");
const googlebot = {
  headers: {
    "User-Agent":
      "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
  },
};

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function matches(html, pattern, label) {
  assert(pattern.test(html), `Missing ${label}`);
}

async function read(url) {
  const response = await fetch(url, googlebot);
  return { response, body: await response.text() };
}

function decodeXml(value) {
  return value
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&apos;", "'");
}

function decodeHtml(value) {
  return decodeXml(value)
    .replaceAll("&nbsp;", " ")
    .replace(/&#x([0-9a-f]+);/gi, (_, code) => String.fromCodePoint(Number.parseInt(code, 16)))
    .replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code)))
    .replace(/<[^>]+>/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function seededSample(values, count) {
  let state = 0x5e0c2026;
  const selected = new Set();
  while (selected.size < Math.min(count, values.length)) {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    selected.add(state % values.length);
  }
  return [...selected].map((index) => values[index]);
}

const sitemapResponse = await read(`${baseUrl}/sitemap.xml`);
if (!Number.isInteger(expectedEventCount) || expectedEventCount <= 0) {
  const apiResponse = await fetch(`${baseUrl}/api/events?pageSize=1`);
  assert(apiResponse.status === 200, "Could not derive the event count from the public API");
  const apiPayload = await apiResponse.json();
  expectedEventCount = Number(apiPayload.total);
  assert(Number.isInteger(expectedEventCount) && expectedEventCount > 0, "API returned an invalid total");
}
assert(sitemapResponse.response.status === 200, "sitemap.xml did not return HTTP 200");
matches(sitemapResponse.body, /^<\?xml[^>]*>/, "XML declaration");
matches(sitemapResponse.body, /<urlset[^>]*xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9"/, "sitemap namespace");
const sitemapUrls = [...sitemapResponse.body.matchAll(/<loc>(.*?)<\/loc>/g)].map((match) =>
  decodeXml(match[1]),
);
const uniqueSitemapUrls = new Set(sitemapUrls);
const eventUrls = sitemapUrls.filter((url) => new URL(url).pathname.startsWith("/events/"));
const lastModifiedValues = [...sitemapResponse.body.matchAll(/<lastmod>(.*?)<\/lastmod>/g)].map(
  (match) => decodeXml(match[1]),
);
assert(eventUrls.length === expectedEventCount, `Expected ${expectedEventCount} event URLs, received ${eventUrls.length}`);
assert(uniqueSitemapUrls.size === sitemapUrls.length, "Sitemap contains duplicate URLs");
assert(sitemapUrls.length === expectedEventCount + 1, "Sitemap must contain only the homepage and event pages");
assert(lastModifiedValues.length === expectedEventCount, "Every event sitemap entry must have lastmod");
assert(lastModifiedValues.every((value) => !Number.isNaN(Date.parse(value))), "Sitemap contains an invalid lastmod date");
for (const url of sitemapUrls) {
  const parsed = new URL(url);
  assert(parsed.origin === expectedSiteUrl, `Unexpected sitemap origin: ${parsed.origin}`);
  assert(!parsed.search && !parsed.hash, `Sitemap URL contains search state: ${url}`);
  assert(parsed.pathname === "/" || /^\/events\/[a-z0-9]+(?:-+[a-z0-9]+)*$/.test(parsed.pathname), `Malformed sitemap URL: ${url}`);
}

const slugAuditUrls = seededSample(eventUrls, 100);
const slugAuditTitles = new Set();
for (let offset = 0; offset < slugAuditUrls.length; offset += 10) {
  await Promise.all(
    slugAuditUrls.slice(offset, offset + 10).map(async (canonical) => {
      const localUrl = `${baseUrl}${new URL(canonical).pathname}`;
      const response = await fetch(localUrl, { ...googlebot, redirect: "manual" });
      const body = await response.text();
      assert(response.status === 200, `${localUrl} returned HTTP ${response.status}`);
      assert(!response.headers.has("location"), `${localUrl} unexpectedly redirects`);
      const canonicalHref = body.match(/<link[^>]+rel="canonical"[^>]+href="([^"]+)"/)?.[1];
      assert(canonicalHref === canonical, `${localUrl} does not canonicalize to itself`);
      const pageTitle = decodeHtml(body.match(/<title>(.*?)<\/title>/)?.[1] ?? "");
      const heading = decodeHtml(body.match(/<h1[^>]*>(.*?)<\/h1>/s)?.[1] ?? "");
      const jsonLdText = body.match(/<script[^>]+type="application\/ld\+json"[^>]*>(.*?)<\/script>/s)?.[1];
      assert(heading.length > 0, `${localUrl} has no rendered event heading`);
      assert(pageTitle.length > 10, `${localUrl} has no useful metadata title`);
      assert(jsonLdText, `${localUrl} has no JSON-LD payload`);
      assert(
        decodeHtml(String(JSON.parse(jsonLdText).headline)) === heading,
        `${localUrl} structured data does not match its event heading`,
      );
      assert(!slugAuditTitles.has(pageTitle), `${localUrl} repeats a title in the 100-slug audit`);
      slugAuditTitles.add(pageTitle);
    }),
  );
}

const sampleUrls = slugAuditUrls.slice(0, 20);
const titles = new Set();
for (const canonical of sampleUrls) {
  const localUrl = `${baseUrl}${new URL(canonical).pathname}`;
  const { response, body } = await read(localUrl);
  assert(response.status === 200, `${localUrl} returned HTTP ${response.status}`);
  const title = body.match(/<title>(.*?)<\/title>/)?.[1];
  assert(title && title.length > 10, `${localUrl} has no useful title`);
  assert(!titles.has(title), `${localUrl} repeats a sampled title`);
  titles.add(title);
  matches(body, /<meta[^>]+name="description"[^>]+content="[^"]{100,}"/, `${localUrl} meta description`);
  matches(body, new RegExp(`<link[^>]+rel="canonical"[^>]+href="${canonical.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`), `${localUrl} canonical`);
  matches(body, /<meta[^>]+property="og:title"/, `${localUrl} og:title`);
  matches(body, /<meta[^>]+property="og:description"/, `${localUrl} og:description`);
  matches(body, /<meta[^>]+property="og:url"/, `${localUrl} og:url`);
  matches(body, /<meta[^>]+property="og:type"[^>]+content="article"/, `${localUrl} og:type`);
  matches(body, /<meta[^>]+property="og:site_name"/, `${localUrl} og:site_name`);
  matches(body, /<meta[^>]+name="twitter:card"[^>]+content="summary"/, `${localUrl} Twitter card`);
  matches(body, /<script[^>]+type="application\/ld\+json"/, `${localUrl} JSON-LD`);
  matches(body, /<h1[^>]*>.*?<\/h1>/s, `${localUrl} rendered event title`);
  matches(body, /Read original source/, `${localUrl} original source link`);
  matches(body, /Price reactions/, `${localUrl} reaction section`);
  assert(!/<meta[^>]+name="robots"[^>]+content="[^"]*noindex/i.test(body), `${localUrl} is unexpectedly noindex`);
}

const invalidSlugs = [
  "missing-event-one-2026-a1b2c3d4",
  "missing-event-two-2026-b2c3d4e5",
  "missing-event-three-2026-c3d4e5f6",
  "missing-event-four-2026-d4e5f6a7",
  "missing-event-five-2026-e5f6a7b8",
];
for (const slug of invalidSlugs) {
  const response = await fetch(`${baseUrl}/events/${slug}`, googlebot);
  assert(response.status === 404, `${slug} returned HTTP ${response.status}, expected 404`);
}

const queryPage = await read(`${baseUrl}/?asset=ETH&sort=growth`);
assert(queryPage.response.status === 200, "Filtered homepage did not return HTTP 200");
matches(queryPage.body, /<meta[^>]+name="robots"[^>]+content="[^"]*noindex/, "filtered homepage noindex");
matches(queryPage.body, new RegExp(`<link[^>]+rel="canonical"[^>]+href="${expectedSiteUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/?"`), "filtered homepage canonical");

const eventQueryCanonical = sampleUrls[0];
const eventQueryPage = await read(
  `${baseUrl}${new URL(eventQueryCanonical).pathname}?utm_source=seo-smoke`,
);
assert(eventQueryPage.response.status === 200, "Event URL with query parameters did not return HTTP 200");
matches(eventQueryPage.body, /<meta[^>]+name="robots"[^>]+content="[^"]*noindex/, "event query noindex");
matches(
  eventQueryPage.body,
  new RegExp(
    `<link[^>]+rel="canonical"[^>]+href="${eventQueryCanonical.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`,
  ),
  "event query canonical",
);

const robots = await read(`${baseUrl}/robots.txt`);
assert(robots.response.status === 200, "robots.txt did not return HTTP 200");
matches(robots.body, /Allow: \//, "robots allow rule");
matches(robots.body, /Disallow: \/api\//, "robots API disallow rule");
matches(robots.body, new RegExp(`Sitemap: ${expectedSiteUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/sitemap\.xml`), "robots sitemap URL");

console.log(
  JSON.stringify(
    {
      sitemap_total_urls: sitemapUrls.length,
      sitemap_event_urls: eventUrls.length,
      sampled_event_pages: sampleUrls.length,
      random_slug_identity_checks: slugAuditUrls.length,
      unique_random_slug_titles: slugAuditTitles.size,
      unique_sampled_titles: titles.size,
      invalid_slug_404s: invalidSlugs.length,
      filtered_homepage_noindex: true,
      event_query_noindex: true,
      robots_verified: true,
      canonical_origin: expectedSiteUrl,
    },
    null,
    2,
  ),
);
