/**
 * One system: the component layer in tokens.css is the only place its patterns are drawn.
 *
 * Run: `node --test frontend/tests/one-system.test.ts`
 *
 * The critique of 2026-10-11 counted the dialects above the tokens: the input well
 * pasted eighteen times, the section label fourteen, help text in thirty-five local
 * classes, a coloured stripe on the left of thirty-three notices, ten ways to draw a
 * disabled control, five undefined tokens that silently dropped a border or a padding,
 * and the kerf line — the one motion that means "the laser is burning" — running on the
 * logo and under the tabs. Each check below refuses one of those coming back. A
 * component may still say where a thing sits, how wide it is and what it holds; what
 * it may not do is draw the shared face again.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');
const tokens = readFileSync(join(src, 'lib', 'tokens.css'), 'utf8');

function files(dir: string, ends: string[], found: string[] = []): string[] {
	for (const entry of readdirSync(dir, { withFileTypes: true })) {
		const path = join(dir, entry.name);
		if (entry.isDirectory()) files(path, ends, found);
		else if (ends.some((end) => entry.name.endsWith(end))) found.push(path);
	}
	return found;
}

const svelte = files(src, ['.svelte']);
const name = (path: string) => relative(src, path);

/** The `<style>` block of a component with its comments taken out. */
function style(path: string): string {
	const source = readFileSync(path, 'utf8');
	const at = source.indexOf('<style');
	if (at < 0) return '';
	return source
		.slice(at)
		.replace(/<style[^>]*>/, '')
		.replace(/\/\*[\s\S]*?\*\//g, '');
}

/** The markup of a component: everything outside script and style. */
function markup(path: string): string {
	return readFileSync(path, 'utf8')
		.replace(/<script[\s\S]*?<\/script>/g, '')
		.replace(/<style[\s\S]*?<\/style>/g, '')
		.replace(/<!--[\s\S]*?-->/g, '');
}

/** Every `selector { body }` in a style block, nested at-rules flattened. */
function rules(css: string): Array<{ selector: string; body: string }> {
	return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
		selector: m[1].trim(),
		body: m[2]
	}));
}

