/**
 * The frame button in the top bar keeps its word at every width its own comment promises.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8184 node --test frontend/tests/frame-word.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing is pressed: the bar is measured as it loads. The frame is never run.
 *
 * Why it exists. `TopBar.svelte` says the frame keeps its word on a tablet — "a thin
 * dashed square says nothing" — and drops it on purpose only below 850 px. The rule that
 * did that, `.frame .short { display: inline }` inside the 1199 media block, was written
 * with the same specificity as the `.btn-label.short { display: none }` default further
 * down the file, and the later one won. Measured: at 1024 and at 800 both labels of the
 * frame button computed to `none`, the button was a 50 x 44 dashed square with no word,
 * and Pause, Stop and Start beside it kept theirs.
 *
 * What is measured: the text that is actually visible on the frame button. At 1440 the
 * long form ("Show frame"); at 1024 and at 850 the short one ("Frame"); at 849 and 800
 * none at all — that last row is the deliberate trade documented in the file, and it is
 * held here so that a fix for the tablet cannot silently give the word back to the phone.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';

/** Width → the word the frame button shows there ('' = none, by design). */
const EXPECTED: [number, 'lang' | 'short' | 'none'][] = [
	[1440, 'lang'],
	[1199, 'short'],
	[1024, 'short'],
	[850, 'short'],
	[849, 'none'],
	[800, 'none']
];

let reachable = false;
let browser: Browser | null = null;

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	browser = await chromium.launch();
});

after(async () => {
	await browser?.close();
});

for (const [width, form] of EXPECTED) {
	test(`the frame button shows its ${form} label at ${width} px`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const context = await browser.newContext({ viewport: { width, height: 900 } });
		await context.addInitScript(() => localStorage.setItem('openkerf.language', 'en'));
		const page = await context.newPage();
		try {
			await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
			await page.waitForSelector('.topbar .btn.frame', { timeout: 20000 });
			await page.waitForFunction(() => document.fonts?.status === 'loaded', null, {
				timeout: 20000
			});
			const measured = await page.evaluate(() => {
				const button = document.querySelector('.topbar .btn.frame')!;
				const shown = [...button.querySelectorAll('.btn-label')]
					.filter((n) => getComputedStyle(n).display !== 'none')
					.map((n) => ({
						form: n.classList.contains('lang') ? 'lang' : 'short',
						text: (n.textContent ?? '').trim()
					}));
				const box = button.getBoundingClientRect();
				return { shown, width: Math.round(box.width), height: Math.round(box.height) };
			});
			if (form === 'none') {
				assert.deepEqual(
					measured.shown,
					[],
					`at ${width} the frame button should be icon-only, it shows ${JSON.stringify(measured.shown)}`
				);
			} else {
				assert.equal(
					measured.shown.length,
					1,
					`at ${width} exactly one frame label should be visible, got ${JSON.stringify(measured.shown)} (button ${measured.width} x ${measured.height})`
				);
				assert.equal(measured.shown[0].form, form);
				assert.equal(measured.shown[0].text, form === 'lang' ? 'Show frame' : 'Frame');
			}
		} finally {
			await context.close();
		}
	});
}
