/**
 * The buttons in the right-hand panel are one button, measured.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8126 node --test frontend/tests/panel-buttons.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing is pressed: the panel is measured as it opens on each tab.
 *
 * Why it exists. `one-button.test.ts` reads the stylesheets; this reads the screen,
 * because the fault was visible before it was findable in a file. Measured at 1440 on
 * the untouched build, over the three tabs of the panel: nine heights between 15.9 and
 * 44 px for buttons that do the same kind of thing, and five of them in IBM Plex Mono —
 * *Unlock*, *Put everything on the bed*, *Earlier*, *Later*, *Cancel* — where the
 * typography table keeps mono for values. *Show cut path* (29.9 px, 11 px, weight 400)
 * and *Show frame* (36.8, 13, 500) stood in one card as sibling verbs.
 *
 * What is measured: every button in the panel that draws a face — a border you can see —
 * carries the shared `btn` class, stands at one of its three heights (32 mini, 36.8
 * base, 44 the one that starts a burn, and 44 for everything under a coarse pointer),
 * and is set in the interface face, not in mono.
 *
 * Three are left out and each says why in the code below: the buttons inside a number
 * field's stepper or a segmented switch, which are parts of a field and not verbs, and the jog
 * pad's Home, which deliberately spans both rows of that pad.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';
/** mini, base, and the button that starts a burn. */
const HEIGHTS = [32, 36.8, 44];

let reachable = false;
let browser: Browser | null = null;

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/** Three layers, three shapes on the bed and one off it, and one of them locked — so the
    layer list, the pre-flight, the stray card and the locked note are all on screen. */
async function aDesign() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	const layers = [
		{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65 },
		{ type: 'engrave', label: 'Caption', speed: 250, power_percent: 22 },
		{ type: 'raster', label: 'Logo area', speed: 300, power_percent: 30 }
	];
	for (const layer of layers) await post('/api/design/operations', layer);
	for (let i = 0; i < 3; i++)
		await post('/api/design/elements', {
			type: 'rect',
			x_mm: 20 + i * 40,
			y_mm: 20,
			width_mm: 30,
			height_mm: 30
		});
	await post('/api/design/elements', {
		type: 'rect',
		x_mm: 4000,
		y_mm: 20,
		width_mm: 30,
		height_mm: 30
	});
	const design = await (await fetch(`${BASE}/api/design`)).json();
	const ops = design.operations.filter((o: { grid?: unknown }) => !o.grid);
	const elements = design.elements as { id: string }[];
	for (let i = 0; i < Math.min(ops.length, elements.length); i++)
		await post('/api/design/assign', { ids: [elements[i].id], operation_id: ops[i].id });
	await post('/api/design/lock', { ids: [elements[1].id], locked: true });
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	return elements.map((element) => element.id);
}

let ids: string[] = [];

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	browser = await chromium.launch();
	ids = await aDesign();
});

after(async () => {
	await browser?.close();
});

type Face = { cls: string; text: string; height: number; mono: boolean; btn: boolean };

const facedButtons = () => {
	const panel = document.querySelector('.panel');
	if (!panel) return [] as Face[];
	return [...panel.querySelectorAll('button')]
		.filter((node) => {
			const style = getComputedStyle(node);
			// A face: a border you can see. A button drawn as a link (Clear, the
			// section headings) is a different thing and is not held to this.
			if (style.borderTopStyle === 'none' || parseFloat(style.borderTopWidth) === 0)
				return false;
			// A stepper inside a number field and a segment of a switch are parts of a
			// field, not verbs; they have their own shapes and their own tests.
			if (node.closest('.stepper, .segmented, .tabs')) return false;
			// Home spans both rows of the jog pad on purpose.
			if (node.classList.contains('home')) return false;
			// A button that is only an icon — the ratio chain between width and height,
			// the burn-along switch in a layer row — is sized to the row it sits in, not
			// to the scale of the buttons that carry a word.
			if (!(node.textContent ?? '').trim()) return false;
			return true;
		})
		.map((node) => {
			const style = getComputedStyle(node);
			return {
				cls: node.className.toString(),
				text: (node.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 30),
				height: Math.round(node.getBoundingClientRect().height * 10) / 10,
				mono: /Mono/i.test(style.fontFamily),
				btn: node.classList.contains('btn')
			};
		});
};

for (const tab of ['design', 'layers', 'job']) {
	test(`every button with a face on the ${tab} tab is the shared button`, async (t) => {
		if (!reachable || !browser) return noServer(t, BASE);
		const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
		const page = await context.newPage();
		try {
			const select = tab === 'design' ? `&select=${ids[1]}` : '';
			await page.goto(`${BASE}/?tab=${tab}${select}`, { waitUntil: 'domcontentloaded' });
			await page.waitForSelector('.panel', { timeout: 20000 });
			await page.waitForFunction(() => document.fonts?.status === 'loaded', null, {
				timeout: 20000
			});
			// The estimate and the layer list land after the page; wait for the answer,
			// not for a guess about how long it takes.
			await page.waitForTimeout(4000);
			const buttons: Face[] = await page.evaluate(facedButtons);
			assert.ok(buttons.length > 0, `no button with a face on the ${tab} tab`);
			const notShared = buttons.filter((b) => !b.btn).map((b) => `${b.cls}: "${b.text}"`);
			assert.deepEqual(notShared, [], `buttons that are not the shared .btn: ${notShared.join(' | ')}`);
			const inMono = buttons.filter((b) => b.mono).map((b) => `"${b.text}"`);
			assert.deepEqual(inMono, [], `verbs set in mono: ${inMono.join(', ')}`);
			const odd = buttons
				.filter((b) => !HEIGHTS.some((h) => Math.abs(h - b.height) < 0.6))
				.map((b) => `"${b.text}" ${b.height} px`);
			assert.deepEqual(odd, [], `heights outside the three: ${odd.join(' | ')}`);
		} finally {
			await context.close();
		}
	});
}
