/**
 * The handbook: every picture there, every link real, every quotation true.
 *
 * Run: `node --test frontend/tests/docs.test.ts`
 *
 * The pages in `docs/` quote the interface. That is what makes them worth
 * reading and what makes them rot: a label is renamed in `en.ts`, the sentence
 * in the handbook keeps promising the old one, and a reader looks for a button
 * that is not there any more. Prose cannot be type-checked, but a quotation can
 * be looked up.
 *
 * Six things are checked.
 *
 *  1. Every `images/...` a page points at exists, and every file in
 *     `docs/images/` is pointed at by some page. An unused screenshot is one
 *     nobody noticed going stale.
 *  2. Every link to another page resolves, heading anchors included.
 *  3. Every sentence the pages quote from the interface is really in the English
 *     catalogue. `{placeholders}` count as wildcards, because a page writes
 *     "{sheet} holds {what}" where the app fills in names.
 *  4. Every operation in `actions.ts` is named somewhere in `docs/`, **by the
 *     label the interface shows** — read through the catalogue exactly as
 *     `actions.ts` reads it. Checking the internal id would prove nothing: a
 *     reader never sees it, and a renamed label would slip straight through.
 *  5. Every shortcut in `KEYS` stands in a key table in `docs/reference.md`, in
 *     the Mac notation or the Windows one. Both are written there, side by side.
 *  6. Every tab of the right-hand panel and every window the interface can open
 *     is named on at least one page.
 *
 * Only quotations long enough to be a claim are checked (from QUOTE_MIN
 * characters). Shorter ones are ordinary words in ordinary sentences — "the
 * bed", "on" — and checking those would make the test noise rather than a
 * guard.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
	KEYS,
	canvasMenu,
	historyActions,
	layerMenu,
	objectMenu,
	type Context,
	type Handlers,
	type LayerContext,
	type LayerHandlers,
	type Menu,
	type MenuItem
} from '../src/lib/actions.ts';
import { en } from '../src/lib/i18n/en.ts';

const here = dirname(fileURLToPath(import.meta.url));
const DOCS = join(here, '..', '..', 'docs');
const IMAGES = join(DOCS, 'images');
const EN = join(here, '..', 'src', 'lib', 'i18n', 'en.ts');
const ENGINE = join(here, '..', '..', 'api', 'openkerf_api');

const QUOTE_MIN = 30;

const pages = readdirSync(DOCS).filter((name) => name.endsWith('.md'));
const read = (name: string) => readFileSync(join(DOCS, name), 'utf8');

/** Every string literal in the English catalogue, flattened to one haystack. */
const catalogue = (() => {
	// Comments go first: an apostrophe in "the user's language" would otherwise
	// pair with the next quotation mark and shift every literal after it.
	const source = readFileSync(EN, 'utf8')
		.replace(/\/\*[\s\S]*?\*\//g, '')
		.replace(/^[\t ]*\/\/[^\n]*$/gm, '');
	const parts: string[] = [];
	for (const match of source.matchAll(/'((?:[^'\\\n]|\\.)*)'/g)) {
		parts.push(match[1].replace(/\\'/g, "'"));
	}
	return parts;
})();

/**
 * The engine's own sentences.
 *
 * The refusals a laser cutter actually meets — a tile that falls outside the bed,
 * a jog while a job runs — are written in the API layer and not in the
 * catalogue, because they also reach curl, scripts and logs. The pages quote
 * them, so they belong in the haystack. Python glues neighbouring literals
 * together, so a run of them is read as one sentence.
 */
const engine = (() => {
	const parts: string[] = [];
	for (const file of readdirSync(ENGINE).filter((name) => name.endsWith('.py'))) {
		const source = readFileSync(join(ENGINE, file), 'utf8');
		for (const run of source.matchAll(/(?:[fr]?"(?:[^"\\\n]|\\.)*"\s*)+/g)) {
			const joined = [...run[0].matchAll(/"((?:[^"\\\n]|\\.)*)"/g)]
				.map((m) => m[1])
				.join('');
			parts.push(joined.replace(/\\"/g, '"'));
		}
	}
	return parts;
})();

/**
 * One canonical form for both sides.
 *
 * The pages write out what the app fills in — "3 layers use settings…" where the
 * catalogue says "{n} layers use settings…" — so a number and a placeholder are
 * the same thing here, and so are a straight and a curly quotation mark. What is
 * left is the wording, which is what a rename changes.
 */
function canonical(text: string): string {
	return text
		.replace(/[‘’]/g, "'")
		.replace(/[“”]/g, '"')
		.replace(/\{[^{}]*\}/g, '§')
		.replace(/[\d.,]*\d/g, '§')
		.replace(/[*_`]/g, '')
		.replace(/\s+/g, ' ')
		.replace(/(§ ?)+/g, '§')
		.trim()
		.toLowerCase();
}

const haystack = [...catalogue, ...engine].map(canonical);

/**
 * Does this quotation come from that message?
 *
 * A page quotes a fragment of a message and writes out what the app fills in, so
 * neither side is the whole of the other: "outside Sheet 1" stands where the
 * message says "outside {sheet}". The § stands for whatever was filled in, on
 * either side, and matching it as a wildcard in both directions catches a
 * reworded label while letting a faithful quotation through.
 */
function quotes(value: string, quotation: string): boolean {
	if (value.includes(quotation)) return true;
	const loose = (text: string) =>
		new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/§/g, '.*?'));
	return loose(value).test(quotation) || loose(quotation).test(value);
}

test('every picture a page points at exists', () => {
	const missing: string[] = [];
	for (const page of pages) {
		for (const match of read(page).matchAll(/\]\((images\/[^)]+)\)/g)) {
			try {
				readFileSync(join(DOCS, match[1]));
			} catch {
				missing.push(`${page} → ${match[1]}`);
			}
		}
	}
	assert.deepEqual(missing, []);
});

test('every picture in docs/images is used by a page', () => {
	const all = pages.map(read).join('\n');
	const unused = readdirSync(IMAGES).filter((file) => !all.includes(`images/${file}`));
	assert.deepEqual(unused, []);
});

test('every link between the pages resolves', () => {
	const headings = new Map<string, Set<string>>();
	for (const page of pages) {
		const anchors = new Set<string>();
		for (const match of read(page).matchAll(/^#+ +(.+)$/gm)) {
			anchors.add(
				match[1]
					.toLowerCase()
					.replace(/[^\w\s-]/g, '')
					.trim()
					.replace(/\s+/g, '-')
			);
		}
		headings.set(page, anchors);
	}
	const broken: string[] = [];
	for (const page of pages) {
		for (const match of read(page).matchAll(/\]\(([a-z0-9-]+\.md)(#[^)]+)?\)/g)) {
			const [, target, anchor] = match;
			if (!headings.has(target)) {
				broken.push(`${page} → ${target}`);
			} else if (anchor && !headings.get(target)!.has(anchor.slice(1))) {
				broken.push(`${page} → ${target}${anchor}`);
			}
		}
	}
	assert.deepEqual(broken, []);
});

/** The paragraphs of a page, with pictures, links and blockquote marks removed. */
function paragraphs(page: string): string[] {
	return read(page)
		.replace(/!\[[^\]]*\]\([^)]*\)/g, '')
		.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
		.split(/\n\s*\n/)
		.map((block) =>
			block
				.split('\n')
				.map((line) => line.replace(/^\s*>\s?/, ''))
				.join(' ')
		);
}

test('every sentence the pages quote is in the English catalogue', () => {
	const wrong: string[] = [];
	for (const page of pages) {
		for (const block of paragraphs(page)) {
			// A paragraph with an odd number of quotation marks holds an apostrophe
			// this test cannot tell from a quotation. Pairing would be guesswork, so
			// it is left alone.
			if ((block.match(/"/g) ?? []).length % 2 !== 0) continue;
			for (const match of block.matchAll(/"([^"]+)"/g)) {
				const wanted = canonical(match[1]);
				if (wanted.length < QUOTE_MIN) continue;
				if (!haystack.some((value) => quotes(value, wanted))) {
					wrong.push(`${page}: "${match[1]}"`);
				}
			}
		}
	}
	assert.deepEqual(
		wrong,
		[],
		`${wrong.length} quotation(s) not found in en.ts:\n${wrong.join('\n')}`
	);
});

// ─── What the app can do, and whether a page says so ─────────────────────────
//
// The three checks above test the pages against themselves and against the
// wording of a message. The three below test them against the app's own list of
// operations, shortcuts, tabs and windows — the drift that hurts most, because
// nothing on the page looks wrong. A row gets a better name, a shortcut moves to
// another key, a window is renamed, and the page keeps describing a version of
// the app that has been gone for months.
//
// Two deliberate softenings, so these stay honest rather than merely strict:
//
//   - A label that bends to a count ("Select the shape in this layer" / "Select
//     the 3 shapes in this layer") or to a state ("Fill — for rastering" /
//     "Remove fill") passes when *one* of its wordings appears. Demanding every
//     number would be demanding nonsense.
//   - Rows built from the reader's own work — a layer name, a sheet name, a shape
//     under the pointer — carry no fixed label and are skipped. They are marked
//     with the id `DATA` in the wide context below, so the skip is exact and not
//     a guess at a prefix.

/**
 * A page reduced to its words.
 *
 * Two things go: the markup, because `**Layers** tab` reads as "Layers tab"; and
 * the line breaks, because a page wraps at eighty columns and a name can be
 * split across two lines. Without the second, this test claimed that "Work from
 * an earlier session" was undocumented while it stood in `getting-started.md`
 * with the wrap between "Work" and "from".
 */
const words = (text: string) => text.replace(/[*_`]/g, '').replace(/\s+/g, ' ');

/** All the pages as one haystack. */
const prose = words(pages.map(read).join('\n'));

const NOTHING = () => {};
const HANDLERS = new Proxy({}, { get: () => NOTHING }) as Handlers & LayerHandlers;

/**
 * A state in which nothing is greyed out and every row appears: three shapes
 * selected, inside a group, an image that is also text and is also cropped.
 * Impossible in the app, on purpose — the point is to collect every row that
 * exists, not to build a menu anyone will see.
 */
const WIDE: Context = {
	count: 3,
	inGroup: true,
		lockedCount: 0,
	isImage: true,
	isText: true,
	isCropped: true,
	filled: false,
	bridges: { carries: true, has: false },
	clipboard: 2,
	busy: false,
	may: true,
	layers: [{ id: 'DATA', label: 'A layer of the reader', inside: true }],
	sheets: [{ id: 'DATA', name: 'A sheet of the reader' }],
	snap: true,
	layerNumbers: true,
	empty: false,
	splittable: { shapes: 0, pieces: 0 },
	under: [
		{ id: 'DATA1', label: 'Rectangle', selected: true },
		{ id: 'DATA2', label: 'Circle', selected: false }
	]
};

const LAYER: LayerContext = {
	label: 'Outline',
	shapeCount: 1,
	burns: true,
	visible: true,
	first: false,
	last: false,
	selection: 2,
	inside: false,
	may: true
};

/** Every row of a menu, submenus included. */
function menuRows(menu: Menu): MenuItem[] {
	const out: MenuItem[] = [];
	for (const group of menu)
		for (const item of group.items) {
			if (item === 'separator') continue;
			out.push(item);
			if ('items' in item) out.push(...item.items);
		}
	return out;
}

/**
 * Every operation the app offers, with every wording it can carry.
 *
 * The menus are built more than once, because some rows change their words with
 * the state: "Paste" becomes "Paste here" over a point, "Fill — for rastering"
 * becomes "Remove fill" on a filled shape, "Split into separate shapes" becomes
 * "Split into 7 shapes", and the layer row counts its shapes. One of the wordings
 * on a page is enough.
 */
function operations(): Map<string, Set<string>> {
	const found = new Map<string, Set<string>>();
	const add = (id: string, label: string) => {
		if (!found.has(id)) found.set(id, new Set());
		found.get(id)!.add(label);
	};

	for (const over of [
		{},
		{ filled: true },
		{ splittable: { shapes: 2, pieces: 7 } }
	] as Partial<Context>[]) {
		const ctx = { ...WIDE, ...over };
		for (const row of menuRows(objectMenu(ctx, HANDLERS))) add(row.id, row.label);
		for (const at of [null, { x: 10, y: 10 }])
			for (const row of menuRows(canvasMenu(ctx, HANDLERS, at))) add(row.id, row.label);
		for (const row of historyActions(ctx, HANDLERS)) add(row.id, row.label);
	}
	// The menu on a layer row, in both directions and with one shape and with
	// several, so the singular and the plural wording are both on offer.
	for (const over of [{}, { inside: true }, { shapeCount: 4 }] as Partial<LayerContext>[])
		for (const row of menuRows(layerMenu({ ...LAYER, ...over }, HANDLERS))) add(row.id, row.label);

	// The rows made out of the reader's own layers, sheets and pile of shapes.
	for (const id of [...found.keys()]) if (/^(layer|sheet|under)-DATA/.test(id)) found.delete(id);

	// If the menus stop building, every check below passes on nothing.
	assert.ok(found.size >= 60, `only ${found.size} operations read from actions.ts`);
	return found;
}

/** Where an operation of this kind probably belongs, for the failure message. */
function operationBelongsOn(id: string): string {
	if (id.startsWith('layer')) return 'docs/layers.md';
	if (id.startsWith('zoom-') || id === 'snap' || id === 'rescue') return 'docs/canvas.md';
	if (id.startsWith('bool-') || id.startsWith('path-')) return 'docs/shapes-and-generators.md';
	if (id === 'sheet') return 'docs/tiling.md';
	return 'docs/canvas.md';
}

test('every operation the app offers is named on a page, by its name on the screen', () => {
	const missing: string[] = [];
	for (const [id, labels] of operations()) {
		const wordings = [...labels];
		if (wordings.some((label) => prose.includes(words(label)))) continue;
		missing.push(
			`"${wordings.join('" / "')}" is on no page — it belongs on ` +
				`${operationBelongsOn(id)} and in the operation table in docs/reference.md`
		);
	}
	assert.deepEqual(missing, [], `\n${missing.join('\n')}\n`);
});

/**
 * The key notations that stand in a table in `reference.md`.
 *
 * The table writes both notations in one cell — "⌘Z / Ctrl+Z" — so the cell is
 * split on the slash. Reading them out of the table rather than searching the
 * page matters: a bare "." or "," occurs in every other sentence, and a check
 * that a full stop appears somewhere in the prose checks nothing at all.
 */
function keyTable(): Set<string> {
	const out = new Set<string>();
	for (const line of read('reference.md').split('\n')) {
		if (!line.startsWith('|')) continue;
		const cell = line.split('|')[1] ?? '';
		if (/^[\s:-]*$/.test(cell)) continue; // the ---|--- rule under a header row
		for (const part of words(cell).split('/')) {
			const token = part.trim().replace(/−/g, '-'); // − is a minus sign, - a hyphen
			if (token) out.add(token);
		}
	}
	assert.ok(out.size >= 20, `only ${out.size} key notations read from reference.md`);
	return out;
}

/**
 * "mod+shift+z" as a Mac shows it.
 *
 * Written out here instead of imported from `keyLabel()`: that function picks one
 * notation from the platform it happens to run on, and the page carries both. A
 * test that only holds on a Mac is not a test.
 */
function macKeys(combo: string): string {
	const parts = combo.split('+');
	const last = parts.pop() ?? '';
	const core = last === 'delete' ? '⌫' : last.length === 1 ? last.toUpperCase() : last;
	const sign: Record<string, string> = { mod: '⌘', shift: '⇧', alt: '⌥' };
	return parts.map((part) => sign[part] ?? part).join('') + core;
}

/** The same combination as Windows and Linux show it. */
function winKeys(combo: string): string {
	const parts = combo.split('+');
	const last = parts.pop() ?? '';
	const core = last === 'delete' ? 'Del' : last.length === 1 ? last.toUpperCase() : last;
	const sign: Record<string, string> = { mod: 'Ctrl', shift: 'Shift', alt: 'Alt' };
	return [...parts.map((part) => sign[part] ?? part), core].join('+');
}

test('every shortcut stands in a key table in the reference', () => {
	const table = keyTable();
	const missing: string[] = [];
	for (const combo of new Set(Object.values(KEYS))) {
		const mac = macKeys(combo);
		const win = winKeys(combo);
		if (table.has(mac) || table.has(win)) continue;
		missing.push(
			`${mac} (${win} on Windows) is in no key table on docs/reference.md — ` +
				`add a row under the heading it belongs to`
		);
	}
	assert.deepEqual(missing, [], `\n${missing.join('\n')}\n`);
});

/** The English wording of a message. A plural gives its singular. */
function wording(key: string): string {
	const message = (en as Record<string, string | { one: string; other: string }>)[key];
	assert.ok(message, `${key} is not in the English catalogue`);
	return typeof message === 'string' ? message : message.one;
}

/** The tabs of the right-hand panel, read out of the page that builds them. */
function panelTabs(): string[] {
	const source = readFileSync(join(here, '..', 'src', 'routes', '+page.svelte'), 'utf8');
	// `{t('tabs.job')}` — one segment after `tabs.`, which leaves the notification
	// button (`tabs.notifications.on`) out: that is a switch, not a tab.
	const keys = [...new Set([...source.matchAll(/t\('(tabs\.[a-zA-Z]+)'\)/g)].map((m) => m[1]))];
	assert.ok(keys.length >= 3, `only ${keys.length} panel tabs found on the main page`);
	return keys.map(wording);
}

test('every tab of the panel is named on a page', () => {
	const missing: string[] = [];
	for (const label of panelTabs()) {
		// The pages name them the way a reader meets them: "the Layers tab".
		if (new RegExp(`${label}\\s+tab`, 'i').test(prose)) continue;
		missing.push(
			`the ${label} tab is called that on no page — write "the ${label} tab" ` +
				`where the reader first needs it, and list it in docs/reference.md`
		);
	}
	assert.deepEqual(missing, [], `\n${missing.join('\n')}\n`);
});

/**
 * Every window the interface can open, read from the components that build them.
 *
 * A window is a dialog with a title out of the catalogue. The one whose title is
 * an expression instead of a key — "replace what is open?", which reads three
 * ways depending on what you did — is left out: there is no single wording a page
 * could carry.
 */
function windows(): { label: string; key: string }[] {
	const src = join(here, '..', 'src');
	const files: string[] = [];
	const walk = (at: string) => {
		for (const entry of readdirSync(at, { withFileTypes: true })) {
			const full = join(at, entry.name);
			if (entry.isDirectory()) walk(full);
			else if (entry.name.endsWith('.svelte')) files.push(full);
		}
	};
	walk(src);

	const found = new Map<string, string>();
	for (const file of files)
		for (const match of readFileSync(file, 'utf8').matchAll(
			/<Dialog[^>]*\btitle=\{t\('([^']+)'\)\}/g
		))
			found.set(match[1], wording(match[1]));
	assert.ok(found.size >= 8, `only ${found.size} windows found in the components`);
	return [...found].map(([key, label]) => ({ key, label }));
}

/** Where a window of this kind probably belongs, for the failure message. */
function windowBelongsOn(key: string): string {
	if (key.startsWith('library') || key.startsWith('presetariat')) return 'docs/library.md';
	if (key.startsWith('testgrid')) return 'docs/test-grid.md';
	if (key.startsWith('gen') || key === 'text.title' || key === 'clipart.title')
		return 'docs/shapes-and-generators.md';
	if (key.startsWith('preview') || key.startsWith('notifications')) return 'docs/job.md';
	if (key.startsWith('recovery')) return 'docs/getting-started.md';
	return 'docs/reference.md';
}

test('every window the interface can open is named on a page', () => {
	const missing: string[] = [];
	for (const { key, label } of windows()) {
		if (prose.includes(words(label))) continue;
		missing.push(`the "${label}" window is named on no page — it belongs on ${windowBelongsOn(key)}`);
	}
	assert.deepEqual(missing, [], `\n${missing.join('\n')}\n`);
});
