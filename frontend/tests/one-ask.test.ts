/**
 * One ask row: the buttons that end a question stand in one place, in one order.
 *
 * Run: `node --test frontend/tests/one-ask.test.ts`
 *
 * Why it exists. A question was drawn five ways. `UnsavedChanges.svelte` put its
 * primary *first*: Save, Discard, Cancel, left to right — measured at 1440, Save at
 * x 680.9 and Cancel at x 838.6, in the one dialog where the wrong reflex costs the
 * work. The layer fold's confirmation sat left-aligned with 101.8 px of empty panel to
 * the right of it; the sheet's confirmation was right-aligned with 12 px; the status
 * bar asked "Disconnect?" with the confirming verb on the left and *Leave it* on the
 * right; the recovery window put Discard first and Restore last. Four orders and two
 * alignments for one kind of row.
 *
 * So there is one row now, `.ask-actions` in `tokens.css`, and one order in it:
 *
 *   the way out first, the answer that destroys in the middle, the primary last.
 *
 * `Dialog.svelte` renders that row as its `footer` snippet — under a rule, outside the
 * body that scrolls — and a component that cannot reach the footer (it is a child
 * inside somebody else's dialog) wears the same class on a row of its own.
 *
 * What is checked here is the source; `ask-rows.test.ts` measures the same rows on
 * screen.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const lib = join(here, '..', 'src', 'lib');
const routes = join(here, '..', 'src', 'routes');
const tokens = readFileSync(join(lib, 'tokens.css'), 'utf8');

function svelteFiles(dir: string, found: string[] = []): string[] {
	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		const path = join(dir, entry.name);
		if (entry.isDirectory()) svelteFiles(path, found);
		else if (entry.name.endsWith('.svelte')) found.push(path);
	}
	return found;
}

const files = [...svelteFiles(join(lib, 'components')), ...svelteFiles(routes)];
const source = new Map(files.map((path) => [path, readFileSync(path, 'utf8')]));
const markup = (text: string) => text.replace(/<style>[\s\S]*<\/style>/, '');

/**
 * The keys of a way out: the answer that leaves everything as it was.
 *
 * `common.close` is not one of them. A window whose only button is Close is answered by
 * that button, and it is the primary there.
 */
const WAY_OUT = ['common.cancel', 'recovery.later', 'status.disconnect.keep'];

/**
 * The windows and confirmations this pattern covers.
 *
 * The scan below finds `<div class="actions">` in fifteen more places — the setup
 * wizard's five pages, PhoneView, StarterOffer, MaterialLibrary, NotificationCard,
 * SeriesRun and TileRun. They are rows of the same kind and were not in this pattern's
 * measurements; bringing one in is adding a line here.
 */
const COVERED = [
	'components/UnsavedChanges.svelte',
	'components/CornersDialog.svelte',
	'components/Offset.svelte',
	'components/StencilDialog.svelte',
	'components/TextDialog.svelte',
	'components/CameraCalibration.svelte',
	'components/SheetMaterial.svelte',
	'components/SheetTabs.svelte',
	'components/Projects.svelte',
	'components/DesignPanel.svelte',
	'components/StatusBar.svelte',
	'components/JobControls.svelte',
	'../routes/+page.svelte'
];

