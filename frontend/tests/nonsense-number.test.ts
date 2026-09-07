/**
 * A number field that is handed nonsense keeps the number it had.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8126 node --test frontend/tests/nonsense-number.test.ts
 *
 * One engine is shared with the other e2e tests, so use `--test-concurrency=1`. Skips
 * itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a failure).
 * Nothing is started and the head is never moved: a raster layer is made over the API and
 * its DPI is typed at.
 *
 * Why it exists. Measured on a raster layer at 500 dpi: typing `abc` in the DPI field and
 * pressing Enter left `"abc"` standing in the box while the layer still said 500, and one
 * click on that field's own `+` committed **10** — the field's `min` — because `set()`
 * read `Number("abc")` as NaN and stepped from 0. No refusal, no notice, and 10 dpi is a
 * ruined engraving you find on the material. The five geometry fields in the same card
 * were already honest, which is what made this a defect and not a house style.
 *
 * The second test is the same rule one layer up: the value a caller receives is a number
 * or the caller is not called at all, so nobody re-invents `Number(v)` without a guard.
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { chromium, type Browser } from "playwright";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { noServer } from "./no-server.ts";

const BASE = process.env.OK_BASE ?? "http://127.0.0.1:8126";
const here = dirname(fileURLToPath(import.meta.url));

let reachable = false;
let browser: Browser | null = null;
let rasterId = "";

const post = (path: string, body?: unknown) =>
  fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });

const layerDpi = async () => {
  const design = await (await fetch(`${BASE}/api/design`)).json();
  return design.operations.find((op: { id: string }) => op.id === rasterId)
    ?.dpi;
};

before(async () => {
  reachable = await fetch(`${BASE}/api/health`, {
    signal: AbortSignal.timeout(2000),
  })
    .then((r) => r.ok)
    .catch(() => false);
  if (!reachable) return;
  browser = await chromium.launch();
  await fetch(`${BASE}/api/design/autosave`, { method: "DELETE" }).catch(
    () => {},
  );
  await post("/api/project/new");
  await post("/api/design/operations", {
    type: "raster",
    label: "Logo area",
    speed: 300,
    power_percent: 30,
  });
  const design = await (await fetch(`${BASE}/api/design`)).json();
  const raster = design.operations.find(
    (op: { type: string }) => op.type === "op raster",
  );
  assert.ok(raster, "no raster layer to type in");
  rasterId = raster.id;
  await fetch(`${BASE}/api/design/operations/${rasterId}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ dpi: 500 }),
  });
  await fetch(`${BASE}/api/design/autosave`, { method: "DELETE" }).catch(
    () => {},
  );
});

after(async () => {
  await browser?.close();
});

test("nonsense in the DPI field neither stands nor becomes the minimum", async (t) => {
  if (!reachable || !browser) return noServer(t, BASE);
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();
  try {
    await page.goto(`${BASE}/?tab=layers`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".statusbar", { timeout: 20000 });
    await page
      .locator(".foldline.layer-open", { hasText: "Logo area" })
      .first()
      .click();
    const field = page
      .locator(".layer-edit .field")
      .filter({ hasText: "DPI" })
      .first();
    const box = field.locator("input");
    await box.waitFor({ timeout: 20000 });

    assert.equal(
      await box.inputValue(),
      "500",
      "the field did not start at 500",
    );
    assert.equal(await layerDpi(), 500, "the layer did not start at 500");

    await box.fill("abc");
    await box.press("Enter");
    await page.waitForTimeout(900);
    assert.equal(
      await box.inputValue(),
      "500",
      "the field kept a number the layer does not have",
    );
    assert.equal(await layerDpi(), 500, "nonsense reached the layer");

    await field.locator("button").last().click();
    await page.waitForTimeout(1200);
    const after = await layerDpi();
    assert.notEqual(
      after,
      10,
      "one click of + dropped the layer to its minimum dpi",
    );
    assert.equal(
      after,
      510,
      "the step did not start from the number that was there",
    );
    assert.equal(await box.inputValue(), "510");
  } finally {
    await context.close();
  }
});

/**
 * `Number(v)` on its own is what let NaN travel, so no caller of a `NumberField` writes it.
 *
 * The component now keeps a value that is not a number to itself, and the guard here is
 * the second half of the same rule: a handler that receives a value hands it through
 * `whenNumber`, which does not call on when the text is not a number.
 */
test("no onchange of a NumberField parses its value with a bare Number()", () => {
  const components = join(here, "..", "src", "lib", "components");
  const offenders: string[] = [];
  for (const name of readdirSync(components)) {
    if (!name.endsWith(".svelte")) continue;
    const source = readFileSync(join(components, name), "utf8");
    if (!source.includes("NumberField")) continue;
    for (const line of source.split("\n")) {
      if (/\bNumber\(\s*v\s*\)/.test(line))
        offenders.push(`${name}: ${line.trim()}`);
    }
  }
  assert.deepEqual(
    offenders,
    [],
    `these read a typed value without a NaN guard:\n${offenders.join("\n")}`,
  );
});
