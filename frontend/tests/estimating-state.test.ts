/**
 * While a new estimate is worked out, the button says so — and stays readable.
 *
 * Run: `node --test frontend/tests/estimating-state.test.ts` for the source checks;
 * `OK_BASE=http://127.0.0.1:8126 node --test frontend/tests/estimating-state.test.ts`
 * adds the measurement in a browser. Nothing is pressed that burns: a shape is added
 * through the API and the start button is watched while the engine re-estimates.
 *
 * Why it exists. The estimate used to stand in a labelled row of its own with the word
 * "calculating…" beside it; when the row went, the state went with it and the only sign
 * left was the number on the start button at `opacity: 0.5`. Measured on the running
 * build at 1440 x 900, white on the teal button: 2.64 : 1 in light and 2.75 : 1 in dark,
 * against 4.69 : 1 and 5.98 : 1 for the same number at rest — the one number on the
 * button, dimmed below the contrast the rest of the panel holds, carrying a state that
 * was said nowhere else and reached no screen reader at all.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src', 'lib');
const read = (file: string) => readFileSync(join(src, file), 'utf8');
/** A component with its comments taken out: a rule may not be proved by a comment. */
const code = (file: string) =>
	read(file)
		.replace(/<!--[\s\S]*?-->/g, '')
		.replace(/\/\*[\s\S]*?\*\//g, '');

test('the state on the start button is a word and not only a dimming', () => {
	const source = code('components/JobControls.svelte');
	const start = source.indexOf(`t('job.startJob')`);
	assert.notEqual(start, -1, 'the start button no longer names itself');
	const button = source.slice(source.lastIndexOf('<button', start), source.indexOf('</button>', start));
	assert.ok(/aria-busy=\{estimating\}/.test(button), 'the start button does not say it is busy');
	assert.ok(
		/t\('job\.estimating'\)/.test(button),
		'nothing on the start button says in words that a new time is being worked out'
	);
});

test('the number on the start button is not dimmed to carry that state', () => {
	const source = read('components/JobControls.svelte');
	assert.ok(!/\.pf-start-time\.rekent/.test(source), 'the dimmed estimate rule is back');
	const rule = /\.pf-start-time\s*\{([^}]*)\}/.exec(source);
	assert.ok(rule, 'the estimate on the start button has no rule of its own any more');
	const resting = /opacity:\s*([\d.]+)/.exec(rule[1]);
	assert.ok(resting, 'the estimate has no opacity of its own');
	const dimmer = [...source.matchAll(/opacity:\s*([\d.]+)/g)]
		.map((m) => Number(m[1]))
		.filter((v, i, all) => all.indexOf(v) === i);
	assert.ok(
		!/pf-start[^{]*\{[^}]*opacity:\s*0\.[0-4]/.test(source),
		`something on the start button dims below the resting ${resting[1]} (${dimmer})`
	);
});

test('the word has its Dutch twin', () => {
	for (const file of ['i18n/en.ts', 'i18n/nl.ts'])
		assert.ok(/'job\.estimating':/.test(read(file)), `job.estimating is missing from ${file}`);
});

// ─── Measured in a browser: the button while the engine re-estimates ─────────

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8126';

function luminance(colour: number[]) {
	const parts = colour.map((v) => {
		const c = v / 255;
		return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];
}
function contrast(a: number[], b: number[]) {
	const [light, dark] = [luminance(a), luminance(b)].sort((p, q) => q - p);
	return (light + 0.05) / (dark + 0.05);
}
const rgb = (value: string) => (value.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);

async function post(path: string, body?: unknown) {
	return fetch(BASE + path, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});
}

type State = { cls: string; opacity: string; colour: string; bg: string; busy: string | null; text: string };

/** Every state the start button passed through while a new shape forced a re-estimate. */
async function whileEstimating(theme: 'light' | 'dark') {
	const browser: Browser = await chromium.launch();
	try {
		await post('/api/project/new');
		await post('/api/design/operations', { type: 'cut', label: 'Outline', speed: 12, power_percent: 65 });
		await post('/api/design/elements', { type: 'rect', x_mm: 15, y_mm: 15, width_mm: 120, height_mm: 80 });
		const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: theme });
		if (theme === 'dark')
			await page.addInitScript(() => {
				const set = () => document.documentElement?.setAttribute('data-theme', 'dark');
				set();
				document.addEventListener('DOMContentLoaded', set);
			});
		await page.goto(BASE, { waitUntil: 'domcontentloaded' });
		await page.click('.panel .tab:has-text("Job")');
		// The estimate is the engine building the whole cut plan; before it lands there is
		// no number on the button to watch.
		await page.waitForSelector('.pf-start-time', { timeout: 30000 });
		await page.evaluate(() => {
			const w = window as unknown as { states: State[]; tick: number };
			w.states = [];
			const button = document.querySelector('.pf-start-time')?.closest('button');
			if (!button) return;
			const snap = () => {
				const number = document.querySelector('.pf-start-time');
				if (!number) return;
				const style = getComputedStyle(number);
				const row = {
					cls: number.className,
					opacity: style.opacity,
					colour: style.color,
					bg: getComputedStyle(button).backgroundColor,
					busy: button.getAttribute('aria-busy'),
					text: (button.textContent ?? '').replace(/\s+/g, ' ').trim()
				};
				const last = w.states[w.states.length - 1];
				if (!last || JSON.stringify(last) !== JSON.stringify(row)) w.states.push(row);
			};
			snap();
			new MutationObserver(snap).observe(button, {
				attributes: true,
				childList: true,
				subtree: true,
				characterData: true
			});
			w.tick = setInterval(snap, 50) as unknown as number;
		});
		await post('/api/design/elements', { type: 'circle', cx_mm: 190, cy_mm: 55, r_mm: 30 });
		await page.waitForFunction(
			() => (window as unknown as { states: State[] }).states.some((s) => s.busy === 'true'),
			undefined,
			{ timeout: 30000 }
		);
		await page.waitForTimeout(2000);
		// Awaited before the `finally` closes the browser: a bare `return` of the promise
		// hands the page to a closed browser.
		const states = await page.evaluate(() => {
			const w = window as unknown as { states: State[]; tick: number };
			clearInterval(w.tick);
			return w.states;
		});
		return states;
	} finally {
		await browser.close();
	}
}

for (const theme of ['light', 'dark'] as const)
	test(`the estimate keeps its contrast while it is worked out (${theme})`, async (t) => {
		const up = await fetch(BASE, { signal: AbortSignal.timeout(2000) }).then(
			() => true,
			() => false
		);
		if (!up) return noServer(t, BASE);
		const states = await whileEstimating(theme);
		const busy = states.filter((s) => s.busy === 'true');
		const rest = states.filter((s) => s.busy !== 'true');
		assert.ok(busy.length > 0, 'the button never said it was busy while the estimate was redone');
		assert.ok(rest.length > 0, 'the button never came to rest');
		const seen = (s: State) => {
			const fg = rgb(s.colour);
			const bg = rgb(s.bg);
			const o = Number(s.opacity);
			return contrast(
				fg.map((v, i) => v * o + bg[i] * (1 - o)),
				bg
			);
		};
		const lowestBusy = Math.min(...busy.map(seen));
		const restingContrast = Math.min(...rest.map(seen));
		assert.ok(
			lowestBusy >= restingContrast - 0.01,
			`the number reads at ${lowestBusy.toFixed(2)} : 1 while busy, against ${restingContrast.toFixed(2)} : 1 at rest`
		);
		assert.ok(lowestBusy >= 4.5, `${lowestBusy.toFixed(2)} : 1 while busy`);
	});
