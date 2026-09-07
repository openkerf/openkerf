/**
 * One fold, one definition.
 *
 * Run: `node --test frontend/tests/one-fold.test.ts`
 * With a server: `OK_BASE=http://127.0.0.1:8126 node --test frontend/tests/one-fold.test.ts`
 *
 * A fold is the same kind of thing everywhere — a line you press to see more — and it
 * was drawn five ways. Measured at 1440 (and again at 1024), before this file existed:
 *
 * | where | marker | case | weight | colour | height 1440 / 1024 |
 * |---|---|---|---|---|---|
 * | Edit, `details.fold` "Image" | triangle, left | sentence | 500 | `--text-1` | 24 / 44 |
 * | Job, `.machinevouw` "Operate machine" | glyph ▸ ▾, left | UPPERCASE 0.44px | 600 | `--text-2` | 15.9 / 18.8 |
 * | Job, `.collapse` "Messages from the machine" | border chevron, right | UPPERCASE 0.66px | 600 | `--text-2` | 15.9 / 44 |
 * | Cut path, "The order, in words" | none | sentence | 400 | `--text-2` | 15.9 / 18.8 |
 * | Setup step 4, "More of this machine" | none | sentence | 500 | `--text-1` | 32 / 44 |
 * | Layers row | none at all — the 26 px colour chip opened the settings | — | — | — | — |
 *
 * Two of those are under 44 px on a tablet, in an app you operate beside a machine.
 *
 * So the fold lives in `tokens.css` now: `details.fold > summary` for a real `details`,
 * and `.foldline` for the one place that cannot be one — the layer row, whose fold hangs
 * outside the row and whose "summary" line holds switches of its own. A component may
 * still say where its fold sits and how wide it is; what it may not do is draw its own
 * marker, its own case or its own weight.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const here = dirname(fileURLToPath(import.meta.url));
const lib = join(here, '..', 'src', 'lib');
const tokens = readFileSync(join(lib, 'tokens.css'), 'utf8');
const components = join(lib, 'components');
const routes = join(here, '..', 'src', 'routes');

function svelteFiles(dir: string, found: string[] = []): string[] {
	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		const path = join(dir, entry.name);
		if (entry.isDirectory()) svelteFiles(path, found);
		else if (entry.name.endsWith('.svelte')) found.push(path);
	}
	return found;
}

/** The stylesheet of a component, with its comments taken out — a comment naming a
 *  property is not a component setting it. */
