/**
 * What the repair has to prove, measured in the running app.
 *
 *   OK_BASE=http://localhost:5199 node gauntlet/preview-check.mjs
 *
 * One-off: it belongs to the repair of the cut-path window (numbers that stacked,
 * a scrubber that could not reach the end, a false claim about the connection, a
 * dialog under the toast stack, focus that walked out). Everything it prints is a
 * number, not an opinion.
 */
import { browser, open, BASE } from './harness.mjs';

const b = await browser();
const page = await open(b, { width: 1440, theme: 'light' });

// ------------------------------------------------------------------ the flash
await page.click('body', { position: { x: 700, y: 400 } }).catch(() => {});
await page.evaluate(() => {
	window.__seen = [];
	const start = performance.now();
	window.__timer = setInterval(() => {
		const dialog = document.querySelector('[role="dialog"]');
		const text = dialog?.textContent ?? '';
		window.__seen.push({
			t: +(performance.now() - start).toFixed(1),
			open: !!dialog,
			away: text.includes('server is away') || text.includes('server weg'),
			building: text.includes('Working out the path'),
			ready: !!dialog?.querySelector('svg')
		});
	}, 5);
});
await page.keyboard.press('Alt+p');
await page.waitForTimeout(1500);
const flash = await page.evaluate(() => {
	clearInterval(window.__timer);
	const seen = window.__seen;
	return {
		samples: seen.length,
		away: seen.filter((s) => s.away).map((s) => s.t),
		firstOpen: seen.find((s) => s.open)?.t ?? null,
		building: seen.filter((s) => s.building).length,
		firstReady: seen.find((s) => s.ready)?.t ?? null
	};
});
console.log('flash:', JSON.stringify(flash));

await page.waitForSelector('[role="dialog"] svg', { timeout: 30000 });
await page.waitForTimeout(600);

// ------------------------------------------------------------------ the numbers
const numbers = await page.$$eval('[role="dialog"] text.order', (nodes) =>
	nodes.map((n) => {
		const r = n.getBoundingClientRect();
		return { t: n.textContent, x: +r.x.toFixed(1), y: +r.y.toFixed(1), w: +r.width.toFixed(1), h: +r.height.toFixed(1) };
	})
);
let pairs = 0;
let overlapping = 0;
let worst = 0;
for (let i = 0; i < numbers.length; i++)
	for (let j = i + 1; j < numbers.length; j++) {
		pairs++;
		const a = numbers[i];
		const c = numbers[j];
		const ox = Math.min(a.x + a.w, c.x + c.w) - Math.max(a.x, c.x);
		const oy = Math.min(a.y + a.h, c.y + c.h) - Math.max(a.y, c.y);
		if (ox > 0 && oy > 0) {
			overlapping++;
			worst = Math.max(worst, (ox * oy) / Math.min(a.w * a.h, c.w * c.h));
		}
	}
console.log(`numbers: ${numbers.length} drawn, ${overlapping} of ${pairs} pairs overlap, worst fraction ${worst.toFixed(2)}`);
console.log('labels:', numbers.map((n) => n.t).join(' '));

// -------------------------------------------------------- the order in words
const listed = await page.$$eval('[role="dialog"] .order-list li', (n) => n.map((x) => x.textContent.trim()));
console.log(`order list: ${listed.length} lines; first: ${listed[0] ?? '—'}`);
console.log(`            last: ${listed[listed.length - 1] ?? '—'}`);

// -------------------------------------------------------------- the scrubber
const range = await page.$('[role="dialog"] input[type=range]');
const box = await range.boundingBox();
const attrs = await range.evaluate((n) => ({
	min: n.min, max: n.max, step: n.step, valuetext: n.getAttribute('aria-valuetext'), live: !!document.querySelector('[role="dialog"] [aria-live]')
}));
console.log('range:', JSON.stringify(attrs));
await page.mouse.move(box.x + 2, box.y + box.height / 2);
await page.mouse.down();
await page.mouse.move(box.x + box.width + 60, box.y + box.height / 2, { steps: 6 });
await page.mouse.up();
const atEnd = await page.evaluate(() => ({
	value: document.querySelector('[role="dialog"] input[type=range]').value,
	clock: document.querySelector('[role="dialog"] .clock').textContent.trim()
}));
console.log('dragged fully right:', JSON.stringify(atEnd));

// One press of Play at the end has to restart the replay, not do nothing.
await page.click('[role="dialog"] .transport .btn');
const played = [];
for (const wait of [300, 600, 900]) {
	await page.waitForTimeout(wait === 300 ? 300 : 300);
	played.push(
		await page.evaluate(() => ({
			clock: document.querySelector('[role="dialog"] .clock').textContent.trim(),
			label: document.querySelector('[role="dialog"] .transport .btn').textContent.trim()
		}))
	);
}
console.log('play at the end:', JSON.stringify(played));

