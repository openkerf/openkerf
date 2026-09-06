/**
 * The sentence on an empty bed names a control that is on the screen it is shown on.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8184 node --test frontend/tests/empty-bed-sentence.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing is pressed: the bed is emptied through the API and read as it stands.
 *
 * Why it exists (gauntlet P33). "Use Import in the top bar for an existing design, or
 * pick a shape on the left and click the bed." was rendered at every width, while the
 * bar it points at only holds Import from 1200 px up: at 1024 the bar has machine,
 * Material, project, frame, Pause, Stop, Start, EN and theme, and Import is a row in the
 * rail's More menu. So on the one device that stands beside the machine the first
 * sentence a new user reads sent them to a button that was not there. The bar itself
 * already changes its words per width ("Show frame" / "Frame"); the sentence now does too.
 *
 * The Edit panel's own empty text ("Nothing on the bed yet. Import in the top bar…")
 * sent the reader to the same absent button one panel away, so it is held here too.
 *
 * What is measured, in English and in Dutch, at 1440 (desk) and at 1024 and 800
 * (tablet): for both empty texts, the words the sentence uses for its control — the
 * bar's Import label or the rail's More label — belong to a button that is visible at
 * that width, and no word of a button that is hidden at that width appears in it.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';
import { en } from '../src/lib/i18n/en.ts';
import { nl } from '../src/lib/i18n/nl.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';
const SIZES: [number, number][] = [
	[1440, 900],
	[1024, 900],
	[800, 900]
];
/** The catalogue also holds plural forms; every key read here is a plain sentence. */
const CATALOGUES: Record<string, Record<string, unknown>> = { en, nl };
const word = (catalogue: Record<string, unknown>, key: string) => String(catalogue[key]);

let reachable = false;
let browser: Browser | null = null;

async function anEmptyBed() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/project/new`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: '{}'
	});
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
}

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	browser = await chromium.launch();
	await anEmptyBed();
});

after(async () => {
	await browser?.close();
});

/** A whole word, so "Import" in the sentence is not found inside "Importeren". */
const names = (sentence: string, word: string) =>
	new RegExp(`(^|[^\\p{L}])${word}([^\\p{L}]|$)`, 'u').test(sentence);

for (const language of Object.keys(CATALOGUES)) {
	for (const [width, height] of SIZES) {
		test(`the empty-bed sentence names a visible control in ${language} at ${width} px`, async (t) => {
			if (!reachable || !browser) return noServer(t, BASE);
			const catalogue = CATALOGUES[language];
			const importWord = word(catalogue, 'topbar.import');
			const moreWord = word(catalogue, 'rail.more');
			const context = await browser.newContext({ viewport: { width, height } });
			await context.addInitScript(
				(lang: string) => localStorage.setItem('openkerf.language', lang),
				language
			);
			const page = await context.newPage();
			try {
				await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
				await page.waitForSelector('.blank p', { timeout: 20000 });
				const measured = await page.evaluate(() => {
					const visible = (node: Element) => {
						const box = node.getBoundingClientRect();
						return box.width > 0 && box.height > 0 && getComputedStyle(node).display !== 'none';
					};
					const barLabels = [...document.querySelectorAll('.topbar .btn')]
						.filter(visible)
						.map((node) => (node.textContent ?? '').trim());
					const railLabels = [...document.querySelectorAll('.rail .tool')]
						.filter(visible)
						.map((node) => (node.textContent ?? '').trim());
					return {
						sentences: [...document.querySelectorAll('.blank p, p.empty')]
							.filter(visible)
							.map((node) => (node.textContent ?? '').trim()),
						barLabels,
						railLabels
					};
				});
				const barHasImport = measured.barLabels.includes(importWord);
				const railHasMore = measured.railLabels.includes(moreWord);
				assert.ok(
					barHasImport !== railHasMore,
					`expected exactly one of bar Import (${barHasImport}) and rail More (${railHasMore}) at ${width} px`
				);
				// The bed's text is always there; the panel's is there at 1440 and 1024 and
				// gone at 800, where the right-hand panel is folded shut.
				assert.ok(
					measured.sentences.length >= (width >= 1024 ? 2 : 1),
					`expected the empty texts on screen, got ${JSON.stringify(measured.sentences)}`
				);
				for (const sentence of measured.sentences) {
					assert.equal(
						names(sentence, importWord),
						barHasImport,
						`"${sentence}" names "${importWord}" but the bar shows ${JSON.stringify(measured.barLabels)}`
					);
					assert.equal(
						names(sentence, moreWord),
						railHasMore,
						`"${sentence}" names "${moreWord}" but the rail shows ${JSON.stringify(measured.railLabels)}`
					);
				}
			} finally {
				await context.close();
			}
		});
	}
}
