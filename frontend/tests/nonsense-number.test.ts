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
 * read `Number("abc")` as NaN and stepped from 0. The emptied box did the same thing for
 * the other reason: `Number("")` is 0, 0 is finite, and one click of `+` clamped that to
 * the minimum — measured, `""` then `+` gave `10` again. No refusal, no notice, and
 * 10 dpi is a ruined engraving you find on the material.
 *
 * The third case is the opposite mistake. The boxes are `type="text" inputmode="decimal"`
 * so that a reader who writes 12,5 can type it; measured with a guard that read the string
 * before normalising it, a width of 40.0 mm typed as `12,5` came silently back as `40.0`
 * and nothing was taken — and at a laser 3,5 against 3.5 is two different values.
 *
 * The last test is the same rule one layer up: the value a caller receives is a number
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

    // And the same field emptied: `Number("")` is 0, so a guard that only asks
    // `Number.isFinite` steps from zero and clamps to `min`.
    await box.fill("");
    await box.press("Enter");
    await page.waitForTimeout(900);
    assert.equal(await layerDpi(), 510, "an empty box wrote a number by itself");
    await field.locator("button").last().click();
    await page.waitForTimeout(1200);
    assert.notEqual(
      await layerDpi(),
      10,
      "one click of + on an emptied box dropped the layer to its minimum dpi",
    );
    assert.equal(await layerDpi(), 510, "the layer moved off the number it had");

    // Emptying the box must not make the empty box the value that comes back.
    await box.fill("");
    await box.press("Enter");
    await page.waitForTimeout(700);
    await box.fill("abc");
    await box.press("Enter");
    await page.waitForTimeout(900);
    assert.equal(
      await box.inputValue(),
      "510",
      "after an empty box, nonsense restored the empty box",
    );
  } finally {
    await context.close();
  }
});

/**
 * A decimal comma is a number, in the fields that were made to take one.
 *
 * The Edit card's W is `type="text" inputmode="decimal"` for exactly this reader, and
 * `commitSize` normalises the comma itself. Measured with a component that judged the
 * string first: `12,5` in a 40.0 mm width came back as `40.0`, nothing taken, no sentence.
 */
test("a width typed with a decimal comma is taken", async (t) => {
  if (!reachable || !browser) return noServer(t, BASE);
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();
  try {
    await post("/api/design/elements", {
      type: "rect",
      x_mm: 10,
      y_mm: 10,
      width_mm: 40,
      height_mm: 20,
    });
    await page.goto(`${BASE}/?tab=design`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".statusbar", { timeout: 20000 });
    // The alarm card over the canvas swallows clicks while no machine is connected
    // (NAGEKOMEN N1), and `?tab=edit` does not open the tab on a cold load.
    await page
      .getByRole("button", { name: "Seen" })
      .click()
      .catch(() => {});
    await page.getByRole("tab", { name: "Edit" }).click();
    await page.keyboard.press("ControlOrMeta+a");
    const box = page
      .locator(".field.compact")
      .filter({ hasText: "W" })
      .first()
      .locator("input");
    await box.waitFor({ timeout: 20000 });

    const widthMm = async () => {
      const design = await (await fetch(`${BASE}/api/design`)).json();
      const bounds = design.elements[0].bounds;
      return (bounds[2] - bounds[0]) / design.units_per_mm;
    };
    assert.equal(Math.round(await widthMm()), 40, "the shape did not start at 40 mm");

    await box.fill("12,5");
    await box.press("Enter");
    await page.waitForTimeout(1200);
    assert.equal(
      Math.round((await widthMm()) * 10) / 10,
      12.5,
      "a width typed with a decimal comma was not taken",
    );
  } finally {
    await context.close();
  }
});

/**
 * A bare `Number(...)` on the typed value is what let NaN travel, so no `<NumberField>`
 * hands its value to one.
 *
 * The scope is exactly that, and no wider: the text between `<NumberField` and the `/>`
 * that closes it, in every component that uses the field. A guard that matched only the
 * literal `Number(v)` let `Number(val)`, `Number(value)` and `parseFloat(v)` past, so what
 * is matched here is whatever identifier the handler happens to bind. Code elsewhere in
 * the same file — `commitSize` reads `typedNumber(raw)`, which normalises a decimal comma
 * and calls an empty box nothing — is not this test's business.
 */
test("no NumberField hands its typed value to a bare Number()", () => {
  const components = join(here, "..", "src", "lib", "components");
  const bare = /\b(?:Number|parseFloat)\(\s*[A-Za-z_$][\w$]*\s*\)/;
  const offenders: string[] = [];
  for (const name of readdirSync(components)) {
    if (!name.endsWith(".svelte")) continue;
    const source = readFileSync(join(components, name), "utf8");
    let at = source.indexOf("<NumberField");
    while (at !== -1) {
      const close = source.indexOf("/>", at);
      const block = source.slice(at, close === -1 ? source.length : close);
      const hit = block.match(bare);
      if (hit) offenders.push(`${name}: ${hit[0]}`);
      at = source.indexOf("<NumberField", close === -1 ? source.length : close);
    }
  }
  assert.deepEqual(
    offenders,
    [],
    `these read a typed value without a NaN guard:\n${offenders.join("\n")}`,
  );
});