// Keyboard grain: one ArrowRight has to move something you can read.
await page.evaluate(() => {
	const r = document.querySelector('[role="dialog"] input[type=range]');
	r.focus();
});
await page.keyboard.press('Home');
const before = await page.evaluate(() => document.querySelector('[role="dialog"] .clock').textContent.trim());
await page.keyboard.press('ArrowRight');
const afterArrow = await page.evaluate(() => ({
	clock: document.querySelector('[role="dialog"] .clock').textContent.trim(),
	valuetext: document.querySelector('[role="dialog"] input[type=range]').getAttribute('aria-valuetext')
}));
await page.keyboard.press('End');
const afterEnd = await page.evaluate(() => document.querySelector('[role="dialog"] .clock').textContent.trim());
console.log(`keyboard: Home ${before} -> ArrowRight ${afterArrow.clock} (valuetext ${afterArrow.valuetext}) -> End ${afterEnd}`);

// ------------------------------------------------------------ the toast stack
const stacking = await page.evaluate(() => {
	const dialog = document.querySelector('[role="dialog"]');
	const backdrop = dialog.parentElement;
	const cards = [...document.querySelectorAll('.dropped, .notice, .alarm')].map((n) => ({
		cls: String(n.className).split(' ')[0],
		text: n.innerText.replace(/\n/g, ' | ').slice(0, 90),
		z: getComputedStyle(n).zIndex,
		box: (({ x, y, width, height }) => ({ x: +x.toFixed(0), y: +y.toFixed(0), w: +width.toFixed(0), h: +height.toFixed(0) }))(n.getBoundingClientRect())
	}));
	const svg = dialog.querySelector('svg').getBoundingClientRect();
	const onTop = document.elementFromPoint(svg.x + 40, svg.y + 20);
	return {
		backdropZ: getComputedStyle(backdrop).zIndex,
		cards,
		overDrawing: onTop ? `${onTop.tagName.toLowerCase()}.${String(onTop.className?.baseVal ?? onTop.className ?? '').slice(0, 30)}` : null,
		insideDialog: dialog.contains(onTop)
	};
});
console.log('stacking:', JSON.stringify(stacking));

// ---------------------------------------------------------------- focus trap
const stops = [];
for (let i = 0; i < 12; i++) {
	await page.keyboard.press('Tab');
	stops.push(
		await page.evaluate(() => {
			const a = document.activeElement;
			return {
				what: `${a.tagName.toLowerCase()}${a.getAttribute('aria-label') ? `[${a.getAttribute('aria-label')}]` : ''}${a.textContent ? ':' + a.textContent.trim().slice(0, 18) : ''}`,
				inside: !!document.querySelector('[role="dialog"]')?.contains(a)
			};
		})
	);
}
console.log('tab stops inside the dialog:', stops.filter((s) => s.inside).length, 'of', stops.length);
for (const s of stops) console.log('   ', s.inside ? 'in ' : 'OUT', s.what);

await page.keyboard.press('Escape');
await page.waitForTimeout(200);
const afterEscape = await page.evaluate(() => {
	const a = document.activeElement;
	return { tag: a.tagName, cls: String(a.className ?? '').slice(0, 40), dialog: !!document.querySelector('[role="dialog"]') };
});
console.log('after Escape:', JSON.stringify(afterEscape));

// ------------------------------------------------- alt+P on an empty bed
await fetch(BASE + '/api/project/new', { method: 'POST' }).catch(() => {});
// Without this the reload recovers the autosave and the bed is not empty at all —
// which is what made this measurement lie the first time.
await fetch(BASE + '/api/design/autosave', { method: 'DELETE' }).catch(() => {});
await page.reload({ waitUntil: 'domcontentloaded' });
await page.waitForTimeout(1200);
await page.click('body', { position: { x: 700, y: 400 } }).catch(() => {});
await page.keyboard.press('Alt+p');
await page.waitForTimeout(800);
const empty = await page.evaluate(() => {
	const row = [...document.querySelectorAll('[role="menuitem"], button')].find((n) =>
		n.textContent.includes('Show cut path')
	);
	return { dialog: !!document.querySelector('[role="dialog"]'), row: row?.textContent?.trim() ?? null };
});
console.log('alt+P on an empty bed opens a window:', JSON.stringify(empty));

console.log('console errors:', page.problems.length ? page.problems : 'none');
await b.close();
