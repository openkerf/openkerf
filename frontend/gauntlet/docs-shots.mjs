/**
 * The screenshot set for the handbook.
 *
 *   node gauntlet/docs-shots.mjs            # everything
 *   node gauntlet/docs-shots.mjs 07         # only the shots whose name contains "07"
 *
 * Same idea as `i-shots.mjs`, different purpose. That one photographs every screen
 * twice to compare two languages; this one photographs each screen once, in
 * English, so the documentation can point at it. Which means the demands are
 * different: a picture in the handbook has to show the *same* thing next month, so
 * every shot states the state it needs and puts it there itself through the API.
 * Nothing here reads what happened to be on the bed.
 *
 * Desktop is 1440×900 in the light theme — the width the usability rounds were
 * measured at, so the layout in the picture is the layout that was designed. The
 * phone is 390×844, the size at which the app switches to its own phone screen
 * (below 768 px).
 *
 * Nothing in here starts the laser. The queue picture (13) would need a real job in
 * a real machine's spooler, and there is no way to fake that in the browser without
 * inventing a machine state — so it is not in the list. The reasoning is written out
 * at the foot of this file.
 */
import { chromium } from 'playwright';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';

const BASE = process.env.OK_BASE ?? 'http://localhost:5199';
// Relative to this script, so it works from `frontend/` and on somebody else's
// machine. It was an absolute path with a home directory in it, which in a public
// repository is both a name nobody needs and a script that only runs here.
const OUT = new URL('../../docs/images', import.meta.url).pathname;
const only = process.argv[2] ?? null;

mkdirSync(OUT, { recursive: true });

// ---------------------------------------------------------------- the API side

async function api(method, path, body) {
	const response = await fetch(BASE + path, {
		method,
		headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	if (!response.ok) {
		console.error('  api', method, path, response.status, (await response.text()).slice(0, 200));
		return null;
	}
	return response.json().catch(() => null);
}

/**
 * The machine the handbook is written around.
 *
 * Every picture has a bed in it and half the prose quotes its size, so which machine
 * is active is part of the state a shot needs — as much as the shapes on the bed.
 * Left to chance it goes wrong quietly: a run made while `lihuiyu-device` happened to
 * be active gave a bed of 310 × 210 mm in every picture, and the tiling shot (a plate
 * of 900 × 280 mm) then overhung the bed in *both* directions, so the app refused to
 * divide it and the picture showed no tiles at all — while the page beside it explains
 * the seam. That is the engine's own fallback biting (CLAUDE.md: the chosen machine is
 * only written at a clean shutdown), not somebody's choice, so the script puts it back.
 */
async function useTheHandbookMachine() {
	const machines = (await api('GET', '/api/machines')) ?? [];
	const wanted = machines.find((m) => m.path === 'ruida');
	if (!wanted || wanted.active) return;
	console.log(`activating ${wanted.label} — the handbook's machine`);
	await api('POST', '/api/machines/ruida/activate');
}

/**
 * An empty bed, one sheet, no recovery file.
 *
 * The recovery file is the reason this exists: leave one behind and the next run
 * opens with a dialog over the screen asking whether to restore it, and every
 * picture after that has a modal in it. That cost the i18n round a set of shots.
 */
async function clear() {
	await fetch(BASE + '/api/design/autosave', { method: 'DELETE' }).catch(() => {});
	// A list attached for the series pictures would still be attached for every
	// picture after them: the names stay on the bed, the Job tab keeps its block
	// about a series nobody started here, and the next person to open the app in
	// this browser inherits somebody else's afternoon. The run goes first because
	// the list may not be taken away while one is going — the app's own refusal,
	// and not something to work around. Both are idempotent, so this costs two
	// requests on a run where no series was ever attached.
	await api('POST', '/api/series/stop');
	await api('DELETE', '/api/series');
	await api('POST', '/api/project/new');
	// The engine starts up with the layer list the previous session left behind, so
	// an empty layer from somebody else's afternoon turns up in the list with "One
	// layer is empty — clear out" above it. Those have nothing to do with this
	// drawing, and the picture is about this drawing.
	await api('POST', '/api/design/operations/prune');
}

/**
 * The drawing the handbook shows.
 *
 * Fixed coordinates and fixed names, because the text points at them: "the
 * rectangle at 15, 15" has to be the rectangle at 15, 15 in every reprint. Four
 * layers with values of their own, so the layer list and the job table have
 * something to show; two rectangles that share a full edge, because "Under the
 * pointer" only appears where there is genuinely more than one shape to choose
 * between.
 */
async function seed() {
	await clear();

	const layers = [
		{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65, passes: 2 },
		{ type: 'engrave', label: 'Caption', speed: 250, power_percent: 22 },
		{ type: 'engrave', label: 'Fine lines', speed: 400, power_percent: 15 },
		{ type: 'raster', label: 'Logo area', speed: 300, power_percent: 30 }
	];
	for (const layer of layers) await api('POST', '/api/design/operations', layer);

	const shapes = [
		{ type: 'rect', x_mm: 15, y_mm: 15, width_mm: 120, height_mm: 80 },
		// Butted right up against the first one, sharing the edge at x = 135 mm.
		// A shape is "under the pointer" where the browser says it is hit, and an
		// unfilled rectangle is only hit along its outline — so two outlines have to
		// meet somewhere for shot 08 to have anything to show. A shared edge 80 mm
		// long is a far more forgiving target than a crossing point.
		{ type: 'rect', x_mm: 135, y_mm: 15, width_mm: 80, height_mm: 80 },
		{ type: 'circle', cx_mm: 280, cy_mm: 55, r_mm: 30 },
		{ type: 'rect', x_mm: 20, y_mm: 120, width_mm: 40, height_mm: 30 },
		{ type: 'rect', x_mm: 80, y_mm: 120, width_mm: 40, height_mm: 30 },
		{ type: 'text', x_mm: 20, y_mm: 190, text: 'OpenKerf 5030', height_mm: 10 }
	];
	for (const shape of shapes) await api('POST', '/api/design/elements', shape);
	await api('POST', '/api/design/generate/qrcode', {
		text: 'openkerf',
		size_mm: 34,
		x_mm: 250,
		y_mm: 130
	});

	const design = await api('GET', '/api/design');
	const elements = design.elements.map((e) => e.id);
	const ops = design.operations.filter((o) => !o.grid).map((o) => o.id);

	// The engine files a new shape under the layer its colour puts it in, so out of
	// every layer first and then into the intended one — otherwise a shape sits in
	// two places and the counts in the layer list do not add up.
	async function put(elementIndex, opIndex) {
		const id = elements[elementIndex];
		if (!id || !ops[opIndex]) return;
		for (const op of ops) await api('POST', '/api/design/unassign', { ids: [id], operation_id: op });
		await api('POST', '/api/design/assign', { ids: [id], operation_id: ops[opIndex] });
	}
	for (const [element, op] of [
		[0, 0],
		[1, 0],
		[2, 0],
		[3, 2],
		[4, 2],
		[5, 1],
		[6, 3]
	]) {
		await put(element, op);
	}
	// One layer that does not burn along: the list has to be able to show that, and
	// the job table has to leave it out.
	if (ops[2]) {
		await fetch(BASE + `/api/design/operations/${encodeURIComponent(ops[2])}`, {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ output: false })
		});
	}
	// Again, and this time it matters most: the engine files new shapes by colour
	// and makes a layer for a colour it has no layer for, so drawing leaves an
	// extra empty one behind. Sweeping only before the drawing left a nameless
	// "Engrave 0" at the foot of the list in every picture of the layer list.
	await api('POST', '/api/design/operations/prune');
	return { elements, ops };
}

// ------------------------------------------------------------ the browser side

await useTheHandbookMachine();

const browser = await chromium.launch();

async function open(path = '/', { width = 1440, height = 900, route = null } = {}) {
	const context = await browser.newContext({
		viewport: { width, height },
		// One device pixel per CSS pixel. At two the pictures are sharper on a HiDPI
		// screen, but the set weighs 8.6 MB, and the rule beside this script says a
		// changed screen earns a new photograph — ten of those rounds put 86 MB of
		// blobs in the history of a repository whose code is a fraction of that. At
		// one it is 2 MB and every word is still legible at the width a page shows
		// them.
		deviceScaleFactor: 1,
		colorScheme: 'light'
	});
	// The language is a stored choice read at boot. Setting it here rather than
	// clicking it means no screen is photographed half-translated.
	await context.addInitScript(() => {
		window.localStorage.setItem('openkerf.language', 'en');
		// The theme is the same kind of stored choice; the handbook is in light.
		window.localStorage.removeItem('openkerf.theme');
	});
	const page = await context.newPage();
	if (route) await route(page);
	const problems = [];
	page.on('console', (m) => m.type() === 'error' && problems.push(m.text().slice(0, 160)));
	page.on('pageerror', (e) => problems.push('pageerror: ' + String(e).slice(0, 160)));
	await page.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 30000 });
	// Not `networkidle`: the status connection stays open for as long as the app
	// runs, so that state never arrives. Wait for the app to have drawn instead.
	await page.waitForSelector('.statusbar, .setup, .card, .phone', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(900);
	// The notification prompt floats over the bottom right when it turns up. It is
	// about this browser profile, not about the app, so it does not belong in the
	// handbook.
	await page.locator('.vraagkaart button').last().click({ timeout: 500 }).catch(() => {});
	page.problems = problems;
	return page;
}

