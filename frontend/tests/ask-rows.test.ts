/**
 * The buttons that answer a question stand in one place, measured on screen.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8126 node --test frontend/tests/ask-rows.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing is pressed that reaches the machine: the three questions opened here
 * are answered with Cancel, and the transport row is measured from the stylesheet on a
 * row built beside the page — never on a running job.
 *
 * Why it exists. `one-ask.test.ts` reads the source; this reads the screen, because the
 * fault was a place and a distance. Measured at 1440 on the untouched build:
 *
 *   Unsaved changes    Save | Discard | Cancel — the primary at x 680.9, Cancel at 838.6
 *   Layer, remove      Cancel | Remove at the *start* of the line, 101.8 px of panel to
 *                      the right of them, 8 px between the two
 *   Sheet, remove      Cancel | Remove at the end of the line, 24 px between the two
 *
 * and in the running job's block `.btn.stop` still carried `grid-column: 1 / -1` and
 * `margin-top: var(--space-6)` from the four-button grid that block replaced: in a
 * centred flex row that put Stop 12 px below Pause, in every phase.
 *
 * What is measured: every ask row lays its buttons out to the end of the line, on one
 * baseline, with the way out first and the answer that cannot be undone 24 px from its
 * neighbour; and the stop button in the running row sits on the same line as pause.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';
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

/** Two layers, two shapes and a second sheet: enough for all three questions. */
async function aDesign() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	for (const layer of [
		{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65 },
		{ type: 'engrave', label: 'Caption', speed: 250, power_percent: 22 }
	])
		await post('/api/design/operations', layer);
	for (let i = 0; i < 2; i++)
		await post('/api/design/elements', {
			type: 'rect',
			x_mm: 20 + i * 40,
			y_mm: 20,
			width_mm: 30,
			height_mm: 30
		});
	await post('/api/sheets', { name: 'Second sheet' });
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
}

type Row = {
	justify: string;
	topSpread: number;
	buttons: { label: string; left: number; right: number; danger: boolean }[];
};

/**
 * One row, as it stands: what it does with the room, and where its buttons are.
 *
 * The selectors are tried in order — not handed to `querySelector` as one comma list,
 * which answers with whichever matches first in the document and so returned the
 * confirmation box rather than the row inside it.
 */
const measureRow = (selectors: string[]): Row | null => {
	let row: Element | null = null;
	for (const selector of selectors) {
		row = document.querySelector(selector);
		if (row) break;
	}
	if (!row) return null;
	const buttons = [...row.querySelectorAll('button')]
		.map((node) => {
			const box = node.getBoundingClientRect();
			return {
				label: (node.textContent ?? '').trim().replace(/\s+/g, ' '),
				left: Math.round(box.left * 10) / 10,
				right: Math.round(box.right * 10) / 10,
				top: Math.round(box.top * 10) / 10,
				danger: /\b(danger|drop|gone)\b/.test(node.className.toString())
			};
		})
		.sort((a, b) => a.left - b.left);
	const tops = buttons.map((b) => b.top);
	return {
		justify: getComputedStyle(row).justifyContent,
		topSpread: Math.round((Math.max(...tops) - Math.min(...tops)) * 10) / 10,
		buttons: buttons.map(({ label, left, right, danger }) => ({ label, left, right, danger }))
	};
};

/** The shared row's promise, held against one measured row. */
function holds(row: Row | null, where: string) {
	assert.ok(row, `${where}: no ask row on screen`);
	assert.ok(row.buttons.length >= 2, `${where}: fewer than two buttons`);
	assert.equal(row.justify, 'flex-end', `${where}: the row does not stand at the end of its line`);
	assert.ok(row.topSpread <= 1, `${where}: the buttons are ${row.topSpread} px apart vertically`);
	assert.match(row.buttons[0].label, /^(Cancel|Leave it|Not now)/, `${where}: the way out is not the first button — the row reads ${row.buttons.map((b) => b.label).join(' | ')}`);
	assert.doesNotMatch(
		row.buttons[row.buttons.length - 1].label,
		/^(Cancel|Leave it|Not now)/,
		`${where}: the way out is the last button`
	);
	for (let i = 1; i < row.buttons.length; i++) {
		if (!row.buttons[i].danger && !row.buttons[i - 1].danger) continue;
		const between: number = Math.round((row.buttons[i].left - row.buttons[i - 1].right) * 10) / 10;
		assert.ok(between >= 23, `${where}: only ${between} px beside the answer that cannot be undone`);
	}
}

