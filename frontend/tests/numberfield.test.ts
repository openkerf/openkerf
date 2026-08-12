/**
 * NumberField: hangt het label aan het invoerveld, of aan de min-knop?
 *
 * Draaien: `node --test frontend/tests/numberfield.test.ts`.
 *
 * De aanleiding: `<label>` omvatte de −-knop, het invoerveld én de +-knop. HTML
 * kiest dan de *eerste* labelbare afstammeling als bijbehorende control, en dat
 * is de −-knop. Twee gevolgen, beide gemeten in Chrome:
 *   - klikken op het woord "Breedte (mm)" verlaagde de breedte met één stap;
 *   - het invoerveld had geen toegankelijke naam ("textbox: 609.6").
 *
 * De component wordt server-side gerenderd, zodat de test geen browser en geen
 * draaiende engine nodig heeft.
 */
import { test, before } from 'node:test';
import assert from 'node:assert/strict';
import { compile } from 'svelte/compiler';
import { render } from 'svelte/server';
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const hier = dirname(fileURLToPath(import.meta.url));
const bron = join(hier, '..', 'src', 'lib', 'components', 'NumberField.svelte');
// Binnen de frontend-boom compileren, anders vindt de gecompileerde module
// `svelte` niet vanuit een tijdelijke map buiten node_modules.
const werkmap = join(hier, '.tmp');

let html = '';

before(async () => {
	const uit = compile(readFileSync(bron, 'utf8'), { generate: 'server', name: 'NumberField' });
	mkdirSync(werkmap, { recursive: true });
	const bestand = join(werkmap, 'NumberField.js');
	writeFileSync(bestand, uit.js.code);
	const mod = await import(bestand + '?t=' + Date.now());
	html = render(mod.default, { props: { label: 'Breedte', unit: 'mm', value: '500' } }).body;
	rmSync(werkmap, { recursive: true, force: true });
});

test('het label wijst met for= naar het invoerveld, niet naar een knop', () => {
	const labelFor = html.match(/<label[^>]*\bfor="([^"]+)"/)?.[1];
	assert.ok(labelFor, `geen <label for=…> gevonden in:\n${html}`);
	const inputId = html.match(/<input[^>]*\bid="([^"]+)"/)?.[1];
	assert.equal(inputId, labelFor, 'het id van het invoerveld hoort gelijk te zijn aan label for=');
});

test('het label omvat de stapknoppen niet', () => {
	const label = html.match(/<label\b[\s\S]*?<\/label>/)?.[0] ?? '';
	assert.ok(label, 'geen <label> gevonden');
	assert.ok(!/<button/.test(label), `een knop staat binnen het label:\n${label}`);
	assert.ok(!/<input/.test(label), `het invoerveld staat binnen het label:\n${label}`);
});

test('label en eenheid staan er nog steeds voor de lezer', () => {
	assert.match(html, /Breedte/);
	assert.match(html, /\(mm\)/);
});

test('de stapknoppen houden hun eigen naam', () => {
	assert.match(html, /aria-label="Breedte verlagen"/);
	assert.match(html, /aria-label="Breedte verhogen"/);
});
