/**
 * The living hinge in the Generators window.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8181 node --test frontend/tests/hinge.test.ts
 *
 * This test shares one running engine with the other e2e tests, so running more than one
 * file at a time goes wrong: use `--test-concurrency=1`. Without a reachable server it
 * skips itself.
 *
 * Why it exists: a slit field is the one generator whose result you cannot check by
 * looking. A hundred and twenty short lines look like a hinge whether the rows stagger or
 * not, whether the bridges are 3 mm or 0.2 mm, and whether the outermost slit stops at the
 * edge or runs on through the workpiece. So what is measured here is what the window
 * *says* about the field beside what it draws: the count, the sentence about the bridge,
 * and the warning when the bridge is thinner than the cut itself.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8181';

let reachable = false;
let browser: Browser | null = null;
let page: Page;

const post = (path: string, body: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body)
	});

/** Open the Generators window on the living hinge tab. */
async function openHinge() {
	await page.getByTitle(/Generators/).first().click();
	// Exact: the rail's own tooltip names the hinge too ("Generators — repeats,
	// boxes, codes and a living hinge"), so a loose match finds two buttons.
	await page.getByRole('button', { name: 'Living hinge', exact: true }).click();
	await page.waitForTimeout(600);
}

const caption = () =>
	page.evaluate(() =>
		[...document.querySelectorAll('figcaption')].map((n) => (n.textContent ?? '').trim())
	);

const field = (name: string) => page.getByLabel(name);

async function set(name: string, value: string) {
	await field(name).fill(value);
	await page.waitForTimeout(600);
}

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) })
		.then((r) => r.ok)
		.catch(() => false);
	if (!reachable) return;
	const machines: { configured?: boolean }[] = await (await fetch(`${BASE}/api/machines`)).json();
	if (!machines.some((m) => m.configured)) {
		await post('/api/machines', { info: 'ruida-beta', label: 'Hinge test bench' });
	}
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });

	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);
});

after(async () => {
	await browser?.close();
});

test('the window says how many slits it will cut, and how wide the bridge is', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await openHinge();

	// The defaults: 60 x 40 mm, slits of 8 mm with 3 mm between them, rows 2 mm apart.
	const lines = await caption();
	assert.ok(
		lines.some((line) => line.includes('120 slits in 20 rows')),
		`the caption says ${JSON.stringify(lines)}`
	);
	assert.ok(
		lines.some((line) => line.includes('60.0 × 38.0 mm')),
		`the size line says ${JSON.stringify(lines)}`
	);

	// Beside the fields, where the eye is while you type the number.
	const beside = await page.evaluate(
		() => document.querySelector('.formulier .bridgeline')?.textContent ?? ''
	);
	assert.match(beside, /3\.0 mm of material stays behind, and between two rows 2\.0 mm/);
	assert.match(beside, /twists, and what breaks/);
});

test('the pattern changes the field, not just the label', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await page.getByRole('radio', { name: 'Wavy slits' }).click();
	await page.waitForTimeout(700);

	const lines = await caption();
	// A wave sticks out above and below its row, so one row of the twenty gives way.
	assert.ok(
		lines.some((line) => line.includes('114 slits in 19 rows')),
		`the caption says ${JSON.stringify(lines)}`
	);
	const d = await page.evaluate(
		() => document.querySelector('.proef svg path.shape')?.getAttribute('d') ?? ''
	);
	assert.ok(d.includes('Q'), 'the wavy field is drawn without a single curve');

	await page.getByRole('radio', { name: 'Straight slits' }).click();
	await page.waitForTimeout(700);
	const straight = await page.evaluate(
		() => document.querySelector('.proef svg path.shape')?.getAttribute('d') ?? ''
	);
	assert.ok(!straight.includes('Q'), 'the straight field has curves in it');
});