async function fresh(): Promise<Page> {
	const context = await browser!.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();
	return page;
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

test('the unsaved-changes question is answered at the end of its footer', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const page = await fresh();
	try {
		await page.goto(`${BASE}/?tab=layers`, { waitUntil: 'domcontentloaded' });
		await page.waitForSelector('.panel', { timeout: 20000 });
		await page.waitForFunction(() => document.fonts?.status === 'loaded', null, { timeout: 20000 });
		await page.waitForTimeout(3000);
		await page.locator('.project-button').first().click({ timeout: 10000 });
		await page.waitForTimeout(300);
		await page.getByRole('menuitem', { name: /New/i }).first().click({ timeout: 10000, force: true });
		await page.waitForSelector('[role=dialog] .ask-actions, [role=dialog] .answers', { timeout: 10000 });
		const row = await page.evaluate(measureRow, ['[role=dialog] .ask-actions', '[role=dialog] .answers']);
		holds(row, 'the unsaved-changes window');
		// Nothing is thrown away: the question is left the way it was found.
		await page.keyboard.press('Escape');
	} finally {
		await page.context().close();
	}
});

test('the layer removal is answered at the end of the panel', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const page = await fresh();
	try {
		await page.goto(`${BASE}/?tab=layers`, { waitUntil: 'domcontentloaded' });
		await page.waitForSelector('.panel', { timeout: 20000 });
		await page.waitForFunction(() => document.fonts?.status === 'loaded', null, { timeout: 20000 });
		await page.waitForTimeout(3000);
		// The layer card opens by its name; before P19 it opened by its colour chip.
		const opener = page.locator('.layer .layer-open').first();
		await ((await opener.count()) ? opener : page.locator('.layer [aria-expanded]').first()).click({
			timeout: 10000
		});
		await page.waitForTimeout(400);
		await page.getByRole('button', { name: /Remove layer/i }).first().click({ timeout: 10000 });
		await page.waitForSelector('.confirm', { timeout: 10000 });
		const row = await page.evaluate(measureRow, ['.confirm .ask-actions', '.confirm']);
		holds(row, "the layer card's confirmation");
		await page.getByRole('button', { name: /^Cancel$/ }).first().click();
	} finally {
		await page.context().close();
	}
});

test('the sheet removal is answered at the end of its line', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const page = await fresh();
	try {
		await page.goto(`${BASE}/?tab=layers`, { waitUntil: 'domcontentloaded' });
		await page.waitForSelector('.sheets .sheet', { timeout: 20000 });
		await page.waitForFunction(() => document.fonts?.status === 'loaded', null, { timeout: 20000 });
		await page.waitForTimeout(2500);
		await page.locator('.sheets .sheet[aria-pressed=true]').first().click({ timeout: 10000, force: true });
		await page.waitForTimeout(300);
		await page
			.getByRole('button', { name: /Remove the sheet/i })
			.first()
			.click({ timeout: 10000, force: true });
		await page.waitForSelector('.confirm', { timeout: 10000 });
		const row = await page.evaluate(measureRow, ['.confirm .ask-actions', '.confirm .buttons']);
		holds(row, "the sheet's confirmation");
		await page.getByRole('button', { name: /^Cancel$/ }).first().click({ force: true });
	} finally {
		await page.context().close();
	}
});

test('stop stands on the same line as pause in the running block', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const page = await fresh();
	try {
		await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
		await page.waitForSelector('.panel', { timeout: 20000 });
		await page.waitForTimeout(2000);
		// The running block is only there while a job runs, and this app never starts
		// one to look at itself. So the row is built beside the page out of the app's
		// own stylesheet — the same classes, the same rules, no machine involved.
		const measured = await page.evaluate(async () => {
			let css = '';
			for (const link of [...document.querySelectorAll('link[rel=stylesheet]')])
				css += await (await fetch((link as HTMLLinkElement).href)).text();
			const scope = /\.now-actions\.(svelte-[a-z0-9]+)/.exec(css)?.[1] ?? '';
			const host = document.createElement('div');
			host.style.cssText = 'position:fixed;left:0;top:0;width:245px';
			host.innerHTML =
				`<div class="now-actions ${scope}">` +
				`<button class="btn danger stop ${scope}">Stop</button>` +
				`<span class="now-stretch ${scope}"></span>` +
				`<button class="btn ${scope}">Pause</button></div>`;
			document.body.append(host);
			const [stop, pause] = [...host.querySelectorAll('button')].map((n) =>
				n.getBoundingClientRect()
			);
			const answer = {
				scope,
				lower: Math.round((stop.top - pause.top) * 10) / 10,
				stopLeft: Math.round(stop.left),
				pauseLeft: Math.round(pause.left)
			};
			host.remove();
			return answer;
		});
		assert.ok(measured.scope, 'the running row was not found in the stylesheet');
		assert.equal(measured.lower, 0, `stop sits ${measured.lower} px below pause`);
		assert.ok(
			measured.stopLeft < measured.pauseLeft,
			'stop does not stand at the start of the row'
		);
	} finally {
		await page.context().close();
	}
});
