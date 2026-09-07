/**
 * NumberField: does the label hang off the input, or off the minus button?
 *
 * Run: `node --test frontend/tests/numberfield.test.ts`.
 *
 * Why it exists: the `<label>` wrapped the − button, the input *and* the +
 * button. HTML then picks the *first* labelable descendant as the associated
 * control, and that is the − button. Two consequences, both measured in Chrome:
 *   - clicking the words "Width (mm)" lowered the width by one step;
 *   - the input had no accessible name at all ("textbox: 609.6").
 *
 * The component is rendered server-side, so the test needs no browser and no
 * running engine. The one thing it does need is `t()`, and that lives behind the
 * `$lib` alias which only the bundler resolves — so the import is swapped for a
 * small stub over the real English catalogue. That keeps the aria labels in this
 * test the same words a reader gets.
 */
import { test, before } from 'node:test';
import assert from 'node:assert/strict';
import { compile } from 'svelte/compiler';
import { render } from 'svelte/server';
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, '..', 'src', 'lib', 'components', 'NumberField.svelte');
// Compile inside the frontend tree, or the compiled module cannot find `svelte`
// from a temporary directory outside node_modules.
const work = join(here, '.tmp');

const STUB = `
import { en } from '../../src/lib/i18n/en.ts';
export function t(key, vars = {}) {
	const message = en[key] ?? key;
	const text = typeof message === 'string' ? message : message.other;
	return text.replace(/\\{(\\w+)\\}/g, (_, name) => String(vars[name] ?? ''));
}
`;

/** The two `$lib` aliases the component imports, pointed at real files. */
const resolved = (code: string) =>
	code
		.replace(/'\$lib\/i18n\/index\.svelte'/g, "'./i18n-stub.js'")
		.replace(/'\$lib\/numbers'/g, "'../../src/lib/numbers.ts'");

let html = '';

before(async () => {
	const out = compile(readFileSync(source, 'utf8'), { generate: 'server', name: 'NumberField' });
	mkdirSync(work, { recursive: true });
	writeFileSync(join(work, 'i18n-stub.js'), STUB);
	const file = join(work, 'NumberField.js');
	writeFileSync(file, resolved(out.js.code));
	const mod = await import(file + '?t=' + Date.now());
	html = render(mod.default, { props: { label: 'Width', unit: 'mm', value: '500' } }).body;
	rmSync(work, { recursive: true, force: true });
});

test('the label points with for= at the input, not at a button', () => {
	const labelFor = html.match(/<label[^>]*\bfor="([^"]+)"/)?.[1];
	assert.ok(labelFor, `no <label for=…> found in:\n${html}`);
	const inputId = html.match(/<input[^>]*\bid="([^"]+)"/)?.[1];
	assert.equal(inputId, labelFor, 'the id of the input should equal label for=');
});

test('the label does not wrap the step buttons', () => {
	const label = html.match(/<label\b[\s\S]*?<\/label>/)?.[0] ?? '';
	assert.ok(label, 'no <label> found');
	assert.ok(!/<button/.test(label), `a button sits inside the label:\n${label}`);
	assert.ok(!/<input/.test(label), `the input sits inside the label:\n${label}`);
});

test('label and unit are still there for the reader', () => {
	assert.match(html, /Width/);
	assert.match(html, /\(mm\)/);
});

test('the step buttons keep a name of their own', () => {
	assert.match(html, /aria-label="Decrease Width"/);
	assert.match(html, /aria-label="Increase Width"/);
});

/**
 * Tabbing goes from value to value.
 *
 * Measured before this fix, with Playwright starting from the "Columns" field in
 * the generator window: input → "Increase Columns" → "Decrease Rows" → input →
 * "Increase Rows" → … Three tabs per field, and two of them are buttons you did
 * not want to reach.
 *
 * The buttons may leave the tab order only because their work can be done on the
 * field itself: arrow up and down step, exactly as on an ordinary
 * `<input type=number>`, whose spinner is not focusable either. They keep their
 * names and stay clickable.
 */
test('the step buttons are not in the tab order', () => {
	const buttons = html.match(/<button[^>]*>/g) ?? [];
	assert.equal(buttons.length, 2, `expected two buttons, got:\n${html}`);
	for (const button of buttons) {
		assert.match(button, /tabindex="-1"/, `this button still catches a Tab:\n${button}`);
	}
});

test('the input does stay an ordinary tab stop', () => {
	const field = html.match(/<input\b[^>]*>/)?.[0] ?? '';
	assert.ok(field, 'no input found');
	assert.ok(!/tabindex/.test(field), `the field should be in the tab order:\n${field}`);
	assert.ok(!/\bdisabled\b/.test(field), field);
});

/**
 * Home and End write nothing.
 *
 * The box is `type="text"` with `inputmode="decimal"`, so in it Home means what it means
 * in every other text box: the caret before the first digit — the key you press to
 * correct the 1 of "142.5". While the component answered it by writing its own `min`,
 * that one keystroke in the width of a 60 × 40 mm rectangle left the shape 0.1 × 0.067 mm
 * on the bed, committed, with no refusal and no sentence; End in the image DPI (max 2000)
 * did the same at the other end. The arrows step, which is all an `<input type=number>`
 * ever gave the keyboard.
 *
 * The pressing itself is measured in `one-number-field.test.ts` against a running server;
 * this case stands here so the two branches cannot come back unnoticed in the component.
 */
test('the keyboard handler has no Home or End branch', () => {
	const code = readFileSync(source, 'utf8');
	const handler = code.match(/function onKey\([\s\S]*?\n\t\}/)?.[0] ?? '';
	assert.ok(handler, 'no onKey found');
	assert.ok(!/'Home'|"Home"/.test(handler), `Home still writes a value:\n${handler}`);
	assert.ok(!/'End'|"End"/.test(handler), `End still writes a value:\n${handler}`);
});

/**
 * A caller may name its own steps.
 *
 * "Increase Angle in degrees" is wrong in substance on a selection whose shapes sit at
 * different angles: the field is empty and shows "—", and the button turns each shape by
 * a degree. The panel passes the words the two loose −1 / +1 buttons carried.
 */
test('a step label from the caller reaches both buttons', async () => {
	const out = compile(readFileSync(source, 'utf8'), { generate: 'server', name: 'NumberField' });
	mkdirSync(work, { recursive: true });
	writeFileSync(join(work, 'i18n-stub.js'), STUB);
	const file = join(work, 'Named.js');
	writeFileSync(file, resolved(out.js.code));
	const mod = await import(file + '?t=' + Date.now());
	const named = render(mod.default, {
		props: {
			label: '∠',
			value: '',
			unit: '°',
			compact: true,
			stepLabel: (direction: number) => ({
				title: `Rotate ${direction > 0 ? '+1' : '-1'}°`,
				aria: `Rotate ${direction > 0 ? '+1' : '-1'} degrees`
			})
		}
	}).body;
	rmSync(work, { recursive: true, force: true });
	assert.match(named, /aria-label="Rotate -1 degrees"/);
	assert.match(named, /aria-label="Rotate \+1 degrees"/);
	assert.match(named, /title="Rotate -1°"/);
	assert.match(named, /title="Rotate \+1°"/);
});