test('a bridge thinner than the cut itself is said out loud, under the drawing', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await set('Gap in a row (mm)', '0.2');

	const lines = await caption();
	assert.ok(
		lines.some((line) => line.includes('burn away')),
		`no warning; the captions say ${JSON.stringify(lines)}`
	);
	await set('Gap in a row (mm)', '3');
	assert.ok(
		!(await caption()).some((line) => line.includes('burn away')),
		'the warning stayed after the reason for it was gone'
	);
});

test('a slit as long as the area is wide is refused where you are looking', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await set('Slit length (mm)', '60');

	const said = await page.evaluate(
		() => document.querySelector('.proef .unfinished')?.textContent ?? ''
	);
	assert.match(said, /cuts the piece in two/);
	// And the last valid drawing stays: dropping a hole in the window teaches nothing.
	assert.ok(await page.$('.proef svg path.shape'), 'the drawing jumped away');
	await set('Slit length (mm)', '8');
});

test('every field is reachable with the keyboard', async (t) => {
	if (!reachable) return noServer(t, BASE);
	// The steppers are deliberately out of the tab order (see NumberField); what has to be
	// reachable is the seven fields and the checkbox.
	const wanted = [
		'Slit length (mm)',
		'Gap in a row (mm)',
		'Between rows (mm)',
		'Left (mm)',
		'Top (mm)',
		'Width (mm)',
		'Height (mm)'
	];
	const reached: string[] = [];
	await field('Slit length (mm)').focus();
	for (let step = 0; step < 40 && reached.length < wanted.length; step++) {
		const name = await page.evaluate(() => {
			const active = document.activeElement as HTMLElement | null;
			if (!active || active.tagName !== 'INPUT') return '';
			const label = active.id ? document.querySelector(`label[for="${active.id}"]`) : null;
			return (label?.textContent ?? '').replace(/\s+/g, ' ').trim();
		});
		if (name && wanted.includes(name) && !reached.includes(name)) reached.push(name);
		await page.keyboard.press('Tab');
	}
	assert.deepEqual(reached, wanted);
});

test('the field lands on the bed as one shape in a cut layer', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await page.getByRole('button', { name: /^Make the hinge/ }).click();
	await page.waitForTimeout(1500);

	const design = await (await fetch(`${BASE}/api/design`)).json();
	assert.equal(design.elements.length, 1, 'the hinge did not land as one shape');
	const element = design.elements[0];
	assert.equal(element.label, 'Living hinge — straight slits');
	assert.equal(element.path.split('M').length - 1, 120, 'not 120 slits on the bed');
	const layers = design.operations.filter((o: { element_ids: string[] }) => o.element_ids.length);
	assert.deepEqual(
		layers.map((o: { label: string }) => o.label),
		['Cut']
	);

	// And the canvas draws it: one element, selectable as one thing.
	const drawn = await page.evaluate(
		() => document.querySelectorAll('.bed [data-el]').length
	);
	assert.equal(drawn, 1, `the bed shows ${drawn} shapes`);
});

test('the area can be the selected shape', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });
	await post('/api/design/elements', {
		type: 'rect',
		x_mm: 30,
		y_mm: 20,
		width_mm: 50,
		height_mm: 24
	});
	await page.waitForTimeout(1200);
	await page.keyboard.press('Meta+a');
	await page.waitForTimeout(800);

	await openHinge();
	const check = page.getByRole('checkbox', { name: /Fill the area of the selected shape/ });
	assert.equal(await check.isDisabled(), false, 'the checkbox stayed off with a selection');
	await check.check();
	await page.waitForTimeout(800);

	// The rectangle is 50 x 24 mm, so twelve rows of 2 mm and slits inside its own box.
	const lines = await caption();
	assert.ok(
		lines.some((line) => line.includes('in 12 rows')),
		`the caption says ${JSON.stringify(lines)}`
	);
	// The four area fields are gone, and the preview does not complain about them either.
	assert.equal(await field('Width (mm)').count(), 0, 'the area fields stayed on screen');
	assert.equal(
		await page.evaluate(
			() => document.querySelector('.proef .unfinished')?.textContent ?? ''
		),
		'',
		'a field nobody can see held the preview back'
	);
});