const done = [];

async function shot(name, page, { selector = null, pad = 0, fullPage = false } = {}) {
	// An alarm from the machine, dismissed at the last moment. It outranks every dialog
	// on purpose (the backdrop sits below it), so a real laser that is not answering
	// puts a red card over the top-left of the canvas and over the cut-path drawing —
	// measured on both. It is about this laser at this moment and it is dismissible in
	// the app, so it is dismissed here. Not in `open()`: it arrives with the status
	// stream, a second or two after the page is drawn, so a click there is too early.
	await page.locator('.alarm .seen').first().click({ timeout: 500 }).catch(() => {});
	let clip;
	if (selector) {
		const box = await page.locator(selector).first().boundingBox();
		if (!box) throw new Error(`${name}: nothing at ${selector} to photograph`);
		const view = page.viewportSize();
		const x = Math.max(0, box.x - pad);
		const y = Math.max(0, box.y - pad);
		clip = {
			x,
			y,
			width: Math.min(view.width - x, box.width + 2 * pad),
			height: Math.min(view.height - y, box.height + 2 * pad)
		};
	}
	// `fullPage` is offered but is not what the tall setup step needed: the wizard
	// scrolls *inside* a full-height layout, so the document itself is 900 px and a
	// full-page shot comes back the same size as the window (measured). What works
	// there is a taller window — see shot 04.
	await page.screenshot({ path: join(OUT, name), clip, fullPage: fullPage && !clip });
	done.push(name);
	if (page.problems?.length) console.log('  !', name, page.problems.slice(0, 2));
	console.log('  ✓', name);
}

const wanted = (name) => !only || name.includes(only);

/** Open, photograph, close — the shape almost every shot has. */
async function scene(name, path, options = {}, step = null) {
	if (!wanted(name)) return;
	const page = await open(path, options);
	try {
		if (step) await step(page);
		await page.waitForTimeout(400);
		await shot(name, page, options);
	} finally {
		await page.context().close();
	}
}

// The rail's buttons carry their label in the tooltip; those are the only stable
// handles it has, because the icons are bare paths with no text in them.
const RAIL = '.rail button.tool';
const TOOL = {
	text: `${RAIL}[title="Text"]`,
	generators: `${RAIL}[title^="Generators"]`,
	clipart: `${RAIL}[title^="Search clipart"]`,
	testgrid: `${RAIL}[title="Test grid"]`,
	series: `${RAIL}[title^="Series"]`,
	library: `${RAIL}[title="Material library"]`
};
const DIALOG = '[role="dialog"]';

// ══════════════════════════════════════════════════ 1. the cold start and setup

/**
 * Shot 01 needs the state a first-time user is in: no machine set up yet. On this
 * machine there is one, and deleting it to take a photograph would throw away
 * somebody's real settings. So the machine list is answered from the script for
 * the length of this one page: the app then draws its real welcome screen, the
 * one the layout gate puts up when nothing is configured.
 */
await scene('01-welcome.png', '/', {
	route: async (page) => {
		await page.route('**/api/machines', (r) =>
			r.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify([
					{
						path: 'lhystudios',
						label: 'lihuiyu-device',
						provider: 'provider/device/lhystudios',
						active: true,
						configured: false
					}
				])
			})
		);
	}
});

// The three wizard steps are three routes, each carrying what it needs in the
// address. That is what makes them photographable one by one: no clicking through
// from the step before, so a failure earlier in the chain cannot silently produce
// a picture of the wrong screen.
await scene('02-setup-kind.png', '/setup/kind');
// A typed name rather than the suggestion the step opens with: the picture is
// about the choice, and "ruida" does not read as a choice. Nothing is created —
// that takes the button, and the script does not press it.
await scene('03-setup-name.png', '/setup/name?type=ruida-beta', {}, async (page) => {
	await page.locator('input[type="text"]').first().fill('KH-5030');
	await page.waitForTimeout(300);
});
// The settings step is shown for the machine that is really there. It changes
// nothing until its own save button is pressed, and the script does not press it.
// A taller window than the rest of the set, and the only one: since the fieldset
// about the laser was added this step does not fit in 900 px, and at 900 px the
// picture stopped just under "Tube power" — leaving the answer for a tube whose
// power you do not know, the lens, both tick boxes and both buttons out of a
// picture the page describes in full. `fullPage` cannot fix that: the wizard
// scrolls inside a full-height layout, so the document is exactly one window tall
// and a full-page shot comes back at 1440 × 900 (measured).
await scene(
	'04-setup-settings.png',
	'/setup/settings?machine=ruida',
	{ height: 1250 },
	async (page) => {
		// The two new fields answered rather than left blank, the way shot 03 types a
		// name: the picture is about what you tell the app here, and this laser has
		// never been asked, so it arrives empty. Typing changes nothing — the step
		// writes only when its own button is pressed, and the script does not press it.
		await page.getByLabel(/^Tube power/).fill('80');
		await page.getByLabel(/^Lens/).fill('50.8');
		// And the focus put down again: the field typed into last keeps its focus ring,
		// which in a still picture reads as "this one is special" rather than "this one
		// was typed a moment ago".
		await page.evaluate(() => document.activeElement?.blur());
		await page.waitForTimeout(300);
	}
);

// ═════════════════════════════════════════════════════ 2. the empty work area

if (wanted('05') || wanted('16')) await clear();

await scene('05-canvas-empty.png', '/?tab=design');

/**
 * The test grid wizard fills its preview by itself, a quarter second after the
 * form changes. Picking a material is what turns an empty form into a plan, so
 * that is the one thing this shot does before it looks.
 */
await scene('16-testgrid.png', '/?tab=design', {}, async (page) => {
	await page.locator(TOOL.testgrid).click();
	await page.waitForSelector(DIALOG, { timeout: 10000 });
	// By its label and not "the first select in the window": the first one is the
	// recipe, and picking a recipe leaves the material empty — which is the one
	// thing this window then complains about, in the middle of the picture.
	const material = page.locator(`${DIALOG} label:has(span:text-is("Material")) select`).first();
	const values = await material
		.locator('option')
		.evaluateAll((nodes) => nodes.map((n) => n.value).filter((v) => v && v !== 'null'));
	if (values.length) await material.selectOption(values[0]);
	// The preview is debounced by 250 ms and then has to come back from the server.
	await page.waitForTimeout(2500);
});

// ══════════════════════════════════════════════════════ 3. the drawing on the bed

if (
	['06', '07', '08', '09', '10', '11', '12', '14', '15', '18', '19', '20', '21', '24', '25'].some(
		wanted
	)
) {
	console.log('seeding the drawing…');
	await seed();
}

const design = await api('GET', '/api/design');
const ELEMENTS = (design?.elements ?? []).map((e) => e.id);

await scene('06-canvas-drawn.png', '/?tab=design');

// One shape selected, so the Edit panel has a subject: position, size and the
// layer it is in are all filled instead of showing the empty state.
await scene('07-selection.png', `/?tab=design&select=${ELEMENTS[2] ?? ''}`);

/**
 * The right-click menu only offers "Under the pointer" when two or more shapes lie
 * under that point — one shape is not a choice. The seed puts a small rectangle
 * inside a large one for exactly this, and the click below aims at their overlap.
 * The submenu opens on hover, not on click, so the last step is a mouse move onto
 * the row.
 */
await scene('08-under-pointer.png', '/?tab=design', {}, async (page) => {
	// Where two shapes lie under one point is not something to work out in
	// millimetres and hope the zoom agrees: the app asks the browser which shapes
	// a point hits, so this asks the same question. Walk a coarse grid over the
	// bed and take the first point that hits two.
	const point = await page.evaluate(() => {
		const shapes = [...document.querySelectorAll('[data-el]')].map((node) => ({
			node,
			box: node.getBoundingClientRect()
		}));
		const hits = (x, y) => {
			// The topmost thing at the point has to be a shape itself. A point that only
			// grazes the hit bands beside two shapes counts two, but the right-click
			// lands on the bed and you get the bed's menu — which cost a run.
			if (!document.elementFromPoint(x, y)?.getAttribute?.('data-el')) return 0;
			const ids = new Set();
			for (const node of document.elementsFromPoint(x, y)) {
				const id = node.getAttribute?.('data-el');
				if (id) ids.add(id);
			}
			return ids.size;
		};
		// Only where two shapes' boxes come within a hair of each other is there
		// anything to find, so search there and nowhere else — a pixel-by-pixel sweep
		// of the whole bed is a hundred thousand hit tests for the same answer.
		for (let i = 0; i < shapes.length; i++) {
			for (let j = i + 1; j < shapes.length; j++) {
				const a = shapes[i].box;
				const b = shapes[j].box;
				const left = Math.round(Math.max(a.left, b.left)) - 3;
				const right = Math.round(Math.min(a.right, b.right)) + 3;
				const top = Math.round(Math.max(a.top, b.top)) - 3;
				const bottom = Math.round(Math.min(a.bottom, b.bottom)) + 3;
				if (right < left || bottom < top) continue;
				const found = [];
				for (let y = top; y <= bottom; y++) {
					for (let x = left; x <= right; x++) {
						if (hits(x, y) > 1) found.push({ x, y });
					}
				}
				// The middle of what was found, not the first: the first point sits at the
				// edge of the shared stretch, where the menu would open half off the shape
				// it is about.
				if (found.length) return found[Math.floor(found.length / 2)];
			}
		}
		return null;
	});
	if (!point) throw new Error('08: no point on the bed with two shapes under it');
	await page.mouse.click(point.x, point.y, { button: 'right' });
	await page.waitForSelector('.menu', { timeout: 5000 });
	const row = page.locator('.menu button.row', { hasText: 'Under the pointer' });
	if (!(await row.count())) throw new Error('08: no "Under the pointer" row — nothing overlapping');
	await row.first().hover();
	await page.waitForTimeout(400);
});

