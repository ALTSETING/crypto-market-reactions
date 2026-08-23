import { spawn } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const port = 9333;
const initialUrl =
  "http://localhost:3000/?asset=ETH&sort=growth&horizon=average&marketDataOnly=true";
const profile = resolve(process.env.TEMP ?? ".", `cmrd-browser-smoke-${process.pid}`);
const reports = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "reports");
const browser = spawn(
  chrome,
  [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    initialUrl,
  ],
  { stdio: "ignore", windowsHide: true },
);

const delay = (milliseconds) => new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));

async function target() {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      const targets = await response.json();
      const page = targets.find((item) => item.type === "page");
      if (page) return page;
    } catch {}
    await delay(200);
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
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}

async function pageState(cdp) {
  return evaluate(
    cdp,
    `(() => ({
      url: location.href,
      innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      result: [...document.querySelectorAll('h2')].find((node) => node.textContent.includes('results'))?.textContent.trim(),
      metric: [...document.querySelectorAll('[aria-label]')].find((node) => /^(Average ETH reaction|ETH after)/.test(node.getAttribute('aria-label') ?? ''))?.getAttribute('aria-label'),
      error: document.body.innerText.includes('Events could not be loaded')
    }))()`,
  );
}

async function screenshot(cdp, name) {
  const image = await cdp.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
    fromSurface: true,
  });
  const path = resolve(reports, name);
  await writeFile(path, Buffer.from(image.data, "base64"));
  return path;
}

let cdp;
try {
  const page = await target();
  cdp = new CdpClient(page.webSocketDebuggerUrl);
  await cdp.ready();
  await cdp.send("Page.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await cdp.send("Page.reload");
  await delay(3500);
  const mobile = await pageState(cdp);
  const mobileScreenshot = await screenshot(cdp, "homework6-mobile.png");

  await evaluate(
    cdp,
    `([...document.querySelectorAll('button')].find((button) => button.textContent.trim() === 'Top losers')?.click(), true)`,
  );
  await delay(1800);
  const quickAction = await pageState(cdp);

  await evaluate(
    cdp,
    `(() => {
      const select = [...document.querySelectorAll('select')][1];
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(select, '1h');
      select.dispatchEvent(new Event('change', { bubbles: true }));
    })()`,
  );
  await delay(1800);
  const horizon = await pageState(cdp);

  const beforeTyping = await evaluate(cdp, "location.href");
  await evaluate(
    cdp,
    `(() => {
      const input = document.querySelector('#event-search');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'bitcoin');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`,
  );
  await delay(500);
  const afterTyping = await evaluate(cdp, "location.href");
  await evaluate(cdp, "document.querySelector('form[role=search]').requestSubmit()");
  await delay(1800);
  const afterSubmit = await evaluate(cdp, "location.href");

  await evaluate(
    cdp,
    `([...document.querySelectorAll('button')].find((button) => button.textContent.trim() === 'All events')?.click(), true)`,
  );
  await delay(1800);
  const allEventsUrl = await evaluate(cdp, "location.href");

  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 1100,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await cdp.send("Page.navigate", { url: initialUrl });
  await delay(3000);
  const desktopScreenshot = await screenshot(cdp, "homework6-desktop.png");

  const checks = {
    mobile_no_horizontal_scroll: mobile.scrollWidth <= mobile.innerWidth,
    mobile_loaded: Boolean(mobile.result) && !mobile.error,
    average_metric_visible: mobile.metric?.startsWith("Average ETH reaction") ?? false,
    top_losers_url:
      quickAction.url.includes("sort=decline") &&
      quickAction.url.includes("horizon=average") &&
      quickAction.url.includes("marketDataOnly=true"),
    specific_horizon_metric: horizon.metric?.startsWith("ETH after 1 hour") ?? false,
    search_does_not_run_per_letter: beforeTyping === afterTyping,
    search_runs_on_submit: afterSubmit.includes("q=bitcoin"),
    all_events_resets_reaction_sort:
      !allEventsUrl.includes("asset=") &&
      !allEventsUrl.includes("sort=") &&
      !allEventsUrl.includes("marketDataOnly="),
  };
  if (Object.values(checks).some((value) => !value)) {
    throw new Error(`Browser smoke test failed: ${JSON.stringify({ checks, mobile, quickAction, horizon })}`);
  }
  console.log(JSON.stringify({ checks, mobile, quickAction, horizon, screenshots: { mobileScreenshot, desktopScreenshot } }, null, 2));
} finally {
  cdp?.close();
  browser.kill();
}