const styleOf = (source: string) =>
	source.slice(source.indexOf('<style>')).replace(/\/\*[\s\S]*?\*\//g, '');

/** The rules whose selector is about a summary line. */
function summaryRules(style: string): { selector: string; body: string }[] {
	const rules: { selector: string; body: string }[] = [];
	for (const match of style.matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
		const selector = match[1].trim();
		if (/\bsummary\b/.test(selector)) rules.push({ selector, body: match[2] });
	}
	return rules;
}

test('the fold is defined in tokens.css, for a details and for the one line that cannot be one', () => {
	assert.match(tokens, /^details\.fold > summary,\n\.foldline \{/m, 'no shared fold in tokens.css');
	const block = /^details\.fold > summary,\n\.foldline \{[\s\S]*?^\}/m.exec(tokens)?.[0] ?? '';
	for (const property of ['cursor', 'font-weight', 'color', 'min-height']) {
		assert.ok(block.includes(property), `the shared fold does not set ${property}`);
	}
	// The marker, and the same marker open and shut.
	assert.match(tokens, /^details\.fold > summary::before,\n\.foldline::before \{/m, 'the fold has no shared marker');
	assert.match(
		tokens,
		/^details\.fold\[open\] > summary::before,\n\.foldline\[aria-expanded='true'\]::before \{/m,
		'the marker does not turn when the fold opens'
	);
	// A finger, beside a machine.
	assert.match(tokens, /min-height: 44px/, 'no 44 px fold on a coarse pointer');
});

test('no component draws a fold of its own', () => {
	const offenders: string[] = [];
	for (const path of [...svelteFiles(components), ...svelteFiles(routes)]) {
		const style = styleOf(readFileSync(path, 'utf8'));
		const name = path.split('/').pop();
		for (const { selector, body } of summaryRules(style)) {
			if (/::(before|after|marker)|details-marker/.test(selector))
				offenders.push(`${name}: its own summary marker (${selector})`);
			for (const property of ['text-transform', 'font-weight', 'letter-spacing'])
				if (new RegExp(`(^|;|\\s)${property}\\s*:`).test(body))
					offenders.push(`${name}: a summary with its own ${property} (${selector})`);
		}
	}
	assert.deepEqual(offenders, [], `folds drawn a second time: ${offenders.join(' | ')}`);
});

test('every details on a screen is a fold', () => {
	const strays: string[] = [];
	for (const path of [...svelteFiles(components), ...svelteFiles(routes)]) {
		const source = readFileSync(path, 'utf8');
		for (const match of source.matchAll(/<details\b([^>]*)>/g)) {
			if (!/class="[^"]*\bfold\b/.test(match[1])) strays.push(`${path.split('/').pop()}: ${match[0].trim().slice(0, 60)}`);
		}
	}
	assert.deepEqual(strays, [], `a details without the fold class: ${strays.join(' | ')}`);
});

test('the layer row is opened by its name, and the chip is only the colour', () => {
	const source = readFileSync(join(components, 'DesignPanel.svelte'), 'utf8');
	assert.ok(source.includes('class="foldline layer-open"'), 'the layer name is not the opener');
	const opener = /<button\s+class="foldline layer-open"[\s\S]*?>/.exec(source)?.[0] ?? '';
	assert.ok(opener.includes('aria-expanded'), 'the name opener does not say whether it is open');
	const chip = /<button\s+class="chip mono"[\s\S]*?>/.exec(source)?.[0] ?? '';
	assert.ok(chip.includes('colourOpen'), 'the chip still opens the settings instead of the colours');
});

/*
 * And on the screen itself: every fold in the app, at a desk and on a tablet.
 */
const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';
let reachable = false;
let browser: Browser | null = null;

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

async function aDesign() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	for (const layer of [
		{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65 },
		{ type: 'engrave', label: 'Caption', speed: 250, power_percent: 22 }
	])
		await post('/api/design/operations', layer);
	for (let i = 0; i < 2; i++)
		await post('/api/design/elements', { type: 'rect', x_mm: 20 + i * 40, y_mm: 20, width_mm: 30, height_mm: 30 });
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

/** Everything that folds, as the screen has it. */
const FOLDS = `(() => {
	const out = [];
	for (const el of document.querySelectorAll('details.fold > summary, .foldline')) {
		const box = el.getBoundingClientRect();
		if (!box.height) continue;
		const s = getComputedStyle(el);
		const before = getComputedStyle(el, '::before');
		const after = getComputedStyle(el, '::after');
		out.push({
			text: (el.textContent ?? '').trim().replace(/\\s+/g, ' ').slice(0, 40),
			height: Math.round(box.height * 10) / 10,
			weight: s.fontWeight,
			transform: s.textTransform,
			spacing: s.letterSpacing,
			color: s.color,
			markerLeft: parseFloat(before.borderLeftWidth) > 0,
			markerRight: after.content !== 'none' || parseFloat(after.borderRightWidth) > 0
		});
	}
	return out;
})()`;

for (const [width, floor] of [
	[1440, 24],
	[1024, 44]
] as [number, number][]) {
	test(`every fold in the app is the one fold at ${width}`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const context = await browser.newContext({ viewport: { width, height: 900 } });
		const page = await context.newPage();
		const seen: { where: string; fold: Record<string, unknown> }[] = [];
		try {
			for (const [where, url] of [
				['job', `${BASE}/?tab=job`],
				['layers', `${BASE}/?tab=layers`],
				['setup step 4', `${BASE}/setup/settings?machine=ruida`]
			] as [string, string][]) {
				await page.goto(url, { waitUntil: 'domcontentloaded' });
				await page.waitForSelector('details.fold > summary, .foldline', { timeout: 20000 });
				await page.waitForFunction(() => document.fonts?.status === 'loaded', null, { timeout: 20000 });
				for (const fold of (await page.evaluate(FOLDS)) as Record<string, unknown>[])
					seen.push({ where, fold });
			}
			assert.ok(seen.length >= 4, `only ${seen.length} folds found — the walk missed a screen`);
			const first = seen[0].fold;
			for (const { where, fold } of seen) {
				for (const property of ['weight', 'transform', 'color', 'markerLeft', 'markerRight'])
					assert.equal(
						fold[property],
						first[property],
						`${where} — "${fold.text}" has ${property} ${String(fold[property])}, the first fold has ${String(first[property])}`
					);
				assert.ok(
					(fold.height as number) >= floor,
					`${where} — "${fold.text}" is ${fold.height} px, under the ${floor} px this width asks for`
				);
			}
		} finally {
			await context.close();
		}
	});
}