test('the ask row is defined in tokens.css and nowhere else', () => {
	const block = /^\.ask-actions \{[\s\S]*?^\}/m.exec(tokens)?.[0] ?? '';
	assert.ok(block, 'no .ask-actions in tokens.css');
	for (const property of ['display: flex', 'justify-content: flex-end', 'gap:'])
		assert.ok(block.includes(property), `the shared ask row does not set ${property}`);
	// A component may say where its row sits; what it may not do is lay it out again.
	const offenders: string[] = [];
	for (const [path, text] of source) {
		const style = /<style>([\s\S]*)<\/style>/.exec(text)?.[1] ?? '';
		if (/\.ask-actions[^{]*\{[^}]*justify-content/.test(style))
			offenders.push(relative(lib, path));
	}
	assert.deepEqual(offenders, [], `these lay the ask row out again: ${offenders.join(', ')}`);
});

/** Every `class="… ask-actions …"` element in the markup, with the buttons inside it. */
type Row = { file: string; buttons: { classes: string; key: string }[] };

function askRows(): Row[] {
	const rows: Row[] = [];
	for (const [path, text] of source) {
		const body = markup(text);
		const opener = /<(div|span|footer)[^>]*class="[^"]*\bask-actions\b[^"]*"[^>]*>/g;
		let match: RegExpExecArray | null;
		while ((match = opener.exec(body))) {
			const tag = match[1];
			// Walk to the matching close tag, counting nested ones of the same name.
			let depth = 1;
			const scan = new RegExp(`<${tag}\\b|</${tag}>`, 'g');
			scan.lastIndex = opener.lastIndex;
			let end = body.length;
			let step: RegExpExecArray | null;
			while (depth > 0 && (step = scan.exec(body))) {
				depth += step[0].startsWith('</') ? -1 : 1;
				if (depth === 0) end = step.index;
			}
			const inside = body.slice(opener.lastIndex, end);
			const buttons = [...inside.matchAll(/<button([\s\S]*?)<\/button>/g)].map((b) => ({
				classes: /class="([^"]*)"/.exec(b[1])?.[1] ?? '',
				key: [...b[1].matchAll(/t\('([a-zA-Z0-9._]+)'/g)].map((k) => k[1]).join(' ')
			}));
			rows.push({ file: relative(lib, path), buttons });
		}
	}
	return rows;
}

test('every ask row is filled: the way out first, the primary last', () => {
	const rows = askRows();
	const wrong: string[] = [];
	for (const row of rows) {
		if (row.buttons.length < 2) continue;
		const first = row.buttons[0];
		const last = row.buttons[row.buttons.length - 1];
		const isWayOut = (b: { key: string }) => WAY_OUT.some((k) => b.key.split(' ').includes(k));
		if (row.buttons.some(isWayOut) && !isWayOut(first))
			wrong.push(`${row.file}: the way out is not the first button (${row.buttons.map((b) => b.key).join(' | ')})`);
		if (isWayOut(last))
			wrong.push(`${row.file}: the way out is the last button (${row.buttons.map((b) => b.key).join(' | ')})`);
	}
	assert.deepEqual(wrong, [], wrong.join('\n'));
	assert.ok(rows.length >= 10, `only ${rows.length} ask rows found — the scan is broken`);
});

test('no window this pattern covers draws a button row of its own', () => {
	const wrong: string[] = [];
	for (const [path, text] of source) {
		const name = relative(lib, path);
		if (!COVERED.includes(name)) continue;
		const body = markup(text);
		for (const match of body.matchAll(/<div class="(answers|buttons|actions)"[^>]*>/g))
			wrong.push(`${name}: <div class="${match[1]}">`);
	}
	assert.deepEqual(wrong, [], `rows outside the shared one: ${wrong.join(', ')}`);
});

test('every dialog that ends in buttons puts them in the window footer', () => {
	const wrong: string[] = [];
	for (const [path, text] of source) {
		const name = relative(lib, path);
		if (!COVERED.includes(name)) continue;
		const body = markup(text);
		if (!/<Dialog[\s>]/.test(body)) continue;
		// The Projects window is not a question: it is a list you browse, and its
		// confirmations stand inline on the row they are about. Its footer would sit a
		// window's height away from the name it names.
		if (name === 'components/Projects.svelte') continue;
		if (!body.includes('{#snippet footer()}'))
			wrong.push(`${name} opens a Dialog and answers it in the body`);
	}
	assert.deepEqual(wrong, [], wrong.join(', '));
});

test('the running job has no button rule left over from the four-button grid', () => {
	const job = source.get(join(lib, 'components', 'JobControls.svelte'))!;
	const style = /<style>([\s\S]*)<\/style>/.exec(job)?.[1] ?? '';
	assert.ok(
		!/\.btn\.stop\s*\{/.test(style),
		'.btn.stop still carries the grid-column and margin-top of the removed four-button grid'
	);
	// Stop stands where the code says it stands: to the left of pause, not on the
	// spot the green start button had a moment earlier.
	const row = /<div class="now-actions">([\s\S]*?)<\/div>/.exec(markup(job))?.[1] ?? '';
	assert.ok(row, 'no now-actions row in JobControls');
	assert.ok(
		row.indexOf('control.stop()') < row.indexOf('control.pause()'),
		'stop is not the first button in the running row'
	);
});
