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
 * What is measured: in all three windows, in both themes, the destroying answer differs
 * from the way out beside it in letter and in border, its letter is the danger colour of
 * the theme it stands in, and that letter is at least 4.5:1 against everything painted
 * behind it — because colour is the whole of the difference, it has to be readable.
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
/**
 * A second project, saved last, so it is the current one. `ProjectsStore.taken` calls a
 * name taken only when it is not the project you are already in, so Save as… only asks
 * the overwrite question about a name that is not the open document's.
 */
const OTHER = 'Danger rest current';

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
	await post(`/api/projects/${encodeURIComponent(OTHER)}`);
	// One more shape, so the document is dirty again and the unsaved question is asked.
	await post('/api/design/elements', {
		type: 'rect',
		x_mm: 70,
		y_mm: 20,
		width_mm: 30,
		height_mm: 30
	});
}

type Paint = {
	label: string;
	color: string;
	background: string;
	border: string;
	/** The letter against the colour actually painted behind it, composited up the tree. */
	contrast: number;
};

/** What the buttons of one row are painted, at rest, and what their letter is worth on it. */
const paintRow = (selector: string): Paint[] => {
	const row = document.querySelector(selector);
	if (!row) return [];
	const channels = (value: string): number[] => {
		const n = (value.match(/[\d.]+/g) ?? []).map(Number);
		// `color(srgb r g b / a)`, which is what color-mix() resolves to, is 0..1 per channel.
		if (value.startsWith('color(')) return [n[0] * 255, n[1] * 255, n[2] * 255, n.length > 3 ? n[3] : 1];
		return n;
	};
	const luminance = (c: number[]): number => {
		const f = c.slice(0, 3).map((v) => {
			const s = v / 255;
			return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
		});
		return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
	};
	const ratio = (a: number[], b: number[]): number => {
		const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
		return (hi + 0.05) / (lo + 0.05);
	};
	/** Everything painted behind this node, from the page down to the node itself. */
	const behind = (node: Element): number[] => {
		const chain: number[][] = [];
		for (let el: Element | null = node; el; el = el.parentElement)
			chain.push(channels(getComputedStyle(el).backgroundColor));
		let base = [255, 255, 255];
		for (let i = chain.length - 1; i >= 0; i--) {
			const c = chain[i];
			if (!c.length) continue;
			const a = c.length > 3 ? c[3] : 1;
			base = [0, 1, 2].map((k) => c[k] * a + base[k] * (1 - a));
		}
		return base;
	};
	return [...row.querySelectorAll('button')].map((node) => {
		const s = getComputedStyle(node);
		return {
			label: (node.textContent ?? '').trim().replace(/\s+/g, ' '),
			color: s.color,
			background: s.backgroundColor,
			border: s.borderTopColor,
			contrast: Math.round(ratio(channels(s.color), behind(node)) * 100) / 100
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
	const destroys = paints.find((p) => /^(Discard|Delete|Replace)/.test(p.label));
	assert.ok(wayOut, `${where}: no way out in the row (${paints.map((p) => p.label).join(' | ')})`);
	assert.ok(destroys, `${where}: no destroying answer in the row`);
	assert.notEqual(destroys.color, wayOut.color, `${where}: the letter is the way out's letter`);
	assert.notEqual(destroys.border, wayOut.border, `${where}: the border is the way out's border`);
	assert.equal(destroys.color, danger, `${where}: the letter is not the theme's danger colour`);
	// The two signals are colour, so the red has to be readable where it stands: AA for
	// normal text. Measured, the drawing gives 5.32 light and 4.78 dark; a fill behind it
	// would take the dark one to 4.34.
	assert.ok(
		destroys.contrast >= 4.5,
		`${where}: the letter is ${destroys.contrast}:1 on what is painted behind it, under 4.5`
	);
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
		for (const name of [PROJECT, OTHER])
			await fetch(`${BASE}/api/projects/${encodeURIComponent(name)}`, { method: 'DELETE' }).catch(
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

	test(`Replace is not Cancel in the overwrite question (${theme})`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const page = await fresh(theme);
		try {
			await loaded(page);
			await page.locator('.project-button').first().click({ timeout: 10000 });
			await page.waitForTimeout(300);
			// Dispatched rather than clicked: with no machine connected the alarm card lies
			// over this row of the menu, and even a forced click lands on the card (N1).
			await page
				.getByRole('menuitem', { name: /Save as…/ })
				.first()
				.dispatchEvent('click');
			await page.waitForSelector('[role=dialog] input.project-name', { timeout: 10000 });
			// The window fills its list after it opens, and `taken` reads that list.
			await page.waitForSelector(`[role=dialog] .row:has-text("${PROJECT}")`, { timeout: 10000 });
			// The name of another project on the server, so Save asks before it replaces.
			await page.locator('[role=dialog] input.project-name').fill(PROJECT);
			await page.waitForTimeout(300);
			await page.locator('[role=dialog] button.save').dispatchEvent('click');
			// The whole question, not its `.ask-actions`: the untouched build words this
			// one row without that class, and this test has to be able to fail on it.
			await page.waitForSelector('[role=dialog] .ask button.danger', { timeout: 10000 });
			const paints = await page.evaluate(paintRow, '[role=dialog] .ask');
			const danger = await page.evaluate(dangerInk);
			apart(paints, danger, `the overwrite question (${theme})`);
			// Nothing is overwritten: the question is answered with the way out.
			await page.getByRole('button', { name: /^Cancel$/ }).first().click({ force: true });
		} finally {
			await page.context().close();
		}
	});
}
