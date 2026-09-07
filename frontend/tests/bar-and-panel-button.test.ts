/**
 * The action bar's *More* and the layer list's *List* are one button, measured.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8126 node --test frontend/tests/bar-and-panel-button.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing is pressed that reaches the machine.
 *
 * Why it exists. The two are the same kind of thing — a small text button with a
 * chevron that opens a menu — and they stand on one screen, measured 595.6 px apart at
 * 1440. The round that gave every small button in the right-hand panel one face did not
 * reach the action bar, and the pair came apart: measured at 1440, *List* 32 px at
 * weight 500 against *More* 25.9 px at weight 400.
 *
 * What is measured: both carry the shared `btn mini`, and their height, size and
 * weight are the same number.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';

let reachable = false;
let browser: Browser | null = null;

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/** Two layers, because the list bar that carries *List* only appears above a list. */
async function aDesign() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	for (const layer of [
		{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65 },
		{ type: 'engrave', label: 'Caption', speed: 250, power_percent: 22 }
	])
		await post('/api/design/operations', layer);
	await post('/api/design/elements', { type: 'rect', x_mm: 20, y_mm: 20, width_mm: 30, height_mm: 30 });
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
}

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	browser = await chromium.launch();
	await aDesign();
});

after(async () => {
	await browser?.close();
});

type Face = { cls: string; text: string; height: number; size: string; weight: string };

test('the bar button and the list button are the same button', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();
	try {
		await page.goto(`${BASE}/?tab=layers`, { waitUntil: 'domcontentloaded' });
		await page.waitForSelector('.panel', { timeout: 20000 });
		await page.waitForFunction(() => document.fonts?.status === 'loaded', null, { timeout: 20000 });
		// The layer list lands after the page; wait for the answer, not for a guess
		// about how long it takes.
		await page.waitForSelector('.listmore', { timeout: 20000 });
		const read = (selector: string) =>
			page.$eval(selector, (node) => {
				const style = getComputedStyle(node);
				return {
					cls: node.className.toString(),
					text: (node.textContent ?? '').trim(),
					height: Math.round(node.getBoundingClientRect().height * 10) / 10,
					size: style.fontSize,
					weight: style.fontWeight
				};
			});
		const bar: Face = await read('.actionbar .more');
		const list: Face = await read('.listmore');
		for (const one of [bar, list])
			assert.ok(
				/\bbtn\b/.test(one.cls) && /\bmini\b/.test(one.cls),
				`"${one.text}" is not the shared small button: class="${one.cls}"`
			);
		assert.equal(
			`${bar.height} ${bar.size} ${bar.weight}`,
			`${list.height} ${list.size} ${list.weight}`,
			`the two menu buttons differ: "${bar.text}" ${bar.height} px ${bar.size} ${bar.weight} against "${list.text}" ${list.height} px ${list.size} ${list.weight}`
		);
	} finally {
		await context.close();
	}
});