test('every token a component reads is defined', () => {
	const defined = new Set([...tokens.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));
	const offenders: string[] = [];
	for (const path of files(src, ['.svelte', '.css', '.ts'])) {
		const source = readFileSync(path, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
		const local = new Set([...source.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));
		// Also custom properties set from markup: `style:--x=` and `style="--x: …"`.
		for (const m of source.matchAll(/style:(--[\w-]+)/g)) local.add(m[1]);
		for (const m of source.matchAll(/var\((--[\w-]+)(\s*,)?/g)) {
			if (m[2]) continue; // a fallback is written beside it on purpose
			if (m[1].endsWith('-')) continue; // a name finished from markup: `--dialog-{size}`
			if (!defined.has(m[1]) && !local.has(m[1])) offenders.push(`${name(path)}: ${m[1]}`);
		}
	}
	assert.deepEqual([...new Set(offenders)], [], `undefined tokens: ${[...new Set(offenders)].join(' | ')}`);
});

test('no coloured stripe on the side of a box', () => {
	const offenders: string[] = [];
	for (const path of svelte) {
		for (const { selector, body } of rules(style(path))) {
			if (/border-(left|right|inline-start|inline-end)(-width)?\s*:\s*([2-9]|\d{2,})px/.test(body))
				offenders.push(`${name(path)}: ${selector}`);
		}
	}
	assert.deepEqual(offenders, [], `side stripes — use Notice or .badge: ${offenders.join(' | ')}`);
});

test('the section label is drawn in one place', () => {
	const offenders: string[] = [];
	for (const path of svelte) {
		for (const { selector, body } of rules(style(path))) {
			if (/text-transform\s*:\s*uppercase/.test(body)) offenders.push(`${name(path)}: ${selector}`);
		}
	}
	assert.deepEqual(offenders, [], `local section labels — use .label-section: ${offenders.join(' | ')}`);
});

test('help text has one class', () => {
	const LOCAL = /\.(hint|muted|fine|tip|note|uitleg|stip|why|explain|caption)\b/;
	const offenders: string[] = [];
	for (const path of svelte) {
		for (const { selector } of rules(style(path))) {
			if (selector.startsWith('@')) continue;
			if (LOCAL.test(selector)) offenders.push(`${name(path)}: ${selector}`);
		}
	}
	assert.deepEqual(offenders, [], `local help classes — use .help or <Why>: ${offenders.join(' | ')}`);
});

/**
 * The well is `:where(input, select, textarea)` in tokens.css. NumberField and Segmented
 * are the shared controls that build on it, so they may shape their own parts.
 */
const CONTROLS = ['lib/components/NumberField.svelte', 'lib/components/Segmented.svelte'];

test('no component draws the input well again', () => {
	const WELL = ['border:', 'background', 'padding', 'border-radius'];
	const offenders: string[] = [];
	for (const path of svelte) {
		if (CONTROLS.includes(name(path))) continue;
		for (const { selector, body } of rules(style(path))) {
			const tails = selector.split(',').map((one) => one.trim().split(/[\s>+~]+/).pop() ?? '');
			if (!tails.some((tail) => /^(input|select|textarea)\b/.test(tail))) continue;
			const sets = WELL.filter((property) => body.includes(property));
			if (sets.length >= 3) offenders.push(`${name(path)}: ${selector}`);
		}
	}
	assert.deepEqual(offenders, [], `the well drawn again: ${offenders.join(' | ')}`);
});

test('a disabled control is drained, not faded', () => {
	const offenders: string[] = [];
	for (const path of svelte) {
		for (const { selector, body } of rules(style(path))) {
			const off = selector.replace(/:not\([^)]*\)/g, '');
			if (/:disabled|\[disabled\]|\[aria-disabled/.test(off) && /opacity\s*:\s*(?!1\s*[;}]|1$)/.test(body))
				offenders.push(`${name(path)}: ${selector}`);
		}
	}
	assert.deepEqual(offenders, [], `faded disabled states: ${offenders.join(' | ')}`);
});

test('colours, radii and type sizes come from the tokens', () => {
	const offenders: string[] = [];
	for (const path of svelte) {
		for (const { selector, body } of rules(style(path))) {
			if (/#[0-9a-f]{3,8}\b|\brgba?\(|\bhsla?\(/i.test(body)) offenders.push(`${name(path)}: ${selector} (colour)`);
			if (/\b999px\b/.test(body)) offenders.push(`${name(path)}: ${selector} (999px)`);
			if (/font-size\s*:\s*[\d.]+px/.test(body)) offenders.push(`${name(path)}: ${selector} (font-size)`);
			if (/accent-color\s*:/.test(body)) offenders.push(`${name(path)}: ${selector} (accent-color)`);
		}
	}
	assert.deepEqual(offenders, [], `raw values: ${offenders.join(' | ')}`);
});

test('motion takes its duration from the tokens', () => {
	const offenders: string[] = [];
	for (const path of svelte) {
		for (const { selector, body } of rules(style(path))) {
			if (/(transition|animation)[\w-]*\s*:[^;]*\b\d+m?s\b/.test(body))
				offenders.push(`${name(path)}: ${selector}`);
		}
	}
	assert.deepEqual(offenders, [], `raw durations: ${offenders.join(' | ')}`);
});

/**
 * The kerf line means "the laser is working". It runs on the progress of a job and
 * nowhere else; on the logo and under a tab it was decoration, and it taught the eye
 * to stop seeing it.
 */
test('the kerf line runs only on the progress of a job', () => {
	const offenders: string[] = [];
	for (const path of svelte) {
		for (const m of markup(path).matchAll(/class="([^"]*\bkerf-anim\b[^"]*)"/g)) {
			if (!/\bjob-progress\b/.test(m[1])) offenders.push(`${name(path)}: ${m[1]}`);
		}
	}
	assert.deepEqual(offenders, [], `kerf line as decoration: ${offenders.join(' | ')}`);
});

test('icons are drawn, not typed', () => {
	const offenders: string[] = [];
	for (const path of svelte) {
		for (const m of markup(path).matchAll(/>\s*([×⋯…↑↓›‹▸▾●✕✓])\s*</g))
			offenders.push(`${name(path)}: ${m[1]}`);
	}
	assert.deepEqual(offenders, [], `glyphs as icons — use <Icon>: ${offenders.join(' | ')}`);
});
