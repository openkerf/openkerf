/**
 * The second-client band takes room of its own; it does not lie over the canvas.
 *
 * Running against the scratch server with its emulated Ruida (frontend/gauntlet/README.md):
 *   OK_BASE=http://127.0.0.1:8092 node --test frontend/tests/second-client-room.test.ts
 *
 * Needs `POST /api/gauntlet/state`, which only the scratch server has: the warning is
 * raised by our own line when the emulator swallows two of every five status answers, the
 * way a KH-5030 did with a second program on it. Without a reachable server the file
 * skips itself (`OK_REQUIRE_SERVER=1` makes that a failure); a server without the route —
 * somebody's real installation — is skipped too, because the only way to raise the band
 * there is a second program on a real controller.
 *
 * Why it exists. The band ("Another program seems to be talking to this laser") was fixed
 * to the bottom of the page above the status bar, and it stays for as long as the other
 * program does, with nothing to dismiss it by. Measured in handbook shot 54 at 1440 x 900:
 * it covered the canvas's zoom bar — zoom, Fit and the snap toggles — and the foot of the
 * panel. It is in the page's column now, and the work area gives up its height.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8092';
const SIZES: [number, number][] = [
	[1280, 800],
	[1440, 900],
	[1920, 1080]
];

let reachable = false;
let scratch = false;
let browser: Browser | null = null;

const state = (body: unknown) =>
	fetch(`${BASE}/api/gauntlet/state`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body)
	});

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	// Only on the disposable server: its marker says isolated and without hardware. Any
	// other server is left alone, not asked to pretend.
	const marker = await fetch(`${BASE}/api/gauntlet`)
		.then((r) => (r.ok ? r.json() : null))
		.catch(() => null);
	if (marker?.marker !== 'openkerf-gauntlet-v1' || marker.isolated !== true || marker.hardware !== false)
		return;
	// The call returns once our line has raised the warning, or says it did not settle.
	const raised = await state({ second_client: true });
	scratch = raised.ok && Boolean((await raised.json())?.settled);
	if (scratch) browser = await chromium.launch();
});

after(async () => {
	await browser?.close();
	if (scratch) await state({ second_client: false });
});

for (const [width, height] of SIZES) {
	test(`the band hides nothing at ${width} x ${height}`, async (t) => {
		if (!reachable) return noServer(t, BASE);
		if (!scratch || !browser) return t.skip(`no scratch server with an emulated Ruida on ${BASE}`);
		const page = await (await browser.newContext({ viewport: { width, height } })).newPage();
		try {
			await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
			await page.locator('.secondclient').waitFor({ timeout: 20000 });
			await page.locator('.zoom').first().waitFor({ timeout: 20000 });
			await page.waitForTimeout(300);
			const boxes = await page.evaluate(() => {
				const box = (selector: string) => {
					const r = document.querySelector(selector)!.getBoundingClientRect();
					return { top: Math.round(r.top), bottom: Math.round(r.bottom) };
				};
				return {
					band: box('.secondclient'),
					bar: box('.statusbar'),
					main: box('.main'),
					zoom: box('.zoom')
				};
			});
			assert.ok(
				boxes.zoom.bottom <= boxes.band.top,
				`the zoom bar ends at ${boxes.zoom.bottom} px and the band starts at ${boxes.band.top}`
			);
			assert.ok(
				boxes.main.bottom <= boxes.band.top,
				`the work area runs to ${boxes.main.bottom} px, under the band at ${boxes.band.top}`
			);
			assert.ok(
				boxes.band.bottom <= boxes.bar.top,
				`the band runs to ${boxes.band.bottom} px, over the status bar at ${boxes.bar.top}`
			);
		} finally {
			await page.context().close();
		}
	});
}
