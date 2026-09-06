/**
 * The image adjustment rows fit inside the selection card.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8121 node --test frontend/tests/image-fx-fit.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing is started and the head is not moved: a PNG is imported, its
 * adjustments are switched on over the API, and the rows are measured as they stand.
 *
 * Why it exists. `.selected > * { min-width: 0 }` reaches only the card's direct
 * children, so the `.fx` rows inside `details.fold > .imagefx` kept the range input's
 * intrinsic width. Measured at 1440 x 900 with eight adjustments on: every row was
 * 258 px wide in a card whose content box is 245 px, its right edge at x 1448 in a
 * 1440 viewport — the values and the dither picker sat outside the teal border and
 * 8 px beyond the window, and the card scrolled sideways (scrollWidth 270,
 * clientWidth 245). At 1280 the same 258 px row in the same 245 px card.
 *
 * What is measured: no `.fx` row, no value and no picker runs past the card's content
 * box, and the card does not scroll sideways. At three widths, in English and Dutch —
 * Dutch has the longer words.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';
const WIDTHS = [1024, 1280, 1440];
const LANGUAGES = ['en', 'nl'];

let reachable = false;
let browser: Browser | null = null;
let imageId = '';

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/** A grey PNG, so the panel has an image to adjust. Drawn here, not read from disk. */
function aPng(): Uint8Array<ArrayBuffer> {
	// A 2 x 2 greyscale PNG, written by hand so the test carries no fixture file.
	const chunk = (type: string, data: Uint8Array) => {
		const body = new Uint8Array(4 + data.length);
		body.set(new TextEncoder().encode(type), 0);
		body.set(data, 4);
		const length = new Uint8Array(4);
		new DataView(length.buffer).setUint32(0, data.length);
		let crc = 0xffffffff;
		for (const byte of body) {
			crc ^= byte;
			for (let i = 0; i < 8; i++) crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
		}
		const tail = new Uint8Array(4);
		new DataView(tail.buffer).setUint32(0, (crc ^ 0xffffffff) >>> 0);
		return [length, body, tail];
	};
	const header = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
	const ihdr = new Uint8Array([0, 0, 0, 2, 0, 0, 0, 2, 8, 0, 0, 0, 0]);
	// Two scanlines of two pixels, filter byte 0, deflated with stored blocks.
	const raw = new Uint8Array([0, 0x20, 0x80, 0, 0xc0, 0x40]);
	let adler = 1;
	let sum2 = 0;
	for (const byte of raw) {
		adler = (adler + byte) % 65521;
		sum2 = (sum2 + adler) % 65521;
	}
	const zlib = new Uint8Array(2 + 5 + raw.length + 4);
	zlib.set([0x78, 0x01, 0x01, raw.length & 0xff, raw.length >> 8, ~raw.length & 0xff, (~raw.length >> 8) & 0xff]);
	zlib.set(raw, 7);
	new DataView(zlib.buffer).setUint32(7 + raw.length, ((sum2 << 16) | adler) >>> 0);
	const parts = [
		header,
		...chunk('IHDR', ihdr),
		...chunk('IDAT', zlib),
		...chunk('IEND', new Uint8Array(0))
	];
	const total = parts.reduce((n, p) => n + p.length, 0);
	const out = new Uint8Array(new ArrayBuffer(total));
	let at = 0;
	for (const part of parts) {
		out.set(part, at);
		at += part.length;
	}
	return out;
}

/** An imported image with every adjustment the engine offers switched on. */
async function anAdjustedImage() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	const form = new FormData();
	form.append('file', new Blob([aPng()], { type: 'image/png' }), 'photo.png');
	const loaded = await (await fetch(`${BASE}/api/job/load`, { method: 'POST', body: form })).json();
	imageId = loaded.added?.[0] ?? '';
	assert.ok(imageId, 'the PNG was not imported');
	const before = await (await fetch(`${BASE}/api/design/elements/${imageId}/image`)).json();
	for (const item of before.adjustments ?? []) {
		await post(`/api/design/elements/${imageId}/image`, {
			adjustment: item.name,
			enabled: true,
			values: null
		});
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
}

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	browser = await chromium.launch();
	await anAdjustedImage();
});

after(async () => {
	await browser?.close();
});

for (const language of LANGUAGES) {
	for (const width of WIDTHS) {
		test(`the image adjustment rows fit the card in ${language} at ${width} x 900`, async (t) => {
			if (!reachable || !browser) return noServer(t, BASE);
			const context = await browser.newContext({ viewport: { width, height: 900 } });
			await context.addInitScript(
				(lang: string) => localStorage.setItem('openkerf.language', lang),
				language
			);
			const page = await context.newPage();
			try {
				await page.goto(`${BASE}/?tab=design&select=${imageId}`, {
					waitUntil: 'domcontentloaded'
				});
				await page.waitForSelector('.selected', { timeout: 20000 });
				await page.waitForFunction(() => document.fonts?.status === 'loaded', null, {
					timeout: 20000
				});
				// Open the Image fold: it is the one whose summary holds the adjustments.
				await page.evaluate(() => {
					for (const fold of document.querySelectorAll<HTMLDetailsElement>('details.fold')) {
						if (fold.querySelector('.imagefx')) fold.open = true;
					}
				});
				await page.waitForSelector('.fx-value input[type=range]', { timeout: 20000 });
				await page.waitForTimeout(500);
				const measured = await page.evaluate(() => {
					const card = document.querySelector('.selected') as HTMLElement;
					const style = getComputedStyle(card);
					// The content box: the border and the padding are not room for a row.
					const box = card.getBoundingClientRect();
					const right =
						box.right - parseFloat(style.borderRightWidth) - parseFloat(style.paddingRight);
					const over = (node: Element) =>
						Math.round(node.getBoundingClientRect().right - right);
					const worst = (selector: string) => {
						const nodes = [...document.querySelectorAll(selector)];
						return nodes.length ? Math.max(...nodes.map(over)) : -1;
					};
					return {
						rows: worst('.fx'),
						values: worst('.fx-num'),
						pickers: worst('.fx-value select'),
						clientW: card.clientWidth,
						scrollW: card.scrollWidth,
						rowW: Math.round(
							document.querySelector('.fx')?.getBoundingClientRect().width ?? 0
						)
					};
				});
				assert.ok(
					measured.rows <= 0,
					`an adjustment row (${measured.rowW} px) runs ${measured.rows} px past the card`
				);
				assert.ok(measured.values <= 0, `a value runs ${measured.values} px past the card`);
				assert.ok(measured.pickers <= 0, `a picker runs ${measured.pickers} px past the card`);
				assert.equal(
					measured.scrollW,
					measured.clientW,
					`the card scrolls sideways: ${measured.scrollW} px of content in ${measured.clientW} px`
				);
			} finally {
				await context.close();
			}
		});
	}
}
