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
import { mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE = process.env.OK_BASE ?? 'http://localhost:5199';
const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/docs/images';
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
 * An empty bed, one sheet, no recovery file.
 *
 * The recovery file is the reason this exists: leave one behind and the next run
 * opens with a dialog over the screen asking whether to restore it, and every
 * picture after that has a modal in it. That cost the i18n round a set of shots.
 */
async function clear() {
	await fetch(BASE + '/api/design/autosave', { method: 'DELETE' }).catch(() => {});
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

async function shot(name, page, { selector = null, pad = 0 } = {}) {
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
	await page.screenshot({ path: join(OUT, name), clip });
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
await scene('04-setup-settings.png', '/setup/settings?machine=ruida');

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
