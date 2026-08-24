import { spawn } from "node:child_process";
import { resolve } from "node:path";


const chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const port = 9334;
const baseUrl = (process.env.SMOKE_BASE_URL ?? "http://localhost:3100").replace(/\/$/, "");
const profile = resolve(process.env.TEMP ?? ".", `cmrd-dz14-smoke-${process.pid}`);
const browser = spawn(
  chrome,
  [
    "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, `${baseUrl}/?page=7`,
  ],
  { stdio: "ignore", windowsHide: true },
);

const delay = (milliseconds) => new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));

async function target() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      const targets = await response.json();
      const page = targets.find((item) => item.type === "page");
      if (page) return page;
    } catch {}
    await delay(250);
  }
  throw new Error("Chrome DevTools target did not become available.");
}

class CdpClient {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.nextId = 1;
    this.pending = new Map();
    this.socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (!message.id) return;
      const handler = this.pending.get(message.id);
      if (!handler) return;
      this.pending.delete(message.id);
      if (message.error) handler.reject(new Error(message.error.message));
      else handler.resolve(message.result);
    };
  }

  async ready() {
    if (this.socket.readyState === WebSocket.OPEN) return;
    await new Promise((resolveOpen, rejectOpen) => {
      this.socket.onopen = resolveOpen;
      this.socket.onerror = rejectOpen;
    });
  }

  send(method, params = {}) {
    const id = this.nextId;
    this.nextId += 1;
    return new Promise((resolveMessage, rejectMessage) => {
      this.pending.set(id, { resolve: resolveMessage, reject: rejectMessage });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    this.socket.close();
  }
}

async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(
      result.exceptionDetails.exception?.description ?? result.exceptionDetails.text,
    );
  }
  return result.result.value;
}

