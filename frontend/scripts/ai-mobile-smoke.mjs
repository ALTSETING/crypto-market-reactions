import { spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const port = 9444;
const baseUrl = (process.env.SMOKE_BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const screenshotDir = resolve(process.env.SMOKE_SCREENSHOT_DIR ?? "../reports/ui-redesign-v3");
const profile = await mkdtemp(join(tmpdir(), "cmr-ai-mobile-"));
const browser = spawn(chrome, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, `${baseUrl}/ai`,
], { stdio: "ignore", windowsHide: true });
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function target() {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = targets.find((item) => item.type === "page");
      if (page) return page;
    } catch {}
    await delay(200);
  }
  throw new Error("Chrome DevTools target was unavailable.");
}

class CdpClient {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
    this.errors = [];
    this.socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (!message.id) {
        if (message.method === "Log.entryAdded" && message.params?.entry?.level === "error") this.errors.push(message.params.entry.text);
        if (message.method === "Runtime.exceptionThrown") this.errors.push(message.params?.exceptionDetails?.text ?? "Runtime exception");
        const listener = this.listeners.get(message.method);
        if (listener) Promise.resolve(listener(message.params)).catch((error) => this.errors.push(String(error)));
        return;
      }
      const handler = this.pending.get(message.id);
      if (!handler) return;
      this.pending.delete(message.id);
      if (message.error) handler.reject(new Error(message.error.message));
      else handler.resolve(message.result);
    };
  }
  async ready() {
    if (this.socket.readyState === WebSocket.OPEN) return;
    await new Promise((resolve, reject) => { this.socket.onopen = resolve; this.socket.onerror = reject; });
  }
  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
  on(method, listener) { this.listeners.set(method, listener); }
  close() { this.socket.close(); }
}

async function evaluate(cdp, expression) {
  const response = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
  return response.result.value;
}

async function viewport(cdp, width) {
  await cdp.send("Emulation.setDeviceMetricsOverride", { width, height: width === 1440 ? 1000 : 844, deviceScaleFactor: 1, mobile: width < 600 });
  await delay(150);
  return evaluate(cdp, `(() => {
    const root = document.documentElement;
    const table = document.querySelector('[data-testid="historical-table-scroll"]');
    const nav = document.querySelector('nav[aria-label="Primary"]')?.getBoundingClientRect();
    const heading = document.querySelector('main h1')?.getBoundingClientRect();
    return {
      width: innerWidth,
      clientWidth: root.clientWidth,
      scrollWidth: root.scrollWidth,
      overflow: Math.max(0, root.scrollWidth - root.clientWidth),
      table: table ? { clientWidth: table.clientWidth, scrollWidth: table.scrollWidth, overflowX: getComputedStyle(table).overflowX } : null,
      navigationClear: Boolean(nav && heading && nav.bottom <= heading.top),
    };
  })()`);
}

async function screenshot(cdp, name) {
  await mkdir(screenshotDir, { recursive: true });
  await evaluate(cdp, `document.querySelectorAll('nextjs-portal').forEach((portal) => { portal.style.display = 'none'; })`);
  const result = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  await writeFile(join(screenshotDir, `${name}.png`), Buffer.from(result.data, "base64"));
}

async function reset(cdp, width, theme) {
  await cdp.send("Emulation.setDeviceMetricsOverride", { width, height: width === 1440 ? 1000 : 844, deviceScaleFactor: 1, mobile: width < 600 });
  await cdp.send("Page.navigate", { url: `${baseUrl}/ai` });
  await delay(1_000);
  await evaluate(cdp, `(() => {
    localStorage.setItem('site-theme', ${JSON.stringify(theme)});
    document.documentElement.dataset.theme = ${JSON.stringify(theme)};
    document.documentElement.style.colorScheme = ${JSON.stringify(theme)};
  })()`);
  await delay(150);
}