await scene('09-layers.png', '/?tab=layers');

// The number chip on a layer row is also its handle: clicking it folds the layer
// open on the speed, power and passes it burns with.
await scene('10-layer-detail.png', '/?tab=layers', {}, async (page) => {
	await page.locator('.layer .chip').first().click();
	await page.waitForTimeout(500);
});

// The colour strip is a band at the foot of the canvas. A full screen makes it a
// stripe you have to be told to look for, so this one is cropped to the strip with
// a little of the bed above it for its bearings.
await scene('11-palette.png', '/?tab=design', { selector: '.palette', pad: 90 });

// The Job tab is the default tab, and with work on the bed it opens on the
// pre-flight: the drawing, the estimated time and the table of what burns with
// which settings. The estimate is computed server-side and takes a moment.
await scene('12-job-preflight.png', '/?tab=job', {}, async (page) => {
	await page.waitForTimeout(3500);
});

await scene('14-library.png', '/?tab=design', {}, async (page) => {
	await page.locator(TOOL.library).click();
	await page.waitForSelector(DIALOG, { timeout: 10000 });
	await page.waitForTimeout(2600);
});

/**
 * A setting with its back story open: where the numbers came from, on which
 * machine, and the photograph of the square they were read off. That is the half
 * of the library that makes it more than a table of numbers, so it is worth its
 * own picture. It lives behind the row's ⋮ menu, under "Provenance and evidence".
 */
await scene('15-library-preset.png', '/?tab=design', {}, async (page) => {
	await page.locator(TOOL.library).click();
	await page.waitForSelector(DIALOG, { timeout: 10000 });
	await page.waitForTimeout(2600);
	// A material with settings behind it. The count on the right of each row in the
	// list says how many; anything with a zero would open on an empty page.
	const rows = page.locator(`${DIALOG} .materials button.matrij`);
	const index = await rows.evaluateAll((nodes) =>
		nodes.findIndex((node, i) => i > 0 && node.querySelector('.mataantal')?.textContent !== '0')
	);
	if (index > 0) await rows.nth(index).click();
	await page.waitForTimeout(800);
	const more = page.locator(`${DIALOG} .preset .meer`).first();
	if (!(await more.count())) throw new Error('15: no settings in the library to open');
	await more.click();
	await page.waitForTimeout(500);
	const provenance = page.locator('button', { hasText: 'Provenance and evidence' }).first();
	if (await provenance.count()) await provenance.click();
	await page.waitForTimeout(900);
});

// With a shape selected, not on an empty selection: the window opens on Repeat,
// and Repeat with nothing chosen is a form with its button greyed out and an
// orange line telling you to go and pick something first.
await scene('18-generators.png', `/?tab=design&select=${ELEMENTS[3] ?? ''}`, {}, async (page) => {
	await page.locator(TOOL.generators).click();
	await page.waitForSelector(DIALOG, { timeout: 10000 });
	await page.waitForTimeout(900);
});

/**
 * Clipart searches public collections, so this shot depends on the network. That
 * is allowed here: without a connection the window says so, and that empty state
 * is worth a picture too — it is what the reader will see on a workshop machine
 * that is offline.
 */
await scene('19-clipart.png', '/?tab=design', {}, async (page) => {
	await page.locator(TOOL.clipart).click();
	await page.waitForSelector(DIALOG, { timeout: 10000 });
	await page.locator(`${DIALOG} .bar input[type="search"]`).fill('star');
	await page.locator(`${DIALOG} .bar button`).first().click();
	await page.waitForTimeout(6000);
});

// The text tool is a mode: pick it, click the bed, and the box asking what it
// should say opens at that point.
await scene('20-text.png', '/?tab=design', {}, async (page) => {
	await page.locator(TOOL.text).click();
	const stage = await page.locator('.stage').boundingBox();
	await page.mouse.click(stage.x + stage.width * 0.55, stage.y + stage.height * 0.62);
	await page.waitForTimeout(900);
	const field = page.locator(`${DIALOG} textarea, ${DIALOG} input[type="text"]`).first();
	if (await field.count()) await field.fill('Made on the 5030');
	await page.waitForTimeout(400);
});

await scene('24-phone.png', '/', { width: 390, height: 844 });

await scene('25-language.png', '/?tab=design', {}, async (page) => {
	await page.locator('.language').first().click();
	await page.waitForTimeout(500);
});

// The sheet tabs are only a row of tabs once there is more than one sheet, so this
// shot makes two extra ones first. Cropped to the strip and the top of the bed:
// full screen, the tabs are a 30-pixel band nobody will find.
if (wanted('21')) {
	await api('POST', '/api/sheets', { name: 'Lid', width_mm: 300, height_mm: 200 });
	await api('POST', '/api/sheets', { name: 'Offcut', width_mm: 180, height_mm: 120 });
	const sheets = await api('GET', '/api/sheets');
	const first = sheets.sheets[0];
	if (first) await api('POST', `/api/sheets/${encodeURIComponent(first.id)}/activate`);
	await scene('21-sheets.png', '/?tab=design', { selector: '.sheets', pad: 120 });
}

// ═══════════════════════════════════════════════════════ 4. states of their own

/**
 * A test board on the bed. Built through the same route the wizard uses, with the
 * numbers written out, so the board in the picture is the same board every time —
 * four speeds down, four powers across.
 *
 * Creating one also files it in the library, the way the wizard does. The record
 * is removed again afterwards: a screenshot run should not leave test boards
 * behind in somebody's library.
 */
if (wanted('17')) {
	await clear();
	const materials = await api('GET', '/api/library/materials');
	const grid = await api('POST', '/api/library/testgrids', {
		operation: 'snijden',
		material_id: materials?.[0]?.id ?? null,
		row_axis: 'speed',
		column_axis: 'power',
		speed_min: 8,
		speed_max: 20,
		speed_steps: 4,
		power_min: 40,
		power_max: 90,
		power_steps: 4,
		cell_mm: 18,
		gap_mm: 4,
		// Not at 20, 20: the caption and the axis figures are drawn *above and to
		// the left of* the squares, so a board anchored in the corner hangs off the
		// bed and the picture fills up with a warning about shapes the head cannot
		// reach.
		origin_x_mm: 60,
		origin_y_mm: 70,
		passes: 1,
		text: true
	});
	await scene('17-testgrid-board.png', '/?tab=design');
	if (grid?.id) await fetch(BASE + `/api/library/testgrids/${grid.id}`, { method: 'DELETE' });
}

/**
 * Straight after an import. The file goes in through the same button a user
 * presses, because what this shot is about is the sentence that comes back
 * afterwards — how many shapes arrived — and that sentence is written by the
 * interface, not by the server.
 */
if (wanted('22')) {
	await clear();
	const file = join(tmpdir(), 'openkerf-docs-import.svg');
	writeFileSync(
		file,
		`<svg xmlns="http://www.w3.org/2000/svg" width="160mm" height="100mm" viewBox="0 0 160 100">
  <rect x="5" y="5" width="150" height="90" rx="6" fill="none" stroke="#000" stroke-width="0.5"/>
  <circle cx="45" cy="50" r="25" fill="none" stroke="#000" stroke-width="0.5"/>
  <circle cx="115" cy="50" r="25" fill="none" stroke="#000" stroke-width="0.5"/>
  <path d="M45 50 L115 50" fill="none" stroke="#000" stroke-width="0.5"/>
</svg>
`
	);
	await scene('22-import.png', '/?tab=design', {}, async (page) => {
		// The import sits in the top bar at this width, as a file field behind a
		// label. Feeding the field directly is what a click on that label leads to.
		const input = page.locator('input[type="file"][accept*=".svg"]').first();
		await input.setInputFiles(file);
		await page.waitForTimeout(3000);
	});
}

/**
 * A sheet bigger than the bed. The 5030's bed is 500 × 300 mm; a board 900 mm long
 * has to be burned in two goes, and with tiling switched on the app draws the
 * division, the seam and the alignment marks over the drawing.
 *
 * Long and not simply big: a plate that overhangs the bed in *both* directions is
 * refused, in so many words — every seam would then need its own marks and its own
 * order. Asking for 700 × 400 gets a 409 and a canvas with no division on it, which
 * is how this shot failed the first time.
 */