let cdp;
try {
  const page = await target();
  cdp = new CdpClient(page.webSocketDebuggerUrl);
  await cdp.ready();
  await cdp.send("Page.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 390, height: 844, deviceScaleFactor: 1, mobile: true,
  });
  await cdp.send("Page.reload");
  await delay(3_000);
  const initial = await evaluate(cdp, `({
    url: location.href,
    result: [...document.querySelectorAll('h2')].find((node) => node.textContent.includes('results'))?.textContent.trim(),
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth,
    labels: [...document.querySelectorAll('button')].map((button) => button.textContent.trim())
  })`);
  await evaluate(cdp, `document.querySelector('[aria-controls="event-filters"]')?.click()`);
  await delay(200);
  const filterLabels = await evaluate(cdp, `[...document.querySelectorAll('button')].map((button) => button.textContent.trim())`);
  await evaluate(cdp, `([...document.querySelectorAll('button')].find((button) => button.textContent.trim() === 'Primary document')?.click(), true)`);
  await delay(1_500);
  const sourceFiltered = await evaluate(cdp, `({
    url: location.href,
    result: [...document.querySelectorAll('h2')].find((node) => node.textContent.includes('results'))?.textContent.trim(),
    badges: [...document.querySelectorAll('[data-source-type]')].map((node) => node.textContent.trim())
  })`);

  let advancedFiltersVisible = false;
  for (let attempt = 0; attempt < 12; attempt += 1) {
    advancedFiltersVisible = await evaluate(
      cdp,
      `Boolean(document.querySelector('select[name="category"]'))`,
    );
    if (advancedFiltersVisible) break;
    await evaluate(cdp, `(() => {
      const toggle = document.querySelector('[aria-controls="event-filters"]');
      if (toggle?.getAttribute('aria-expanded') === 'false') toggle.click();
    })()`);
    await delay(250);
  }
  if (!advancedFiltersVisible) {
    const diagnostics = await evaluate(cdp, `({
      url: location.href,
      title: document.title,
      body: document.body.innerText.slice(0, 500),
      toggles: [...document.querySelectorAll('[aria-controls]')].map((node) => ({
        controls: node.getAttribute('aria-controls'),
        expanded: node.getAttribute('aria-expanded'),
        text: node.textContent.trim()
      }))
    })`);
    throw new Error(`Advanced filters did not open: ${JSON.stringify(diagnostics)}`);
  }

  await evaluate(cdp, `(() => {
    for (const [name, value] of [['category', 'regulation'], ['year', '2024']]) {
      const select = document.querySelector('select[name="' + name + '"]');
      if (!select) throw new Error('Missing advanced filter: ' + name);
      select.value = value;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }
    [...document.querySelectorAll('button')].find((button) => button.textContent.trim() === 'Apply')?.click();
  })()`);
  await delay(1_500);
  const combinedUrl = await evaluate(cdp, "location.href");
  const csv = await evaluate(cdp, `fetch('/api/events/export?sourceType=primary_document&pageSize=1000').then(async (response) => ({ status: response.status, text: await response.text() }))`);
  const invalid = await evaluate(cdp, `fetch('/api/events?sourceType=publisher%27%29%20OR%20true--').then(async (response) => ({ status: response.status, body: await response.json() }))`);
  const nextAvailable = await evaluate(cdp, `Boolean([...document.querySelectorAll('button')].find((button) => button.textContent.includes('Next') && !button.disabled))`);
  await evaluate(cdp, `([...document.querySelectorAll('button')].find((button) => button.textContent.includes('Next') && !button.disabled)?.click(), true)`);
  await delay(1_000);
  const pageTwoUrl = await evaluate(cdp, "location.href");

  const eventHref = await evaluate(cdp, `document.querySelector('a[href^="/events/"]')?.getAttribute('href')`);
  await cdp.send("Page.navigate", { url: new URL(eventHref, baseUrl).toString() });
  await delay(1_500);
  const detail = await evaluate(cdp, `({
    url: location.href,
    text: document.body.innerText,
    sourceBadge: document.querySelector('[data-source-type]')?.textContent.trim(),
    reactionTooltip: document.querySelector('[aria-label^="Reaction V2"]')?.getAttribute('aria-label'),
    canonical: document.querySelector('link[rel="canonical"]')?.href,
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth
  })`);
  const seo = await evaluate(cdp, `Promise.all([
    fetch('/sitemap.xml').then(async (response) => ({ status: response.status, text: await response.text() })),
    fetch('/events/bad').then(async (response) => ({ status: response.status, text: await response.text() }))
  ]).then(([sitemap, invalid]) => ({ sitemap, invalid }))`);
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false,
  });
  await cdp.send("Page.reload");
  await delay(1_000);
  const desktop = await evaluate(cdp, `({ scrollWidth: document.documentElement.scrollWidth, innerWidth })`);

  const csvLines = csv.text.trimEnd().split("\r\n");
  const checks = {
    mobile_no_horizontal_scroll: initial.scrollWidth <= initial.innerWidth,
    source_options_visible: ["All sources", "News media", "Primary document", "Official announcement"].every((label) => filterLabels.includes(label)),
    source_filter_url_and_page_reset: sourceFiltered.url.includes("sourceType=primary_document") && !sourceFiltered.url.includes("page=7"),
    dynamic_source_total: sourceFiltered.result === "736 results",
    friendly_card_badge: sourceFiltered.badges.includes("Primary document") && !sourceFiltered.badges.includes("primary_document"),
    combination_state_in_url: combinedUrl.includes("sourceType=primary_document") && combinedUrl.includes("category=regulation") && combinedUrl.includes("year=2024"),
    pagination_works: nextAvailable && pageTwoUrl.includes("page=2"),
    csv_bounded_and_filtered: csv.status === 200 && csvLines.length <= 51 && csv.text.includes("Primary document"),
    invalid_source_controlled: invalid.status === 400 && invalid.body.code === "INVALID_QUERY",
    detail_mobile_no_horizontal_scroll: detail.scrollWidth <= detail.innerWidth,
    detail_badge_and_reaction_v2: detail.sourceBadge === "Primary document" && detail.text.includes("Reaction V2") && detail.reactionTooltip?.includes("does not prove"),
    seo_canonical: detail.canonical === detail.url,
    sitemap_event_pages: seo.sitemap.status === 200 && seo.sitemap.text.includes("dz14-stub-event-1-b1c2d3e4"),
    invalid_event_404_noindex: seo.invalid.status === 404 && seo.invalid.text.includes("noindex"),
    no_snake_case_visible: !detail.text.includes("primary_document"),
    desktop_no_horizontal_scroll: desktop.scrollWidth <= desktop.innerWidth,
  };
  if (Object.values(checks).some((value) => !value)) {
    throw new Error(JSON.stringify({ checks, initial, sourceFiltered, combinedUrl, pageTwoUrl, detail, desktop }));
  }
  console.log(JSON.stringify({ status: "PASS", checks }, null, 2));
} finally {
  cdp?.close();
  browser.kill();
}
