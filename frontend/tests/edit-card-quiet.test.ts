/**
 * The Edit card says a thing once, and only where it is true.
 *
 * Running against a live server:
 *   OK_BASE=http://127.0.0.1:8121 node --test frontend/tests/edit-card-quiet.test.ts
 *
 * Skips itself without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a
 * failure). Nothing is pressed and nothing is started: the card is measured as it
 * stands, with the selection made through the `?select=` parameter the app already
 * carries in its own URL.
 *
 * Why it exists. Measured at 1440 x 900 on the seeded design, before the repair:
 * a single rectangle got a 292 px card with 64 px of prose in it; the same card
 * around a typed caption 425 px with 147 px in four paragraphs, and around a
 * generated QR 368 px with 128 px. Three of those paragraphs said something that
 * was either untrue or already on the screen:
 *
 *   - "This shape consists of 18 loose pieces. An export from a CAD program…" sat
 *     under a *typed text* (18 glyph outlines) and under a *generated QR* (232
 *     modules). Neither came out of a CAD program and neither wants splitting.
 *   - the caption was quoted twice, 40 px apart: once in the head as
 *     Text "OpenKerf 5030" and once again below it.
 *   - "Drag the box to move, the corners to scale…" — 17 words — stood in every
 *     selected state at every width, inside the card, where the Layers tab keeps
 *     the same sentence as a title on the rows it is about.
 *
 * And above all of it "Design · 6 elements" headed both the Edit and the Layers
 * tab and headed nothing: it pushed the card that *is* the tab down to y 164.
 *
 * What is measured: the CAD sentence appears for neither a text nor a generated
 * shape *and still appears for an imported path*, the text value is not on screen
 * twice, the drag hint is a title and not a paragraph, and no section heading stands
 * above the selection card.
 *
 * That fourth clause is the one this file did not have and needed. A first repair
 * exempted every shape whose label did not carry the engine's internal id, and an
 * import never carries one: MeerK40t's SVG reader puts the element's own `id` (or its
 * `inkscape:label`) in the label, so both paths below arrive as `Path bracket #000000`
 * and `front panel`. The sentence then appeared essentially never. A file that only
 * asserts absences cannot see that, so both imports are selected here and the sentence
 * has to be there.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser } from 'playwright';
import { noServer } from './no-server.ts';
import {
	nameShowsWholeText,
	elementName,
	madeHere,
	NAME_TEXT_LIMIT
} from '../src/lib/design.svelte.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';

let reachable = false;
let browser: Browser | null = null;
let elements: {
	id: string;
	type: string;
	label: string;
	text: { text: string } | null;
	subpaths: number;
	generated?: boolean;
}[] = [];
let imported: string[] = [];

const post = (path: string, body?: unknown) =>
	fetch(`${BASE}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});

/**
 * The three shapes this file is about, laid down by this file.
 *
 * It used to read whatever happened to be on the bed, and then a test file that
 * ran before it and cleared the design took these four measurements with it. A
 * rectangle (one piece), a typed caption of thirteen characters (many pieces, and
 * short enough for the head to carry whole) and a generated QR (many pieces, a
 * name of its own).
 */
async function aDesign() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await post('/api/project/new');
	await post('/api/design/elements', {
		type: 'rect',
		x_mm: 15,
		y_mm: 15,
		width_mm: 120,
		height_mm: 80
	});
	await post('/api/design/elements', {
		type: 'text',
		x_mm: 20,
		y_mm: 175,
		text: 'OpenKerf 5030',
		height_mm: 10
	});
	await post('/api/design/generate/qrcode', {
		text: 'openkerf',
		size_mm: 34,
		x_mm: 250,
		y_mm: 120
	});
	imported = await importSvg();
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	elements = (await (await fetch(`${BASE}/api/design`)).json()).elements;
}

/**
 * A CAD export as one really arrives.
 *
 * One path, two loose pieces, and an `id` of its own — which is what every
 * Illustrator, Inkscape or Fusion export carries. MeerK40t's SVG reader puts that id
 * in the node's label (`core/svg_io.py`), so the shape lands here as `Path bracket`
 * and *not* as `Path meerk40t:12`. That is the whole reason the panel may not decide
 * this question on the label: an earlier repair exempted every shape whose label did
 * not carry the engine's internal id, and then the one shape the sentence exists for
 * was the one shape that never got it.
 */
