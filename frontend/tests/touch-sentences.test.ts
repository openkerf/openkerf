/**
 * A sentence that lives in a `title` has a route on a screen that cannot hover.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8126 node --test frontend/tests/touch-sentences.test.ts
 *
 * The source checks run without one; the browser part skips itself when nothing is
 * listening (`OK_REQUIRE_SERVER=1` turns that into a failure). Nothing is started and
 * nothing moves: the panel is read as it opens, with the selection made through the
 * `?select=` parameter the app carries in its own URL.
 *
 * Why it exists. `screen.noHover` was added to this branch with the rule that a
 * sentence a finger cannot reach has to be on the screen instead, and three sentences
 * were left on the other side of it. Measured at 1024 x 900 on the same seed, on this
 * build against untouched main:
 *
 *   - the drag hint ("Drag the box to move, the corners to scale. Arrow keys: 0.1 mm,
 *     with shift 1 mm.") — on screen on main, nowhere here, and it is the only place
 *     in the interface that names the nudge distances;
 *   - "Off: the work burns at the coordinates you drew it on." — on screen on main,
 *     a title here;
 *   - "Off. The work burns where you drew it. …" — on screen on main, a title here.
 *
 * Room was not the reason: with the drag hint gone the Edit card left 92.4 px of empty
 * panel under it at 1024 and 259.7 px at 1440.
 *
 * What is pinned: at 1024 each of the three stands on the screen, and at 1440 each of
 * them is a title and not a paragraph — the density the repairs won on the desk is not
 * given back to buy the touch screen its sentence.
 *
 * The fourth sentence of the same break, `job.keysHere`, only shows while a job is
 * running, which is the one state this app may not be put into to measure something.
 * It is read out of the source instead, the way `job-quiet.test.ts` reads the states it
 * cannot stage.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';
const here = dirname(fileURLToPath(import.meta.url));
const components = join(here, '..', 'src', 'lib', 'components');

/** A component with its comments taken out: a rule may not be proved by a comment. */
const code = (file: string) =>
	readFileSync(join(components, file), 'utf8')
		.replace(/<!--[\s\S]*?-->/g, '')
		.replace(/\/\*[\s\S]*?\*\//g, '');

const DRAG = 'Drag the box to move';
const ORIGIN = 'the work burns at the coordinates';
const PRINTCUT = 'The work burns where you drew it';

let reachable = false;
let browser: Browser | null = null;

/**
 * A rectangle of this file's own, laid beside whatever is on the bed.
 *
 * Made per measurement and not once: these files run side by side, and one that clears
 * the project takes another file's shape with it. Nothing is cleared here for the same
 * reason.
 */
async function aRectangle() {
	const made = await (
		await fetch(`${BASE}/api/design/elements`, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ type: 'rect', x_mm: 20, y_mm: 20, width_mm: 40, height_mm: 25 })
		})
	).json();
	const id = made?.ids?.[0];
	assert.ok(id, 'the rectangle to read the Edit card around was not made');
	return id as string;
}

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

/** What the Edit card and the two "where does the work go" cards say at one width. */
async function atWidth(width: number) {
	const id = await aRectangle();
	const context = await browser!.newContext({ viewport: { width, height: 900 } });
	const page = await context.newPage();
	try {
		await page.goto(`${BASE}/?tab=design&select=${encodeURIComponent(id)}`, {
			waitUntil: 'domcontentloaded'
		});
		await page.waitForSelector('.selected', { timeout: 20000 });
		await page.waitForTimeout(600);
		const edit = await page.evaluate(() => {
			const card = document.querySelector('.selected') as HTMLElement | null;
			return {
				visible: card ? card.innerText.replace(/\s+/g, ' ') : '',
				titles: [...(card?.querySelectorAll('[title]') ?? [])].map(
					(node) => node.getAttribute('title') ?? ''
				)
			};
		});
		await page.click('.panel .tab:has-text("Job")');
		await page.waitForSelector('.origin p.hint[title]', { timeout: 20000 });
		await page.waitForTimeout(500);
		const off = await page.evaluate(() =>
			[...document.querySelectorAll('.origin')].map((block) => ({
				visible: (block as HTMLElement).innerText.replace(/\s+/g, ' '),
				sentence: block.querySelector('p.hint[title]')?.getAttribute('title') ?? null
			}))
		);
		return { edit, off };
	} finally {
		await context.close();
	}
}

test('at 1024 the three sentences stand on the screen', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const { edit, off } = await atWidth(1024);
	assert.ok(
		edit.visible.includes(DRAG),
		`the drag hint is nowhere at 1024; the card reads: ${edit.visible}`
	);
	for (const needle of [ORIGIN, PRINTCUT]) {
		assert.ok(
			off.some((block) => block.visible.includes(needle)),
			`"${needle}" is nowhere at 1024; the cards read: ${off.map((b) => b.visible).join(' | ')}`
		);
	}
});

test('at 1440 the same three sentences are a title and not a paragraph', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const { edit, off } = await atWidth(1440);
	assert.ok(!edit.visible.includes(DRAG), 'the drag hint is a paragraph again at 1440');
	assert.ok(
		edit.titles.some((title) => title.startsWith(DRAG)),
		`the drag hint is not a title either: ${JSON.stringify(edit.titles)}`
	);
	for (const needle of [ORIGIN, PRINTCUT]) {
		assert.ok(
			!off.some((block) => block.visible.includes(needle)),
			`"${needle}" is a paragraph again at 1440`
		);
		assert.ok(
			off.some((block) => (block.sentence ?? '').includes(needle)),
			`"${needle}" is not a title either at 1440`
		);
	}
});

test('the sentence about the keys is rendered, not only glued to three tooltips', () => {
	const source = code('JobControls.svelte');
	// Three tooltips carry it as their second line, on stop, pause and resume.
	const glued = (source.match(/\\n\$\{t\('job\.keysHere'\)\}/g) ?? []).length;
	assert.equal(glued, 3, `job.keysHere is the second line of ${glued} tooltips, not three`);
	// And once outside a tooltip: a line of its own in the running block.
	const rendered = (source.match(/>\{t\('job\.keysHere'\)\}</g) ?? []).length;
	assert.equal(rendered, 1, `job.keysHere is rendered ${rendered}× — it exists only as a tooltip`);
	assert.ok(
		/screen\.noHover[\s\S]{0,200}job\.keysHere/.test(source),
		'the rendered line is not tied to `screen.noHover`'
	);
});
