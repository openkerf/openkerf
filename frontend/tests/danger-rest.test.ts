/**
 * The answer that destroys does not look like the way out.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8126 node --test frontend/tests/danger-rest.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing here reaches the machine: two questions are opened and both are
 * answered with the way out.
 *
 * Why it exists. `.btn.danger` had a hover state and a disabled state in `tokens.css`
 * and no rest state, so a button that erases looked exactly like the button beside it
 * that changes nothing. Measured at 1440 on the untouched build, in the Unsaved changes
 * window: *Discard* `color rgb(27,31,36)`, `background rgb(255,255,255)`,
 * `border rgb(214,218,222)` — the same three values as the *Cancel* beside it, in both
 * themes; the Projects delete question the same. Meanwhile the top bar's Stop, the same
 * class, was solid red and the library's Remove was red ink on a red tint: three
 * drawings for one class, and the invisible one stood in the two questions a user meets
 * most.
 *
 * What is measured: in both windows, in both themes, the destroying answer differs from
 * the way out beside it in letter, fill and border, and its letter is the danger colour
 * of the theme it stands in.
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

/** A project on disk to ask the delete question about, and a shape to be unsaved about. */
const PROJECT = 'Danger rest';

async function aDesign() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	await post('/api/design/elements', {
		type: 'rect',
		x_mm: 20,
		y_mm: 20,
		width_mm: 30,
		height_mm: 30
	});
	await post(`/api/projects/${encodeURIComponent(PROJECT)}`);
	// One more shape, so the document is dirty again and the unsaved question is asked.
	await post('/api/design/elements', {
		type: 'rect',
		x_mm: 70,
		y_mm: 20,
		width_mm: 30,
		height_mm: 30
	});
}

type Paint = { label: string; color: string; background: string; border: string };

/** What the buttons of one row are painted, at rest. */
const paintRow = (selector: string): Paint[] => {
	const row = document.querySelector(selector);
	if (!row) return [];
	return [...row.querySelectorAll('button')].map((node) => {
		const s = getComputedStyle(node);
		return {
			label: (node.textContent ?? '').trim().replace(/\s+/g, ' '),
			color: s.color,
			background: s.backgroundColor,
			border: s.borderTopColor
		};
	});
};

/** The theme's own danger colour, as the page resolves it. */
const dangerInk = (): string => {
	const probe = document.createElement('span');
	probe.style.color = 'var(--danger)';
	document.body.append(probe);
	const answer = getComputedStyle(probe).color;
	probe.remove();
	return answer;
};

/** Held against one question: the two answers are not the same drawing. */
function apart(paints: Paint[], danger: string, where: string) {
	const wayOut = paints.find((p) => /^Cancel/.test(p.label));
	const destroys = paints.find((p) => /^(Discard|Delete)/.test(p.label));
	assert.ok(wayOut, `${where}: no way out in the row (${paints.map((p) => p.label).join(' | ')})`);
	assert.ok(destroys, `${where}: no destroying answer in the row`);
	assert.notEqual(destroys.color, wayOut.color, `${where}: the letter is the way out's letter`);
	assert.notEqual(destroys.background, wayOut.background, `${where}: the fill is the way out's fill`);
	assert.notEqual(destroys.border, wayOut.border, `${where}: the border is the way out's border`);
	assert.equal(destroys.color, danger, `${where}: the letter is not the theme's danger colour`);
}

async function fresh(theme: 'light' | 'dark'): Promise<Page> {
	const context = await browser!.newContext({
		viewport: { width: 1440, height: 900 },
		colorScheme: theme
	});
	const page = await context.newPage();
	if (theme === 'dark')
		await page.addInitScript(() => {
			const set = () => document.documentElement?.setAttribute('data-theme', 'dark');
			set();
			document.addEventListener('DOMContentLoaded', set);
		});
	return page;
}

async function loaded(page: Page) {
	await page.goto(`${BASE}/?tab=layers`, { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.panel', { timeout: 20000 });
	await page.waitForFunction(() => document.fonts?.status === 'loaded', null, { timeout: 20000 });
	await page.waitForTimeout(3000);
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
	if (reachable)
		await fetch(`${BASE}/api/projects/${encodeURIComponent(PROJECT)}`, { method: 'DELETE' }).catch(
			() => {}
		);
});

for (const theme of ['light', 'dark'] as const) {
	test(`Discard is not Cancel in the unsaved-changes window (${theme})`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const page = await fresh(theme);
		try {
			await loaded(page);
			await page.locator('.project-button').first().click({ timeout: 10000 });
			await page.waitForTimeout(300);
			await page.getByRole('menuitem', { name: /New/i }).first().click({ timeout: 10000, force: true });
			await page.waitForSelector('[role=dialog] .ask-actions, [role=dialog] .answers', {
				timeout: 10000
			});
			const paints = await page.evaluate(paintRow, '[role=dialog] .ask-actions, [role=dialog] .answers');
			const danger = await page.evaluate(dangerInk);
			apart(paints, danger, `the unsaved-changes window (${theme})`);
			// Nothing is thrown away: the question is left the way it was found.
			await page.keyboard.press('Escape');
		} finally {
			await page.context().close();
		}
	});

	test(`Delete is not Cancel in the Projects window (${theme})`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const page = await fresh(theme);
		try {
			await loaded(page);
			await page.locator('.project-button').first().click({ timeout: 10000 });
			await page.waitForTimeout(300);
			await page.getByRole('menuitem', { name: /Open…/ }).first().click({ timeout: 10000, force: true });
			await page.waitForSelector('[role=dialog] .row', { timeout: 10000 });
			const row = page.locator('[role=dialog] .row').filter({ hasText: PROJECT }).first();
			await row.locator('button').last().click({ timeout: 10000, force: true });
			await page.waitForTimeout(300);
			await page.getByRole('menuitem', { name: /Delete/i }).first().click({ timeout: 10000, force: true });
			await page.waitForSelector('[role=dialog] .ask .ask-actions', { timeout: 10000 });
			const paints = await page.evaluate(paintRow, '[role=dialog] .ask .ask-actions');
			const danger = await page.evaluate(dangerInk);
			apart(paints, danger, `the Projects window (${theme})`);
			// The project stays: the question is answered with the way out.
			await page.getByRole('button', { name: /^Cancel$/ }).first().click({ force: true });
		} finally {
			await page.context().close();
		}
	});
}