if (wanted('23')) {
	await clear();
	const sheets = await api('GET', '/api/sheets');
	const sheet = sheets.sheets.find((s) => s.active) ?? sheets.sheets[0];
	await fetch(BASE + `/api/sheets/${encodeURIComponent(sheet.id)}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			name: 'Long board',
			width_mm: 900,
			height_mm: 280,
			tiling: { enabled: true }
		})
	});
	await api('POST', '/api/design/elements', {
		type: 'rect',
		x_mm: 25,
		y_mm: 25,
		width_mm: 850,
		height_mm: 230
	});
	await api('POST', '/api/design/elements', { type: 'circle', cx_mm: 450, cy_mm: 140, r_mm: 90 });
	await scene('23-tiling.png', '/?tab=design', {}, async (page) => {
		// The view opens on the bed, and the point of this picture is what falls
		// outside it. "3" is the app's own shortcut for fitting everything in view.
		await page.locator('.stage').click({ position: { x: 40, y: 40 } });
		await page.keyboard.press('3');
		await page.waitForTimeout(1500);
	});
}

/**
 * One rectangle in a cut layer with four bridges in its outline.
 *
 * 60 × 40 mm and four gaps of 2 mm, because that is the case the page quotes: a
 * contour of 200 mm with 192 mm left to cut. At the zoom the bed opens on, a 2 mm
 * gap in a 1.2 px line is not visible, so the shot zooms to the selection first —
 * the whole point of the picture is that you can see the gaps.
 *
 * A cut layer, and not whichever layer the colour happens to land the shape in:
 * outside a cut layer the panel adds a line saying the gaps change nothing yet,
 * and that line is true but it is not what this picture is about.
 */
if (wanted('26')) {
	await clear();
	const layer = await api('POST', '/api/design/operations', {
		type: 'cut',
		label: 'Outline',
		speed: 12,
		power_percent: 65
	});
	const made = await api('POST', '/api/design/elements', {
		type: 'rect',
		x_mm: 40,
		y_mm: 40,
		width_mm: 60,
		height_mm: 40
	});
	const id = made?.ids?.[0];
	if (layer?.id && id) await api('POST', '/api/design/assign', { ids: [id], operation_id: layer.id });
	await api('POST', '/api/design/bridges', { ids: [id], count: 4, length_mm: 2 });
	await scene('26-bridges.png', `/?tab=design&select=${id ?? ''}`, {}, async (page) => {
		// "2" is the app's own key for zooming to the selection. The keyboard listener
		// sits on the window, so nothing has to be clicked first — and clicking the bed
		// would clear the selection this picture needs.
		await page.keyboard.press('2');
		await page.waitForTimeout(1200);
	});
}

/**
 * The node tool with a node in hand and its menu open.
 *
 * The curve is put there through the API, in the same three steps a user takes: add
 * a node to a rectangle, make the piece after it a curve, pull the handle out. So
 * the shape in the picture has a real curve with a real handle on it, and the menu
 * beside it shows the row reading "Make this piece straight" — the state you are in
 * once you have bent something, which is more informative than the offer.
 */
if (wanted('27')) {
	await clear();
	const made = await api('POST', '/api/design/elements', {
		type: 'rect',
		x_mm: 40,
		y_mm: 50,
		width_mm: 80,
		height_mm: 50
	});
	let id = made?.ids?.[0];
	const added = await api('POST', `/api/design/elements/${encodeURIComponent(id)}/nodes`, {
		segment_index: 0
	});
	id = added?.id ?? id;
	const curved = await fetch(
		BASE + `/api/design/elements/${encodeURIComponent(id)}/segments/0/kind`,
		{
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ kind: 'quad' })
		}
	).then((r) => r.json().catch(() => null));
	id = curved?.id ?? id;
	// The control of a fresh quad sits on the chord, so the curve is still straight
	// until it is pulled off it. 20 mm above the top edge is a bend you can see at
	// the size the handbook prints.
	await fetch(BASE + `/api/design/elements/${encodeURIComponent(id)}/segments/0/control`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ which: 1, x_mm: 60, y_mm: 30 })
	});
	await scene('27-nodes.png', `/?tab=design&select=${id ?? ''}`, {}, async (page) => {
		await page.keyboard.press('2');
		await page.waitForTimeout(900);
		await page.locator(`${RAIL}[title^="Nodes"]`).click();
		// The knots come from the server, so they are not on screen the instant the
		// tool is picked.
		await page.waitForSelector('.knot', { timeout: 10000 });
		// Node 1 is the start of segment 0, which is the piece that was bent — so it
		// is the node whose handle is on screen and whose menu says "straight".
		const grip = page.locator('[aria-label="Drag node 1"]').first();
		await grip.click();
		await page.waitForTimeout(400);
		await grip.click({ button: 'right' });
		await page.waitForSelector('.menu', { timeout: 5000 });
		await page.waitForTimeout(400);
	});
}

/**
 * The living hinge tab, with its preview computed.
 *
 * The numbers are the ones the page quotes — 8 mm slits, 3 mm apart, 2 mm between
 * rows — so the count under the preview reads the 120 slits in 20 rows that the
 * text names. Those are the tab's own defaults, so nothing is typed here; the shot
 * only has to open the tab and wait for the server to answer.
 */
if (wanted('28')) {
	await clear();
	await scene('28-hinge.png', '/?tab=design', {}, async (page) => {
		await page.locator(TOOL.generators).click();
		await page.waitForSelector(DIALOG, { timeout: 10000 });
		await page.locator(`${DIALOG} .tabs button.tab`, { hasText: 'Living hinge' }).click();
		// The preview waits 250 ms after the last change and then asks the server.
		await page.waitForTimeout(2500);
	});
}

/**
 * The cut-path window, halfway through its replay.
 *
 * Its own little design and not the drawing of section 3: this picture is about the
 * *order*, so the shapes have to be few enough that the numbers beside them can be
 * read. Two squares of 80 mm, 60 mm apart, with a 40 mm one inside the left-hand
 * square — that is checklist step 3 (does it cut inside before outside) and it is
 * the one thing the picture has to prove it can show. The engraved bar underneath
 * puts a second layer in the legend and a long travel line across the drawing.
 *
 * The scrubber is dragged to the middle rather than left at zero: at zero the whole
 * path is faint and there is nothing to see about "burned so far". Setting the
 * range's value with `fill` fires the same input event the mouse does, so the shot
 * lands on a fixed moment of the job instead of on however long a play took.
 */
if (wanted('29')) {
	await clear();
	const cut = await api('POST', '/api/design/operations', {
		type: 'cut',
		label: 'Outline',
		speed: 12,
		power_percent: 65
	});
	const engrave = await api('POST', '/api/design/operations', {
		type: 'engrave',
		label: 'Caption',
		speed: 250,
		power_percent: 22
	});
	const put = async (shape, layer) => {
		const made = await api('POST', '/api/design/elements', shape);
		const id = made?.ids?.[0];
		if (id && layer?.id) {
			// New shapes are filed by colour, so out of everything first and then into
			// the layer this picture needs — the same dance as `seed()`.
			for (const op of [cut?.id, engrave?.id])
				if (op) await api('POST', '/api/design/unassign', { ids: [id], operation_id: op });
			await api('POST', '/api/design/assign', { ids: [id], operation_id: layer.id });
		}
		return id;
	};
	// The sizes are chosen against the numbering, not against the bed. A number is
	// folded into its neighbour when the two would overlap, and at this bed (500 mm, so
	// a digit is about 16 mm tall on the drawing) an inner square 12 mm inside its outer
	// one gave "1+1" in one spot instead of a 1 and a 2 — true, and useless as a picture
	// of the order. 20 mm between the two starting corners keeps them apart.
	await put({ type: 'rect', x_mm: 40, y_mm: 40, width_mm: 80, height_mm: 80 }, cut);
	await put({ type: 'rect', x_mm: 60, y_mm: 60, width_mm: 40, height_mm: 40 }, cut);
	await put({ type: 'rect', x_mm: 180, y_mm: 40, width_mm: 80, height_mm: 80 }, cut);
	await put({ type: 'rect', x_mm: 40, y_mm: 160, width_mm: 220, height_mm: 15 }, engrave);
	await api('POST', '/api/design/operations/prune');
	// The whole window does not fit in any picture, and no viewport changes that: the
	// dialog is capped at min(80vh, 760px) while the drawing alone is 58vh, so the body
	// always scrolls. Measured: at 1400 px high the path itself had scrolled out of the
	// top of the crop (contour 4 at the edge, the squares gone). So this picture is the
	// top of the window — the order, the travel and the clock — and the sums, the legend
	// and the note about what the clock cannot promise are quoted in docs/job.md instead.
	await scene('29-cutpath.png', '/?tab=job', { selector: DIALOG }, async (page) => {
		// The pre-flight builds its estimate first; the button under the drawing only
		// exists once the panel has drawn the pre-flight at all.
		await page.waitForTimeout(3000);
		await page.locator('button', { hasText: 'Show cut path' }).first().click();
		await page.waitForSelector(`${DIALOG} .cp`, { timeout: 30000 });
		const scrub = page.locator(`${DIALOG} input[type="range"]`).first();
		const max = Number(await scrub.getAttribute('max'));
		await scrub.fill(String(Math.round(max / 2)));
		// Putting a value in the range scrolls it into view; if the window is scrollable
		// at all, that takes the drawing with it.
		await page.locator(DIALOG).first().evaluate((node) => node.scrollTo(0, 0));
		await page.waitForTimeout(600);
	});
}

/**
 * The rotary page, for a machine that has one fitted.
 *
 * The state is answered from the script, the same way shot 01 answers the machine
 * list, and for a stronger reason: the real answer here depends on which machine
 * happens to be active in this session, and switching a machine on or writing a
 * rotary setting would change the owner's laser to take a photograph. Nothing on
 * this page writes anything by itself — it is a draft until Save, and the script
 * does not press Save — so what is faked is only the answer it opens with.
 *
 * The numbers are the ones the handbook quotes: a chuck of 80 mm (251.33 mm round)
 * and the factor 1.0363 that comes out of 100 mm asked for and 96.5 mm measured.
 */
if (wanted('30')) {
	await scene(
		'30-rotary.png',
		'/setup/rotary?machine=ruida',
		{
			// Tall enough for the whole page in one picture, checklist and all: the ten
			// steps at the foot are the part somebody reads standing at the laser, and a
			// picture that stops above them would be a picture of half the feature.
			// Measured: the page ends at 2044 px at this width, so 2060 is the whole of it
			// with nothing but its own margin under the last step.
			height: 2060,
			route: async (page) => {
				await page.route('**/api/machine/rotary', (r) =>
					r.fulfill({
						status: 200,
						contentType: 'application/json',
						body: JSON.stringify({
							active: true,
							kind: 'chuck',
							diameter_mm: 80,
							circumference_mm: 251.3274,
							scale_source: 'manual',
							manual_scale_y: 1.036269,
							flat_steps_per_mm: 0,
							rotary_steps_per_mm: 0,
							last_calibration: {
								commanded_mm: 100,
								measured_mm: 96.5,
								factor: 1.036269
							},
							scale_y: 1.036269,
							scale_x: 1,
							// The whole page: on a machine that brings MeerK40t's own rotary
							// along, everything below the first paragraph is replaced by one
							// sentence saying so.
							engine_rotary: false
						})
					})
				);
			}
		},
		async (page) => {
			await page.waitForTimeout(600);
		}
	);
}

// ═════════════════════════════════════════ 9. the four small ones (lock … cut)

/**
 * A locked shape, and the panel saying what a lock covers.
 *
 * The shape is selected *and* locked, because the whole point of the picture is what
 * the selection looks like when it cannot be dragged: no corner handles, no rotation
 * stem, and the note in the panel with the way out in it. Locking through the API and
 * not with ⌘L, so the picture does not depend on which element the keyboard focus
 * happened to be in.
 */
if (wanted('31')) {
	await clear();
	const made = await api('POST', '/api/design/elements', {
		type: 'rect',
		x_mm: 40,
		y_mm: 40,
		width_mm: 120,
		height_mm: 70
	});
	const id = made?.ids?.[0];
	await api('POST', '/api/design/lock', { ids: [id], locked: true });
	await scene('31-lock.png', `/?tab=design&select=${encodeURIComponent(id)}`, {}, async (page) => {
		await page.waitForTimeout(800);
	});
	await api('POST', '/api/design/lock', { ids: [id], locked: false });
}

/**
 * The duplicates question, with real numbers in it.
 *
 * Three copies of one rectangle and two of one circle: two places, three shapes too
 * many — so the sentence in the picture is the plural one with both counts, which is
 * the wording the page quotes. The dialog is opened from the bed's own menu, because
 * that is the way in that searches the whole sheet.
 */
if (wanted('32')) {
	await clear();
	for (let i = 0; i < 3; i++)
		await api('POST', '/api/design/elements', {
			type: 'rect',
			x_mm: 40,
			y_mm: 40,
			width_mm: 90,
			height_mm: 60
		});
	for (let i = 0; i < 2; i++)
		await api('POST', '/api/design/elements', { type: 'circle', cx_mm: 240, cy_mm: 90, r_mm: 30 });
	await scene('32-duplicates.png', '/?tab=design', {}, async (page) => {
		const bed = await page.locator('.bed > svg').boundingBox();
		await page.mouse.click(bed.x + bed.width * 0.9, bed.y + bed.height * 0.9, {
			button: 'right'
		});
		await page.waitForTimeout(500);
		await page.getByRole('menuitem', { name: /Remove duplicates/ }).first().click();
		await page.waitForSelector(DIALOG, { timeout: 10000 });
		await page.waitForTimeout(600);
	});
}

/**
 * The focus test tab.
 *
 * The handbook's machine is a Ruida and has no Z axis the software can move, so the
 * tab is not there — correctly. The capability answer is therefore given from the
 * script for the length of this one page, exactly as shot 01 does with the machine
 * list: the app then draws its own tab, with its own preview from the real server
 * (the preview needs no Z; only burning does).
 */
if (wanted('33')) {
	await clear();
	await scene(
		'33-focus.png',
		'/?tab=design',
		{
			route: async (page) => {
				await page.route('**/api/design/capabilities', (r) =>
					r.fulfill({
						status: 200,
						contentType: 'application/json',
						body: JSON.stringify({ air_assist: false, z_step: true })
					})
				);
			}
		},
		async (page) => {
			await page.locator(TOOL.generators).click();
			await page.waitForSelector(DIALOG, { timeout: 10000 });
			await page.locator(`${DIALOG} .tabs button.tab`, { hasText: 'Focus test' }).click();
			// The preview waits 250 ms after the last change and then asks the server.
			await page.waitForTimeout(2500);
		}
	);
}

/**
 * Print and cut, with an alignment in it.
 *
 * The measured pose is answered from the script, and that is the honest way round:
 * the real thing needs a head driven over two marks on a printed sheet, and there is
 * no sheet in the machine. The numbers are the ones the page quotes — mark 1 moved
 * 2.5, 1.2 mm and the sheet lies 0.3° out — so the picture and the prose cannot
 * drift apart. The shapes are on the bed for real, so the drawing behind the panel is
 * a drawing with two marks in it.
 */
if (wanted('34')) {
	await clear();
	const first = await api('POST', '/api/design/elements', {
		type: 'circle',
		cx_mm: 30,
		cy_mm: 30,
		r_mm: 3
	});
	const second = await api('POST', '/api/design/elements', {
		type: 'circle',
		cx_mm: 260,
		cy_mm: 40,
		r_mm: 3
	});
	await api('POST', '/api/design/elements', {
		type: 'rect',
		x_mm: 70,
		y_mm: 70,
		width_mm: 140,
		height_mm: 90
	});
	const marks = [first?.ids?.[0], second?.ids?.[0]];
	await scene(
		'34-printcut.png',
		'/?tab=job',
		{
			// Tall enough that the print-and-cut block is in the picture: the panel is one
			// scrolling column and this block sits under the zero point, which is under the
			// machine controls. Measured: at 1300 px it fell just below the edge.
			height: 1700,
			route: async (page) => {
				await page.route('**/api/printcut', (r) =>
					r.fulfill({
						status: 200,
						contentType: 'application/json',
						body: JSON.stringify({
							marks: [
								{
									id: marks[0],
									drawn: { x_mm: 30, y_mm: 30 },
									measured: { x_mm: 32.5, y_mm: 31.2 }
								},
								{
									id: marks[1],
									drawn: { x_mm: 260, y_mm: 40 },
									measured: { x_mm: 262.5, y_mm: 42.4 }
								}
							],
							offset_mm: { x_mm: 2.5, y_mm: 1.2 },
							aligned: true,
							angle_deg: 0.3,
							dx_mm: 2.5,
							dy_mm: 1.2,
							distance_error_mm: 0.01,
							tolerance_mm: 2,
							max_angle_deg: 3,
							lapsed: null
						})
					})
				);
			}
		},
		async (page) => {
			await page.waitForTimeout(900);
		}
	);
}

// ══════════════════════════════════════════ 10. a series: one design, many names

/**
 * The list the three series pictures are burned from.
 *
 * Five plainly fictional names and a second column the design does not read, so the
 * columns table can show both states at once: "In use" beside `name` and nothing
 * beside `room`. Deliberately no date column and no counter — either would put a
 * different value in the picture every time it is taken, against the promise beside
 * this script that a picture shows the same thing next month.
 *
 * It is written to a directory of its own because the basename is what the reader
 * sees: the window says "These rows came from the file names.csv." and a temporary
 * name with a prefix on it would be in the handbook for good.
 */
const SERIES_CSV = `name,room
Anna,Kitchen
Bram,Studio
Cees,Workshop
Daan,Loft
Eva,Cellar
`;
const SERIES_FILE = join(tmpdir(), 'openkerf-docs-series', 'names.csv');

/**
 * A keyring tag that reads its name out of the list, with the list attached.
 *
 * The order is not free. A text holding `{name}` is refused while nothing is
 * attached — "No list is attached, so a text with a placeholder in it cannot become
 * anything." — so the list goes on first and the tag is drawn against it. That
 * refusal is the feature working, not something to work around.
 *
 * One tag and nothing else on the bed, because two of these three pictures are
 * about a single word: the name has to be legible at the zoom the picture is taken
 * at, and a bed with a drawing on it as well would put it at a tenth of the width.
 *
 * The upload is an ordinary multipart POST and Node can make one, so the seeding
 * needs no browser. Shot 35 chooses the same file again *in the window*, because
 * what the app read out of a file is only on screen for a file that window session
 * has read — see there.
 */
async function seedSeries() {
	await clear();
	mkdirSync(dirname(SERIES_FILE), { recursive: true });
	writeFileSync(SERIES_FILE, SERIES_CSV);

	const form = new FormData();
	form.append('file', new Blob([SERIES_CSV], { type: 'text/csv' }), 'names.csv');
	const upload = await fetch(BASE + '/api/series/upload', { method: 'POST', body: form })
		.then((r) => (r.ok ? r.json() : null))
		.catch(() => null);
	if (!upload?.file) throw new Error('series: the upload was refused');
	await api('POST', '/api/series/attach', {
		kind: 'file',
		file: upload.file,
		has_header: true,
		skip_blank: true
	});

	// 11.5 mm/s and not a round 14: the page quotes the clock this design comes out at
	// — "Estimated time 0:24", and three of those in the line under it — so the speed is
	// picked to give that, the way shot 26 sizes its rectangle and shot 28 leaves the
	// hinge on its defaults. Measured through `/api/job/estimate`: 14 gives 19.9 s, 12
	// gives 23.1 s, 11.5 gives 24.0 s. A cut of 11.5 mm/s at 70 % is an ordinary setting
	// for a tag in 3 mm ply, so nothing about the picture is odd to read.
	const cut = await api('POST', '/api/design/operations', {
		type: 'cut',
		label: 'Tag outline',
		speed: 11.5,
		power_percent: 70
	});
	const engrave = await api('POST', '/api/design/operations', {
		type: 'engrave',
		label: 'Name',
		speed: 280,
		power_percent: 22
	});
	const put = async (shape, layer) => {
		const made = await api('POST', '/api/design/elements', shape);
		const id = made?.ids?.[0];
		if (id && layer?.id) {
			// New shapes are filed by colour, so out of both layers first and then into
			// the one this picture needs — the same dance as `seed()`.
			for (const op of [cut?.id, engrave?.id])
				if (op) await api('POST', '/api/design/unassign', { ids: [id], operation_id: op });
			await api('POST', '/api/design/assign', { ids: [id], operation_id: layer.id });
		}
		return id;
	};
	await put(
		{ type: 'rect', x_mm: 40, y_mm: 40, width_mm: 90, height_mm: 40, corner_radius_mm: 8 },
		cut
	);
	await put({ type: 'circle', cx_mm: 51, cy_mm: 60, r_mm: 3 }, cut);
	// The text last, so it is the newest shape and its id is the one the two pictures
	// that need a selection point at.
	// `font_size_mm` and not `height_mm`: the latter is quietly ignored for text and the
	// name then comes out 3.8 mm tall on a 40 mm tag — legible on the bed and four pixels
	// high in a handbook. The anchor is the left end of the baseline, so these two
	// numbers put the word beside the hole and on the tag's own centre line.
	const text = await put(
		{ type: 'text', x_mm: 69, y_mm: 66, text: '{name}', font_size_mm: 14 },
		engrave
	);
	await api('POST', '/api/design/operations/prune');
	return text;
}

/**
 * Shot 35: the window with a list on it.
 *
 * Two halves and both have to be filled, and they are filled by two different
 * things. The burn list on the left is there because a list is *attached* — that is
 * server state, and the seeding above put it there. The block on the right is what
 * this app read out of a *file*, and that only exists for a file the open window has
 * read: it is not kept with the list, on purpose, because it is a report on a
 * reading and not a property of the rows. So the same file is handed to the window's
 * own field here, the way shot 22 hands the importer a drawing.
 *
 * Nothing is pressed afterwards. The button says "Use this list instead" because a
 * list is already on; pressing it would attach the very same rows again.
 */
if (wanted('35')) {
	await seedSeries();
	await scene(
		'35-series.png',
		'/?tab=design',
		{
			// The whole of the right-hand pane does not fit — the dialog is capped at
			// min(80vh, 760px) and the pane is two tables, a tick and a row field — so
			// this is the top of the window, which is what the page beside it walks
			// through. What *is* in the picture is the action row: it sat below the fold
			// at every window height until the round that took this shot made it stick to
			// the foot of the pane, which is exactly the sort of thing a photograph finds
			// and a measurement does not.
			//
			// 1000 px and not the usual 900: at 900 the cap is 80vh = 720 and the fold
			// climbs another 40 px, taking "Start at row" with it. Above 950 the 760 px
			// half of the cap wins and nothing more is gained by going taller.
			height: 1000
		},
		async (page) => {
			await page.locator(TOOL.series).click();
			await page.waitForSelector(DIALOG, { timeout: 10000 });
			await page.locator(`${DIALOG} input[type="file"]`).setInputFiles(SERIES_FILE);
			// The upload answers with the reading, and every change after that waits
			// 200 ms and asks the server again.
			await page.waitForTimeout(2500);
		}
	);
}

/**
 * Shot 36: the bed showing the row that is about to burn.
 *
 * The whole feature has to be trusted about one thing — that the name on the bed is
 * the name the next plate gets — so this picture has to carry both halves at once:
 * the tag with `Anna` cut into it, and the panel saying that the text itself reads
 * `{name}`. Without the second half the picture reads as a bug.
 *
 * Zoomed to the drawing ("3", the app's own key), because the point of the picture
 * is a single word and a 90 mm tag on a 500 mm bed prints it four pixels tall.
 */
if (wanted('36')) {
	const text = await seedSeries();
	await scene('36-series-text.png', `/?tab=design&select=${encodeURIComponent(text ?? '')}`, {}, async (page) => {
		await page.keyboard.press('3');
		await page.waitForTimeout(1200);
	});
}

/**
 * Shot 37: the Job tab with a run going.
 *
 * The run itself is real. `POST /api/series/start` writes the count of plates and
 * sends nothing to the machine — its own tooltip says so in as many words — and
 * `advance` moves the pointer on without burning, which is what the button "Burned,
 * next one" does. So "Burn 3 of 5" and "This one engraves Cees." are the app's own
 * state, arrived at by the two presses an operator makes.
 *
 * The two plates behind it are not, and cannot be. A burn is only ever marked done
 * by `POST /api/series/burn`, and that builds the plan and hands it to the spooler
 * of the machine that is really there — a Ruida over the network that reopens its
 * connection by itself. Nothing in a documentation script is worth setting a laser
 * going in an empty room, which is the same reason 13-queue.png is not in this file
 * at all.
 *
 * So the count of what has been burned is answered from the script, the way shot 01
 * answers the machine list and shot 34 answers the print-and-cut pose: two burns
 * done, in the three places that read that one fact — the socket the run block
 * lives on, the window's own route, and the estimate, which counts the plates still
 * due on the server. All three or none: patch one and the picture shows a bar at
 * two fifths above a line promising five more plates, which is worse than no
 * picture. What is invented is a number of our own bookkeeping — "two of these were
 * counted" — and not a state of the machine; nothing here claims the laser did
 * anything.
 */
if (wanted('37')) {
	const text = await seedSeries();
	if (!text) throw new Error('37: no text on the bed to read the list');
	await api('POST', '/api/series/start');
	// Twice, because the picture is of a run in the middle and not of one that has
	// just begun: the third plate is the first that has a before and an after.
	await api('POST', '/api/series/advance');
	await api('POST', '/api/series/advance');

	/** Two burns behind us, said the same way wherever it is read. */
	const DONE = [[0, 1]];
	const counted = (state) =>
		state?.run ? { ...state, run: { ...state.run, done: DONE } } : state;

	await scene(
		'37-series-run.png',
		'/?tab=job',
		{
			// Tall enough for the run block *and* everything the page quotes under it: the
			// clock, the line counting the afternoon, the layer table and the checklist,
			// down to the start button. Measured: at 900 px the picture stopped above the
			// clock, and below 1120 the checklist is cut in half.
			height: 1120,
			route: async (page) => {
				await page.route('**/api/series', async (r) => {
					const response = await r.fetch();
					await r.fulfill({ response, json: counted(await response.json()) });
				});
				await page.route('**/api/job/estimate**', async (r) => {
					const response = await r.fetch();
					const answer = await response.json();
					// The route multiplies this plate's own time by the plates still due, so
					// the two numbers on screen always multiply. Doing the same here keeps
					// that true.
					const left = 3;
					await r.fulfill({
						response,
						json: {
							...answer,
							burns_left: left,
							seconds_total: Math.round(answer.seconds * left * 10) / 10
						}
					});
				});
				// The run block reads the live socket and nothing else — one fact, one
				// source, so the top bar and the phone view cannot drift from it. Which
				// means the socket is where this has to be said too.
				await page.routeWebSocket('**/api/ws', (ws) => {
					const server = ws.connectToServer();
					server.onMessage((message) => {
						let payload = null;
						try {
							payload = JSON.parse(String(message));
						} catch {
							// Not JSON: hand it on untouched.
						}
						if (payload?.type === 'snapshot' && payload.data?.series)
							payload.data.series = counted(payload.data.series);
						ws.send(payload ? JSON.stringify(payload) : message);
					});
				});
			}
		},
		async (page) => {
			// The pre-flight builds a whole cut plan before it can say anything.
			await page.waitForTimeout(4000);
		}
	);
	// A run left going would refuse the ordinary Burn button in the next person's
	// browser, with a sentence about a series they never started.
	await api('POST', '/api/series/stop');
}

/**
 * Shot 38: a plate laid out by the app.
 *
 * Its own list and not the five-name one the other three share: the point of the
 * picture is what happens when the list is *longer* than the plate holds, and five
 * names on a 500 × 300 plate fit twice over. Twenty-three rows on a 110 × 60 piece is
 * sixteen places and two plates, so the burn list shows both and the second one says
 * how many places have no row left — which is the sentence the page quotes.
 *
 * The piece is bigger than the tag of shots 35 to 37 for the same reason: a 90 × 40 tag
 * fits thirty times on this plate and the picture would be a wall of small words. This
 * is the one shot in the file that presses a button that changes the drawing, so it
 * runs last and `clear()` at the head of the next one puts everything back.
 */
if (wanted('38')) {
	await clear();
	const names = [
		'Anna', 'Bram', 'Cees', 'Daan', 'Eva', 'Fien', 'Gijs', 'Hanna',
		'Ids', 'Joke', 'Kees', 'Lotte', 'Mees', 'Niek', 'Olga', 'Pim',
		'Ria', 'Sam', 'Tess', 'Ute', 'Vera', 'Wim', 'Xander'
	];
	const csv = `name\n${names.join('\n')}\n`;
	const form = new FormData();
	form.append('file', new Blob([csv], { type: 'text/csv' }), 'names.csv');
	const upload = await fetch(BASE + '/api/series/upload', { method: 'POST', body: form })
		.then((r) => (r.ok ? r.json() : null))
		.catch(() => null);
	if (!upload?.file) throw new Error('series: the upload was refused');
	await api('POST', '/api/series/attach', { kind: 'file', file: upload.file });
	const cut = await api('POST', '/api/design/operations', {
		type: 'cut',
		label: 'Tag outline',
		speed: 11.5,
		power_percent: 70
	});
	const outline = await api('POST', '/api/design/elements', {
		type: 'rect',
		x_mm: 150,
		y_mm: 100,
		width_mm: 110,
		height_mm: 60,
		corner_radius_mm: 8
	});
	const name = await api('POST', '/api/design/elements', {
		type: 'text',
		x_mm: 162,
		y_mm: 142,
		text: '{name}',
		font_size_mm: 18
	});
	const ids = [...(outline?.ids ?? []), ...(name?.ids ?? [])];
	if (cut?.id) await api('POST', '/api/design/assign', { ids, operation_id: cut.id });
	await api('POST', '/api/design/group', { ids });
	await api('POST', '/api/design/operations/prune');

	await scene(
		'38-series-plate.png',
		'/?tab=design',
		{},
		async (page) => {
			await page.locator(TOOL.series).click();
			await page.waitForSelector(DIALOG, { timeout: 10000 });
			// The sum is a debounced read, so it is on screen a moment after the window.
			await page.waitForTimeout(1200);
			await page.getByRole('button', { name: /^Lay out/ }).click();
			await page.waitForTimeout(2000);
			// And then out of the way: the window itself is already shot 35, and what
			// this section is about is the plate it produced — sixteen tags, sixteen
			// names, laid out from the corner of the margin.
			//
			// By its own close button and not by Escape: after the fill the focus sits on
			// a button that has just been re-rendered, and the key then reaches nothing
			// (measured — the window stayed open and the picture was of the window again).
			await page.locator(`${DIALOG} button.close`).click();
			await page.waitForTimeout(500);
			await page.keyboard.press('3');
			await page.waitForTimeout(900);
		}
	);
}

// ══════════════════════════ 8. the offer, the material verbs, the board's extras

/**
 * Shot 39 needs a machine with no settings at all, and the machine on this laptop
 * has three it measured itself — so the card never appears here. Rather than
 * emptying somebody's library to take a photograph, the offer route and the
 * catalogue route are answered from this script for the length of this one page,
 * exactly as shot 01 answers the machine list. Everything the picture shows is
 * the app's own rendering of those two answers.
 *
 * Nothing is pressed but "Show what would suit this laser". **Add these** writes
 * to the library, and a documentation script does not write to somebody's
 * library.
 *
 * Three details that each cost a run.
 *
 * **The rows are not invented.** They are three entries of the catalogue the app
 * ships with (`api/openkerf_api/starter_seed.json`), copied out of that file with
 * their own speeds, powers, tiers and handle. Typing plausible numbers instead put
 * "16 mm/s at 55%" on screen under the id `berkentriplex-3mm-snijden-co2-80w`,
 * which really carries 12 mm/s at 65% — a handbook picture quoting a setting that
 * does not exist, under the name of one that does.
 *
 * **The machine is the one that is really there.** Its id and name are read off the
 * live offer, because the top bar and the "Only …" checkbox beside the card read
 * the real machine and anything else puts two names for one laser in one picture —
 * measured twice: a pinned "KH-5030" over a top bar reading "Bench 5030", and then
 * "the first profile that has a device" over the same bar, which is a leftover
 * called "Dummy Device". Only the two facts the picture is *about* are made up: the
 * kind of laser and the wattage.
 *
 * **The bed is cleared first**, for the reason `open()` gives: a recovery file left
 * behind by an engine that was killed puts a modal over the screen, and the rail
 * button underneath it cannot be pressed at all.
 */
if (wanted('39')) {
	await clear();
	const live = await api('GET', '/api/library/starter');
	const active = live?.machine ?? null;
	const offer = {
		machine: {
			id: active?.id ?? 1,
			name: active?.name ?? 'KH-5030',
			laser_type: 'co2-glass',
			power_watt: 80,
			starter_state: ''
		},
		state: 'nothing',
		needed: true,
		coverage: {
			mine: 0,
			mine_measured: 0,
			materials_covered: 0,
			materials_known: 20,
			unattached: 0,
			unattached_grids: 0
		}
	};
	// Three rows over two materials: enough for the list to show a material block,
	// its Add button and a row's own values, and few enough to fit in the card
	// without a scroll bar across the picture. Which three is fixed by id, so the
	// picture is the same next month; what each one says comes out of the file.
	const seed = JSON.parse(
		readFileSync(join(dirname(OUT), '..', 'api', 'openkerf_api', 'starter_seed.json'), 'utf8')
	);
	const wantedRows = [
		'berkentriplex-3mm-snijden-co2-80w',
		'berkentriplex-3mm-graveren-raster-co2-80w',
		'mdf-3mm-snijden-co2-80w'
	];
	const presets = wantedRows.map((id) => {
		const entry = seed.presets.find((p) => p.id === id);
		if (!entry) throw new Error(`39: ${id} is no longer in starter_seed.json`);
		return {
			...entry,
			// The two fields the catalogue route adds per machine and the seed file
			// cannot carry: whether this library already holds the row, and whether the
			// wattage matched. Both false here — that is the state the card is about.
			imported: false,
			power_unmatched: false
		};
	});
	const catalogue = {
		version: seed.version,
		count: presets.length,
		total: seed.presets.length,
		stale: false,
		very_stale: false,
		fetched_at: Math.floor(Date.now() / 1000) - 3600,
		skipped: 0,
		error: null,
		from_seed: false,
		license: seed.license,
		attribution: seed.attribution,
		machine_id: offer.machine.id,
		matched_on: 'kind+power',
		presets
	};
	const json = (body) => ({
		status: 200,
		contentType: 'application/json',
		body: JSON.stringify(body)
	});
	await scene(
		'39-starter.png',
		'/?tab=design',
		{
			route: async (page) => {
				await page.route('**/api/library/starter', (r) => r.fulfill(json(offer)));
				// By the path and not by a glob with a `?` in it: the app asks for
				// `/api/presetariat?machine_id=5`, and whether `?` is a wildcard or a
				// literal in Playwright's globs has changed between versions. A
				// predicate cannot go stale that way.
				await page.route(
					(url) => url.pathname === '/api/presetariat',
					(r) => r.fulfill(json(catalogue))
				);
			}
		},
		async (page) => {
			await page.locator(TOOL.library).click();
			await page.waitForSelector(DIALOG, { timeout: 10000 });
			await page.waitForTimeout(2600);
			await page.getByRole('button', { name: 'Show what would suit this laser' }).click();
			await page.waitForTimeout(1200);
		}
	);
}

/**
 * Shot 40: the ⋯ on a material row, open. Read-only — the menu is a menu, and
 * none of its five rows is pressed.
 *
 * The offer route is answered here as well, and for once *to get the card out of
 * the way*. This laptop's machine has no wattage recorded, so the real answer is
 * the two-field `askMachine` card — 330 px of it, which is shot 39's other state
 * and pushed the list this picture is about off the bottom of the window
 * (measured: the menu opened at y=730 with not one material row visible behind
 * it). The one fabricated fact is the wattage, exactly as in shot 39; the machine,
 * the coverage and the strays are this library's own, so what stands above the
 * list is the quiet door that a library with settings in it really shows.
 *
 * The drawing is seeded first for the same reason: an empty bed puts "There is no
 * layer to put a setting on yet." above the list, which is a true sentence about
 * an empty bed and not about materials.
 */
if (wanted('40')) {
	await seed();
	const live = await api('GET', '/api/library/starter');
	const settled = {
		...(live ?? {}),
		machine: { ...(live?.machine ?? {}), power_watt: live?.machine?.power_watt ?? 80 },
		state: 'none',
		needed: false
	};
	await scene(
		'40-material-verbs.png',
		'/?tab=design',
		{
			route: async (page) => {
				await page.route('**/api/library/starter', (r) =>
					r.fulfill({
						status: 200,
						contentType: 'application/json',
						body: JSON.stringify(settled)
					})
				);
			}
		},
		async (page) => {
			await page.locator(TOOL.library).click();
			await page.waitForSelector(DIALOG, { timeout: 10000 });
			await page.waitForTimeout(2600);
			// Every material and not only those with a setting for this laser: the
			// checkbox is on by default, and with it on this library shows two rows out
			// of twenty. The verbs on the menu are about the material itself, so the
			// list they belong to is the whole list.
			await page.locator(`${DIALOG} label.bereik input[type="checkbox"]`).first().click();
			await page.waitForTimeout(1200);
			const rows = page.locator(`${DIALOG} .materials li.matregel`);
			if (!(await rows.count())) throw new Error('40: no materials in the library to open');
			// Berkentriplex by name, because it is the material the handbook uses on
			// every other page; the first row of the list if this library has none.
			const named = rows.filter({ has: page.locator('.matname', { hasText: /Berken/ }) });
			const row = (await named.count()) ? named.first() : rows.first();
			await row.locator('.meer').click();
			await page.waitForTimeout(600);
		}
	);
}

/**
 * Shots 41 and 42 draw a real test board with a code and with a cut-out — and
 * drawing one writes a row into the library, mints the board a name and, for the
 * cut-out, needs a cut setting for the material. That is more than a screenshot
 * may do to somebody's real library, so these two only run against a library that
 * is expendable. Shot 43 photographs the form rather than a board and so writes no
 * row of its own, but it needs the same material with the same cut setting for the
 * cut-out to have anything to report, so it goes with them:
 *
 *   OK_SCRATCH_LIBRARY=1 OK_BASE=http://localhost:5200 node gauntlet/docs-shots.mjs 41
 *
 * Start an engine of its own for it — `openkerf -p 8092 -l <path>`, which is the
 * flag that exists; the harness has none — and point OK_BASE at a dev server in
 * front of it (`OPENKERF_API=http://127.0.0.1:8092 npx vite dev --port 5200`).
 * Without the flag both are skipped and say so, because a silent skip is how a
 * picture goes stale.
 *
 * One thing that engine does *not* get a copy of: the machine list and the
 * machine's own settings live in one `MeerK40t.cfg` for every instance, so a
 * scratch engine comes up with whatever bed and name the file happens to hold —
 * measured: 609.6 × 406.4 mm and a leftover name, where every other picture in
 * this set shows 500 × 300 and KH-5030. Set those before photographing, or the
 * two board pictures disagree with the rest of the handbook.
 */
const scratch = process.env.OK_SCRATCH_LIBRARY === '1';

/**
 * The board both pictures are of, drawn through the API.
 *
 * `uid` is given rather than left to the server, and that is the whole reason these
 * two pictures are worth reprinting: a minted name is eight random characters, so
 * every run burned a different word into the caption and a different pattern into
 * the code, and no page could ever point at either. `7X4MQB2K` is the name the
 * handbook's own prose uses, so the picture and the text now say the same thing.
 * On a library that already holds that name the server mints a fresh one instead —
 * deliberately, so that two planks never carry one name — which is a second reason
 * these shots want a library of their own.
 *
 * The material is made once and reused: `POST /api/library/materials` refuses a
 * name it already has, and a second run then had no material to hang the board on.
 */
async function birchWithCutSetting() {
	const materials = (await api('GET', '/api/library/materials')) ?? [];
	const material =
		materials.find((m) => m.name === 'Birch plywood') ??
		(await api('POST', '/api/library/materials', { name: 'Birch plywood' }));
	if (!material) throw new Error('41/42/43: could not make a material on the scratch library');
	// A cut setting for the board's own rim: the cut-out is refused without one,
	// and refused rather than guessed on purpose — see docs/test-grid.md. Idempotent
	// in effect: a second identical row changes nothing the picture shows.
	await api('POST', '/api/library/presets', {
		material_id: material.id,
		operation: 'snijden',
		thickness_mm: 3,
		speed_mm_s: 12,
		power_percent: 65,
		source: 'handmatig'
	});
	return material;
}

async function boardOn(extra) {
	const material = await birchWithCutSetting();
	return api('POST', '/api/library/testgrids', {
		operation: 'snijden',
		material_id: material.id,
		thickness_mm: 3,
		row_axis: 'speed',
		column_axis: 'power',
		speed_min: 8,
		speed_max: 20,
		speed_steps: 4,
		power_min: 40,
		power_max: 90,
		power_steps: 4,
		cell_mm: 8,
		gap_mm: 2,
		origin_x_mm: 40,
		origin_y_mm: 30,
		caption: 'Cut trial',
		uid: '7X4MQB2K',
		...extra
	});
}

if (wanted('41') || wanted('42') || wanted('43') || wanted('44')) {
	if (!scratch) {
		console.log(
			'  – 41-board-code.png, 42-board-tile.png, 43-board-extras.png and ' +
				'44-board-readback.png skipped: set OK_SCRATCH_LIBRARY=1'
		);
	} else {
		if (wanted('41')) {
			await clear();
			await boardOn({ code_enabled: true, code_size_mm: 18 });
			await scene('41-board-code.png', '/?tab=design', {}, async (page) => {
				await page.keyboard.press('3');
				await page.waitForTimeout(900);
			});
		}
		if (wanted('42')) {
			await clear();
			// Its own name, because it is its own plank. Left to the server the second
			// board of a run got a minted name (measured: `BYMH HXVP`), which is the
			// right behaviour — two planks never share a name — and the wrong thing for
			// a picture, since the caption then read something different every time.
			// The cut-out brings the code with it; asking for both says so out loud.
			await boardOn({ code_enabled: true, cutout_enabled: true, uid: '5NKD8W3Q' });
			await scene('42-board-tile.png', '/?tab=layers', {}, async (page) => {
				await page.keyboard.press('3');
				await page.waitForTimeout(900);
			});
		}
		if (wanted('43')) {
			// Same as 41 and 42: an autosaved design from an earlier run puts the recovery
			// dialog over the rail, and then nothing on this form can be reached.
			await clear();
			// The two switches on the form, both on, with what each of them then says. On
			// the scratch library for the same reason as 41 and 42: with a material that has
			// no cut setting the cut-out answers with its refusal, which is the right
			// behaviour and the wrong picture for this page — the refusal has its own
			// paragraph in the handbook. Nothing here writes a board; the preview route only
			// plans.
			const material = await birchWithCutSetting();
			await scene('43-board-extras.png', '/?tab=design', { selector: '.schakelaars' }, async (page) => {
				await page.locator(TOOL.testgrid).click();
				await page.waitForSelector(DIALOG, { timeout: 10000 });
				const picker = page
					.locator(`${DIALOG} label:has(span:text-is("Material")) select`)
					.first();
				await picker.selectOption(String(material.id));
				await page.waitForTimeout(1200);
				// `setChecked` and not `check`: 41 and 42 leave boards on this material whose
				// settings the form adopts, so either switch may already be on.
				await page.locator('.schakelaars label:has-text("QR code") input').setChecked(true);
				await page
					.locator('.schakelaars label:has-text("Cut the board loose") input')
					.setChecked(true);
				// The preview is debounced by 250 ms and then has to come back; every line
				// under both switches is a number out of that answer.
				await page.waitForTimeout(2500);
				await page.locator('.schakelaars').scrollIntoViewIfNeeded();
			});
		}
		if (wanted('44')) {
			// Coming back with a plank in your hand: the way in, and the list that leads
			// with the board's own name. The board is written for this shot because the
			// picture is *about* that line — a library with no boards shows an empty
			// picker, which is the one state this page does not need explaining.
			//
			// No photograph is handed over here, deliberately: doing that needs a JPEG
			// with a real code in it, and a synthetic board photograph in `docs/images`
			// would be half a megabyte of evidence for a plank nobody burned. What the
			// answer looks like is a sentence in the handbook instead, quoted from the
			// catalogue.
			await clear();
			await boardOn({ code_enabled: true, uid: '7X4MQB2K' });
			// A taller window, so the whole panel is inside the dialog: at 900 px the panel
			// runs past the dialog's bottom edge, and a clip in page coordinates then
			// photographs the page behind it (measured — the first take carried the status
			// bar's "Machine not connected" under a picture about finding a board).
			await scene(
				'44-board-readback.png',
				'/?tab=design',
				{ selector: '.resultaat', height: 1250 },
				async (page) => {
					await page.locator(TOOL.testgrid).click();
					await page.waitForSelector(DIALOG, { timeout: 10000 });
					// The panel loads its list on mount and the board was made a moment
					// ago; 800 ms is the round trip, not a guess about rendering.
					await page.waitForTimeout(800);
					// The board is chosen, because a closed `<select>` reading "Choose a
					// grid…" hides the one thing this picture is of: the line leads with
					// the name that is engraved on the plank. A select cannot be
					// photographed open, so the chosen state is the only way to show it.
					await page.locator('.picker').selectOption({ index: 1 });
					await page.waitForTimeout(400);
					// Scrolled last, and to the panel rather than to the way in: choosing
					// a board makes the panel taller, and a clip is in page coordinates —
					// scroll first and the picture catches the page *behind* the dialog
					// (measured: the status bar's "Machine not connected" under a picture
					// about finding a board).
					await page.locator('.resultaat').scrollIntoViewIfNeeded();
					await page.waitForTimeout(600);
				}
			);
		}
	}
}

// ──────────────────────────────────────────────────────────────── leaving tidy
//
// Back to the drawing of section 3. A run ends the way it began, so opening the app
// after taking screenshots does not land you in the middle of a tiling experiment.
if (!only) await seed();

await browser.close();

/**
 * 13-queue.png is deliberately not in this script.
 *
 * A picture of the queue needs a job in the spooler of the active machine, and the
 * only way to put one there is `/api/job/start` — which plans the drawing and hands
 * it to the machine. The machine here is a real Ruida over the network that
 * reopens its connection by itself within seconds; starting a job to take a
 * photograph could set a laser going in an empty room. Nothing in a documentation
 * script is worth that. Faking it by rewriting the status stream in the browser
 * would produce a picture of a machine state that never happened, which is worse
 * than not having the picture.
 */
console.log(`\n${done.length} shots in ${OUT}`);
for (const name of done) console.log('  ' + name);
