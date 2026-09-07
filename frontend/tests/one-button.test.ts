/**
 * One button, one definition.
 *
 * Run: `node --test frontend/tests/one-button.test.ts`
 *
 * Fifteen components defined a `.btn` of their own. They agreed on the border, the
 * radius, the surface and the weight, and disagreed on the size: `8px 12px` in six,
 * `8px 16px` in five, `var(--space-2) var(--space-4)` — the same 8/16, but as tokens —
 * in two, `6px 12px` with `min-height: 32px` in the starter offer and
 * `0 var(--space-4)` with `min-height: 36px` in a notification. Measured on screen:
 * 32.0, 36.0, 36.8 and 40.0 px, and the first two stand side by side, because the
 * offer sits inside the library window.
 *
 * `tokens.css:574` had noticed and written it down — "Eleven components define a
 * `.btn` of their own" — as a safety net rather than a repair. It was fifteen by the
 * time this round counted.
 *
 * So the button lives in `tokens.css` now, with named exceptions: `.btn.mini` where
 * the room is genuinely gone, `.btn.big` for the one that starts a burn. A component
 * may still say something extra about its own buttons (a `white-space`, a width); what
 * it may not do is start the base again.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const lib = join(here, '..', 'src', 'lib');
const tokens = readFileSync(join(lib, 'tokens.css'), 'utf8');
const components = join(lib, 'components');
const routes = join(here, '..', 'src', 'routes');

/** The properties that make a button a button. Whoever sets these starts a base. */
const BASE = ['border-radius', 'border:', 'background', 'font-weight', 'padding'];

function svelteFiles(dir: string, found: string[] = []): string[] {
	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		const path = join(dir, entry.name);
		if (entry.isDirectory()) svelteFiles(path, found);
		else if (entry.name.endsWith('.svelte')) found.push(path);
	}
	return found;
}

test('the button is defined in tokens.css', () => {
	assert.match(tokens, /^\.btn \{/m, 'no .btn in tokens.css');
	for (const property of BASE) {
		const block = /^\.btn \{[\s\S]*?^\}/m.exec(tokens)?.[0] ?? '';
		assert.ok(block.includes(property), `the shared .btn does not set ${property}`);
	}
	assert.match(tokens, /^\.btn\.primary/m, 'no primary variant in tokens.css');
	assert.match(tokens, /^\.btn\.mini/m, 'no mini variant — then the offer starts its own again');
});

test('no component defines a button of its own', () => {
	const offenders: string[] = [];
	for (const path of [...svelteFiles(components), ...svelteFiles(routes)]) {
		const source = readFileSync(path, 'utf8');
		const style = source.slice(source.indexOf('<style>'));
		// The base block, written exactly as the fifteen wrote it: `.btn {` on its own.
		const block = /\n\t*\.btn \{([\s\S]*?)\n\t*\}/.exec(style);
		if (!block) continue;
		const sets = BASE.filter((property) => block[1].includes(property));
		if (sets.length >= 3) {
			offenders.push(`${path.split('/').pop()}: ${sets.join(', ')}`);
		}
	}
	assert.deepEqual(
		offenders,
		[],
		`components starting the button over again: ${offenders.join(' | ')}`
	);
});

/**
 * And the same button under another name.
 *
 * The first test above matches a literal `.btn {`, so a component that draws the same
 * face and calls it something else walks straight past it. The right-hand panel did
 * that nine times: `.rot`, `.listmore`, `.dichtheid`, `.assign`, `.anchor-back`,
 * `.gone`, `.add` in `DesignPanel.svelte` and `.rot`, `.pf-order`, `.jog` in
 * `JobControls.svelte`. Measured at 1440 they came out at 15.9, 25.9, 29.9, 33.9, 34
 * and 36.8 px, in two typefaces, with *Show cut path* (29.9, 11 px, 400) and
 * *Show frame* (36.8, 13 px, 500) sibling verbs in one card.
 *
 * What is refused here is what makes a button face: border, radius, background and
 * padding in one rule, on a selector that is worn by a `<button>` in that same file.
 * A component may still say something extra about its own buttons — a colour, a
 * width, a place in a grid; what it may not do is start the base again.
 *
 * The two files were the right-hand panel, the surface that round measured. The action
 * bar came in after it, because its `.more` and the panel's `.listmore` are the same
 * thing — a small text button that opens a menu — and the panel's repair did not reach
 * it: measured at 1440 on the Layers tab they stood 595.6 px apart on one screen, at
 * 25.9 px / weight 400 against 32 px / weight 500. Scanned with the same rule, the
 * components still to follow are Clipart, CornersDialog, Generators, JobPreview,
 * LanguagePicker, MaterialLibrary, Menu, PhoneView, Series, SheetMaterial, SheetTabs,
 * StatusBar, TestGridResult, ToolRail and TopBar. Adding a file to the list below is
 * the way to bring one in.
 */
const PANEL = ['DesignPanel.svelte', 'JobControls.svelte', 'ActionBar.svelte'];

/**
 * Two selectors in these files draw a face and are not the button:
 * `.tag.air` is the pill that reports whether air assist is on — a state, in the
 * shape the other tags in that row have — and `.pf-menu .row` is a row in a menu,
 * which the app's menus draw their own way everywhere.
 */
const NOT_A_BUTTON = ['.tag.air', '.pf-menu .row'];

test('no button in the panel or the action bar is drawn under another name', () => {
	const FACE = ['border-radius', 'border:', 'background', 'padding'];
	const offenders: string[] = [];
	for (const name of PANEL) {
		const source = readFileSync(join(components, name), 'utf8');
		const cut = source.indexOf('<style>');
		const markup = source.slice(0, cut);
		const style = source.slice(cut);
		// Every class a `<button>` in this file wears.
		const worn = new Set<string>();
		for (const match of markup.matchAll(/<button\b[^>]*?class="([^"{]*)"/g))
			for (const one of match[1].split(/\s+/).filter(Boolean)) worn.add(one);
		for (const rule of style.matchAll(/\n\t*([^\n{}]+)\{([^{}]*)\}/g)) {
			const selector = rule[1].trim();
			if (selector.startsWith('@') || NOT_A_BUTTON.includes(selector)) continue;
			const aButton = selector
				.split(',')
				.map((one) => one.trim().split(/[\s>]+/).pop() ?? '')
				.some((tail) =>
					tail
						.split(/[.:[]/)
						.filter(Boolean)
						.some((one) => worn.has(one))
				);
			if (!aButton) continue;
			const sets = FACE.filter((property) => rule[2].includes(property));
			if (sets.length === FACE.length) offenders.push(`${name}: ${selector}`);
		}
	}
	assert.deepEqual(
		offenders,
		[],
		`the panel draws the button again under another name: ${offenders.join(' | ')}`
	);
});