async function importSvg(): Promise<string[]> {
	const svg =
		'<svg xmlns="http://www.w3.org/2000/svg" ' +
		'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" ' +
		'width="60mm" height="40mm" viewBox="0 0 60 40">' +
		'<path id="bracket" fill="none" stroke="#000000" ' +
		'd="M 4 4 L 26 4 L 26 20 L 4 20 Z M 34 4 L 56 4 L 56 20 L 34 20 Z"/>' +
		'<path id="path1234" inkscape:label="front panel" fill="none" stroke="#000000" ' +
		'd="M 4 24 L 26 24 L 26 36 L 4 36 Z M 34 24 L 56 24 L 56 36 L 34 36 Z"/>' +
		'</svg>';
	const form = new FormData();
	form.append('file', new Blob([svg], { type: 'image/svg+xml' }), 'bracket.svg');
	const response = await fetch(`${BASE}/api/job/load`, { method: 'POST', body: form });
	if (!response.ok) return [];
	return (await response.json()).added ?? [];
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

/** The card as it stands around one selection, with nothing pressed. */
async function card(ids: string[], tab = 'design') {
	const context = await browser!.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();
	try {
		await page.goto(`${BASE}/?tab=${tab}&select=${ids.join(',')}`, {
			waitUntil: 'domcontentloaded'
		});
		await page.waitForSelector('.panel-scroll', { timeout: 20000 });
		if (tab === 'design') await page.waitForSelector('.selected', { timeout: 20000 });
		await page.waitForFunction(() => document.fonts?.status === 'loaded', null, { timeout: 20000 });
		await page.waitForTimeout(400);
		return await page.evaluate(() => {
			const selected = document.querySelector('.selected');
			const box = selected?.getBoundingClientRect();
			const paragraphs = [...(selected?.querySelectorAll('p') ?? [])]
				.map((node) => (node.textContent ?? '').replace(/\s+/g, ' ').trim())
				.filter(Boolean);
			return {
				height: box ? Math.round(box.height) : null,
				top: box ? Math.round(box.top) : null,
				text: (selected?.textContent ?? '').replace(/\s+/g, ' ').trim(),
				paragraphs,
				titles: [...(selected?.querySelectorAll('[title]') ?? [])].map(
					(node) => node.getAttribute('title') ?? ''
				),
				headings: [...document.querySelectorAll('.panel-scroll h2')].map((node) =>
					(node.textContent ?? '').trim()
				)
			};
		});
	} finally {
		await context.close();
	}
}

const CAD = 'loose pieces';
const DRAG = 'Drag the box to move';

test('the CAD-export diagnosis stays away from a text and a generated shape', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const text = elements.find((e) => e.text);
	const generated = elements.find((e) => e.label.startsWith('QR'));
	assert.ok(text && generated, 'the seeded design has a text and a QR to look at');

	const onText = await card([text!.id]);
	assert.ok(
		!onText.text.includes(CAD),
		`a typed text of ${text!.subpaths} glyph outlines is offered the CAD-export sentence: ${onText.paragraphs.join(' | ')}`
	);
	const onQr = await card([generated!.id]);
	assert.ok(
		!onQr.text.includes(CAD),
		`a generated QR of ${generated!.subpaths} modules is offered the CAD-export sentence: ${onQr.paragraphs.join(' | ')}`
	);
});

test('a caption the head shows in full is not quoted a second time', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const text = elements.find((e) => e.text)!;
	const value = text.text!.text;
	assert.ok(value.length <= 22, 'this caption fits in the head, so the head shows all of it');
	const shown = await card([text.id]);
	const times = shown.text.split(value).length - 1;
	assert.equal(times, 1, `"${value}" stands ${times}× in the card`);
});

test('the drag hint is a title on the size grid, not a paragraph in the card', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const shape = elements.find((e) => e.type === 'elem rect')!;
	const shown = await card([shape.id]);
	assert.ok(
		!shown.paragraphs.some((p) => p.startsWith(DRAG)),
		`the drag hint is still a paragraph: ${shown.paragraphs.join(' | ')}`
	);
	assert.ok(
		shown.titles.some((title) => title.startsWith(DRAG)),
		`the drag hint is nowhere: titles are ${JSON.stringify(shown.titles)}`
	);
});

test('no heading stands above the card on the Edit and the Layers tab', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	const shape = elements.find((e) => e.type === 'elem rect')!;
	const edit = await card([shape.id]);
	assert.ok(
		!edit.headings.includes('Design'),
		`the Edit tab is headed ${JSON.stringify(edit.headings)}`
	);
	assert.ok(
		edit.top !== null && edit.top < 150,
		`the card starts at y ${edit.top}, so something is still above it`
	);
	const layers = await card([shape.id], 'layers');
	assert.ok(
		!layers.headings.includes('Design'),
		`the Layers tab is headed ${JSON.stringify(layers.headings)}`
	);
});

test('an imported path of several pieces still gets the diagnosis', async (t) => {
	if (!reachable || !browser) return noServer(t, BASE);
	assert.equal(imported.length, 2, 'the SVG brought in both its paths');
	for (const id of imported) {
		const path = elements.find((e) => e.id === id);
		assert.ok(path, 'the imported shape is in the snapshot');
		assert.equal(path!.subpaths, 2, `the imported path holds ${path!.subpaths} pieces`);
		assert.equal(
			madeHere(path!),
			false,
			`it is labelled ${JSON.stringify(path!.label)} and counts as made here`
		);
		const shown = await card([path!.id]);
		assert.ok(
			shown.text.includes(CAD),
			`${path!.label} does not get the sentence it exists for: ${shown.paragraphs.join(' | ')}`
		);
	}
});

test('the two readers of the name limit agree about a caption of nothing but spaces', () => {
	// `elementName` renders `Text “”` for it, so the quote below the head would be a
	// second empty pair of quotation marks — the very repetition this pair decides.
	const blank = { type: 'elem text', text: { text: '   ' }, label: 'Text' };
	assert.equal(elementName(blank), 'Text “”');
	assert.equal(nameShowsWholeText(blank), true);
	const long = { type: 'elem text', text: { text: 'x'.repeat(NAME_TEXT_LIMIT + 1) }, label: 'Text' };
	assert.equal(nameShowsWholeText(long), false);
});

test('a shape a generator laid down is known by its mark and by its name', () => {
	// The mark travels with the shape from the moment it is made; the name is what a
	// design saved before the mark existed still carries. Neither is the question
	// "did nobody name it?", which every CAD export answers wrongly.
	assert.equal(madeHere({ generated: true, label: 'Path path1234 #000000' }), true);
	assert.equal(madeHere({ label: 'QR — openkerf' }), true);
	assert.equal(madeHere({ label: 'Living hinge — staggered' }), true);
	assert.equal(madeHere({ label: 'Path bracket' }), false);
	assert.equal(madeHere({ label: 'Path path1234 #000000' }), false);
	assert.equal(madeHere({ label: 'Path meerk40t:12 #0000ff' }), false);
});