async function submit(cdp, question) {
  await evaluate(cdp, `(() => {
    const input = document.querySelector('#ai-search-question');
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    setter.call(input, ${JSON.stringify(question)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await delay(250);
  const submitted = await evaluate(cdp, `(() => {
    const button = document.querySelector('button[type="submit"]');
    if (!button || button.disabled) return false;
    button.click();
    return true;
  })()`);
  if (!submitted) throw new Error("AI submit button remained disabled.");
  await delay(100);
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const ready = await evaluate(cdp, `document.body.innerText.includes(${JSON.stringify(question)}) && !document.body.innerText.includes('Analyzing…') && (Boolean(document.querySelector('[aria-label="AI explanation"]')) || Boolean(document.querySelector('[aria-label="Historical evidence"]')) || document.body.innerText.includes('Request not supported') || document.body.innerText.includes('unavailable'))`);
    if (ready) return;
    await delay(100);
  }
  throw new Error("AI answer did not finish within the smoke window.");
}

function expandedSourcesResponse() {
  const citations = Array.from({ length: 21 }, (_, index) => ({
    eventId: `visual-source-${index + 1}`,
    href: `/events/visual-source-${index + 1}`,
    title: "Institutional Ethereum purchase and market reaction archive source",
    ...(index === 0 ? { groupSize: 3 } : {}),
  }));
  const rows = ["1m", "5m", "15m", "1h", "4h", "24h"].map((horizon, index) => ({
    horizon,
    mean: index < 2 ? null : 0.22 + index * 0.17,
    median: index < 2 ? null : 0.12 + index * 0.14,
    positivePercent: index < 2 ? null : 54 + index * 4,
    sampleSize: index < 2 ? 0 : 23,
    standardDeviation: null,
    standardError: null,
    trimmedMean5Percent: null,
    positive95Ci: null,
  }));
  const intent = {
    intent: "aggregate", asset: "ETH", dateFrom: null, dateTo: null, category: null,
    topic: "institutional_purchase", actorType: "institution", action: "buy", direction: "inflow",
    magnitude: "large", amount: null, entity: null, assetRole: "primary", sourceClass: null,
    sentiment: null, reactionSign: null, importance: null, horizon: null, metric: "mean",
    sort: "newest", groupBy: "none", comparison: null, limit: 10,
  };
  return {
    status: "ok", mode: "agent", modeLabel: "AI explanation", language: "en",
    answer: "Institutional purchases can add demand and affect liquidity. The historical archive below provides context without implying causality.",
    historical: {
      basedOn: "Reaction V2", operation: "overview", intent,
      answer: "Historical reaction across all horizons.", calculation: "",
      result: { kind: "multi_horizon", rows, citations }, citations,
    },
    historicalUnavailable: false, historicalMessage: null, citations,
    disclaimer: "Educational answer — not financial advice.",
  };
}

let cdp;
try {
  const page = await target();
  cdp = new CdpClient(page.webSocketDebuggerUrl);
  await cdp.ready();
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await cdp.send("Page.reload");
  await delay(2_000);

  const states = {};
  await reset(cdp, 390, "light");
  states.emptyMobile = await viewport(cdp, 390);
  await screenshot(cdp, "ai-390-empty");
  states.examplesCollapsed = await evaluate(cdp, `(() => {
    const toggle = document.querySelector('[aria-controls="ai-example-questions"]');
    const buttons = [...document.querySelectorAll('#ai-example-questions button')];
    return { expanded: toggle?.getAttribute('aria-expanded'), hidden: document.querySelector('#ai-example-questions')?.getAttribute('aria-hidden'), tabbable: buttons.filter((button) => button.tabIndex === 0).length };
  })()`);
  await screenshot(cdp, "ai-390-examples-collapsed");
  await evaluate(cdp, `document.querySelector('[aria-controls="ai-example-questions"]')?.click()`);
  await delay(250);
  states.examplesExpanded = await evaluate(cdp, `(() => {
    const toggle = document.querySelector('[aria-controls="ai-example-questions"]');
    const buttons = [...document.querySelectorAll('#ai-example-questions button')];
    return { expanded: toggle?.getAttribute('aria-expanded'), hidden: document.querySelector('#ai-example-questions')?.getAttribute('aria-hidden'), tabbable: buttons.filter((button) => button.tabIndex === 0).length };
  })()`);
  await screenshot(cdp, "ai-390-examples-expanded");
  await evaluate(cdp, `document.querySelector('#ai-example-questions button')?.click()`);
  await delay(100);
  states.exampleSelection = await evaluate(cdp, `({ value: document.querySelector('#ai-search-question')?.value, answerVisible: Boolean(document.querySelector('[aria-label="AI explanation"]')) })`);
  await reset(cdp, 1440, "dark");
  states.emptyDesktop = await viewport(cdp, 1440);
  await screenshot(cdp, "ai-1440-empty");

  await reset(cdp, 390, "dark");
  await submit(cdp, "How did SOL react historically?");
  await viewport(cdp, 390);
  await screenshot(cdp, "ai-390-historical");
  for (const width of [320, 360, 375, 390, 430, 768, 1024, 1440]) states[width] = await viewport(cdp, width);
  await viewport(cdp, 1440);
  await screenshot(cdp, "ai-1440-historical");

  await reset(cdp, 390, "light");
  await submit(cdp, "What is a Bitcoin ETF?");
  states.general = await viewport(cdp, 390);
  await screenshot(cdp, "ai-390-general");
  await submit(cdp, "На які новини ETH найчастіше реагував зростанням за 24h?");
  states.topicRanking = await viewport(cdp, 390);
  await submit(cdp, "ETF approvals or institutional purchases — which had a stronger ETH 24h reaction?");
  states.comparison = await viewport(cdp, 390);
  await reset(cdp, 390, "dark");
  await submit(cdp, "Як ETH реагував на надзвичайно довгу назву інституційної купівлі з поясненням ліквідності та ринкового впливу через 24 години?");
  states.longUkrainian = await viewport(cdp, 390);
  await screenshot(cdp, "ai-390-long-uk");

  await cdp.send("Fetch.enable", { patterns: [{ urlPattern: "*api/ai-search", requestStage: "Request" }] });
  const expandedResponse = expandedSourcesResponse();
  cdp.on("Fetch.requestPaused", async ({ requestId }) => {
    await cdp.send("Fetch.fulfillRequest", {
      requestId,
      responseCode: 200,
      responseHeaders: [{ name: "Content-Type", value: "application/json" }],
      body: Buffer.from(JSON.stringify(expandedResponse)).toString("base64"),
    });
  });
  await reset(cdp, 390, "dark");
  await submit(cdp, "How does ETH react to large institutional purchases?");
  states.sourcesCollapsed = await evaluate(cdp, `({ visible: document.querySelectorAll('[aria-labelledby="sources-heading"] li').length, moreLabel: [...document.querySelectorAll('button')].find((button) => button.textContent.includes('more'))?.textContent.trim() })`);
  await evaluate(cdp, `([...document.querySelectorAll('button')].find((button) => button.textContent.includes('more'))?.click(), true)`);
  await delay(200);
  states.sourcesExpanded = await evaluate(cdp, `({ visible: document.querySelectorAll('[aria-labelledby="sources-heading"] li').length, lessVisible: [...document.querySelectorAll('button')].some((button) => button.textContent.trim() === 'Show less') })`);
  await screenshot(cdp, "ai-390-sources-expanded");

  const failures = Object.entries(states).filter(([, state]) => typeof state.overflow === "number" && (state.overflow !== 0 || !state.navigationClear));
  const tableStates = [320, 360, 375, 390, 430].map((width) => states[width].table);
  if (tableStates.some((table) => !table || table.overflowX !== "auto" || table.scrollWidth < table.clientWidth)) {
    throw new Error("Historical table is not isolated in its horizontal scroll wrapper.");
  }
  if (states.examplesCollapsed.expanded !== "false" || states.examplesCollapsed.hidden !== "true" || states.examplesCollapsed.tabbable !== 0) throw new Error("Examples are not accessibly collapsed by default.");
  if (states.examplesExpanded.expanded !== "true" || states.examplesExpanded.hidden !== "false" || states.examplesExpanded.tabbable !== 5) throw new Error(`Examples did not expand accessibly: ${JSON.stringify(states.examplesExpanded)}`);
  if (states.exampleSelection.value !== "What is a Bitcoin ETF?" || states.exampleSelection.answerVisible) throw new Error("Example selection did not fill the prompt without submitting.");
  if (states.sourcesCollapsed.visible !== 5 || states.sourcesCollapsed.moreLabel !== "Show 16 more" || states.sourcesExpanded.visible !== 21 || !states.sourcesExpanded.lessVisible) throw new Error("Citation progressive disclosure failed.");
  if (failures.length > 0) throw new Error(`Mobile layout failures: ${JSON.stringify(failures)}`);
  const criticalErrors = cdp.errors.filter((message) => !/favicon\.ico|Failed to load resource.*404/iu.test(message));
  if (criticalErrors.length > 0) throw new Error(`Critical browser errors: ${JSON.stringify(criticalErrors)}`);
  console.log(JSON.stringify({ states, screenshots: screenshotDir, criticalConsoleErrors: criticalErrors.length }, null, 2));
} finally {
  cdp?.close();
  browser.kill();
}
