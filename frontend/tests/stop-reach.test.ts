/**
 * The stop button, measured with a window open.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/stop-reach.test.ts
 *
 * Shares one engine with the other e2e tests, so `--test-concurrency=1`; without a
 * reachable server it skips itself. It never starts a job: the machine on this bench
 * is not connected, and what is measured here is whether the *pixel* under the middle
 * of the button belongs to the button — not what pressing it does.
 *
 * Measured on 1440 x 900 before this was fixed: with the cut-path window open,
 * `elementFromPoint` in the middle of Stop (1104.5, 5.1, 85.5 x 36.8) gave
 * `DIV.backdrop` — the dialog's own layer, `0 0 1440 900`, z-index 100. The same for
 * Pause. `Ctrl/⌘ .` still worked, because the dialog only swallows Escape and Tab,
 * but `TopBar.svelte` argues for that button in so many words: "on a tablet, where
 * this is the only stop button, hover does not exist" — and a tablet has no Ctrl.
 *
 * `Dialog.svelte` already carried the reasoning that fixes it: its backdrop sits
 * below the alarm at 200 because "an alarm about the machine outranks anything you
 * are reading". A button that stops the machine outranks it too.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

let reachable = false;
let browser: Browser | null = null;
let page: Page;

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/** Is the middle of the button the button, or something lying over it? */
async function underTheMiddle(label: string) {
	return page.evaluate((label) => {
		const button = [...document.querySelectorAll('header button')].find((n) =>
			(n.textContent ?? '').trim().startsWith(label)
		);
		if (!button) return { found: false, self: false, over: null as string | null };
		const box = button.getBoundingClientRect();
		const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
		return {
			found: true,
			self: hit === button || button.contains(hit),
			over: hit ? `${hit.tagName}.${typeof hit.className === 'string' ? hit.className : ''}` : null
		};
	}, label);
}

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	const machines: { configured?: boolean }[] = await (await fetch(`${BASE}/api/machines`)).json();
	if (!machines.some((m) => m.configured)) {
		await post('/api/machines', { info: 'ruida-beta', label: 'Stop reach test bench' });
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	// Something on the bed, because the cut-path window refuses to open on an empty one.
	await post('/api/design/elements', { type: 'rect', x_mm: 20, y_mm: 20, width_mm: 60, height_mm: 40 });
	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);
});

after(async () => {
	await browser?.close();
});

test('stopping and pausing stay reachable with a window open', async (t) => {
	if (!reachable) return t.skip(`no server on ${BASE}`);

	for (const label of ['Stop', 'Pause']) {
		const closed = await underTheMiddle(label);
		assert.ok(closed.found, `no ${label} button in the top bar`);
		assert.ok(closed.self, `${label} was already covered by ${closed.over} with nothing open`);
	}

	await page.mouse.click(700, 400);
	await page.waitForTimeout(300);
	await page.keyboard.press('Alt+p');
	await page.waitForTimeout(1200);
	assert.equal(
		await page.$$eval('[role="dialog"]', (n) => n.length),
		1,
		'the cut-path window did not open, so nothing was measured'
	);

	for (const label of ['Stop', 'Pause']) {
		const open = await underTheMiddle(label);
		assert.ok(open.self, `${label} is behind ${open.over} while a window is open`);
	}

	await page.keyboard.press('Escape');
	await page.waitForTimeout(400);
});
