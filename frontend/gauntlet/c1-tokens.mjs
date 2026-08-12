/**
 * Criticus 1 — de tokenpolitie.
 *
 * DESIGN-SYSTEM.md als wet: kleuren uit tokens, spacing op het 4px-grid,
 * radius 6/10/999, drie fontrollen, en de kerflijn alleen op de drie
 * toegestane plekken.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { browser, open, report, reset } from './harness.mjs';

const SRC = new URL('../src', import.meta.url).pathname;

function walk(dir) {
	return readdirSync(dir).flatMap((name) => {
		const path = join(dir, name);
		return statSync(path).isDirectory() ? walk(path) : [path];
	});
}

const files = walk(SRC).filter((f) => /\.(svelte|css|ts)$/.test(f));
const findings = [];

// --- hardcoded kleuren buiten het tokenbestand
const hexes = [];
for (const file of files) {
	if (file.endsWith('tokens.css')) continue;
	const text = readFileSync(file, 'utf8');
	const lines = text.split('\n');
	for (const [index, line] of lines.entries()) {
		// Een blok dat zichzelf @tokens-mirror noemt, is een bewuste spiegel van
		// tokens.css met de bron in CSS. Uitzonderingen horen gemarkeerd te
		// staan, niet stilzwijgend door de vingers gezien te worden.
		if (lines.slice(Math.max(0, index - 4), index).join(' ').includes('@tokens-mirror')) continue;
		// Een kleurcode die je in een commentaarregel noemt, is uitleg en geen
		// stijl. Deze meter sloeg aan op de zin die uitlegt waarom #0000ff00
		// onbruikbaar is — dat is de meter die de fout in gaat, niet de code.
		const kaal = line.trim();
		if (kaal.startsWith('//') || kaal.startsWith('*') || kaal.startsWith('/*')) continue;
		// Een HTML-entiteit is geen kleurcode. `&#8239;` — de smalle vaste ruimte
		// tussen een getal en zijn eenheid — las deze meter als #8239 en meldde
		// dus een hardcoded kleur die niet bestaat.
		const zonderEntiteiten = line.replace(/&#[0-9a-fA-F]+;/g, '');
		for (const m of zonderEntiteiten.matchAll(/#[0-9a-fA-F]{3,8}\b/g)) {
			hexes.push({ file: file.slice(SRC.length + 1), line: index + 1, value: m[0], src: line.trim().slice(0, 70) });
		}
	}
}
if (hexes.length) {
	findings.push({
		severity: 'major',
		what: `${hexes.length} hardcoded kleurwaarden buiten tokens.css`,
		evidence: hexes.slice(0, 8).map((h) => `${h.file}:${h.line} ${h.value} — ${h.src}`).join(' | ')
	});
}

// --- radius buiten 6/10/999
const radii = [];
for (const file of files) {
	if (file.endsWith('tokens.css')) continue;
	const text = readFileSync(file, 'utf8');
	for (const [index, line] of text.split('\n').entries()) {
		const m = line.match(/border-radius:\s*([^;]+);/);
		if (!m) continue;
		const value = m[1].trim();
		if (/var\(--radius/.test(value)) continue;
		if (/^(999px|50%|inherit|0)$/.test(value)) continue;
		radii.push(`${file.slice(SRC.length + 1)}:${index + 1} ${value}`);
	}
}
if (radii.length) {
	findings.push({
		severity: 'minor',
		what: `${radii.length} border-radius buiten de tokens`,
		evidence: radii.slice(0, 8).join(' | ')
	});
}

// --- spacing buiten het 4px-grid
const spacing = [];
const GRID = new Set([0, 1, 2, 4, 8, 12, 16, 24, 32, 40, 48]);
for (const file of files) {
	if (file.endsWith('tokens.css')) continue;
	const text = readFileSync(file, 'utf8');
	for (const [index, line] of text.split('\n').entries()) {
		const m = line.match(/^\s*(padding|margin|gap|row-gap|column-gap)(-[a-z]+)?:\s*([^;]+);/);
		if (!m) continue;
		for (const raw of m[3].split(/\s+/)) {
			const px = raw.match(/^(-?\d+(?:\.\d+)?)px$/);
			if (!px) continue;
			const value = Math.abs(+px[1]);
			if (!GRID.has(value)) {
				spacing.push(`${file.slice(SRC.length + 1)}:${index + 1} ${m[1]}: ${raw}`);
			}
		}
	}
}
if (spacing.length) {
	findings.push({
		severity: 'minor',
		what: `${spacing.length} spacing-waarden buiten het 4px-grid`,
		evidence: spacing.slice(0, 10).join(' | ')
	});
}

// --- fontgroottes buiten de schaal 11/13/15/18/24
const sizes = [];
const SCALE = new Set(['11px', '13px', '15px', '18px', '24px']);
for (const file of files) {
	if (file.endsWith('tokens.css')) continue;
	const text = readFileSync(file, 'utf8');
	const rows = text.split('\n');
	for (const [index, line] of rows.entries()) {
		const m = line.match(/font-size:\s*([^;]+);/);
		if (!m) continue;
		const value = m[1].trim();
		if (/var\(--text/.test(value) || value === 'inherit') continue;
		// @svg-space: tekst binnen een SVG die in millimeters rekent, niet in
		// CSS-pixels. Die hoort niet op de typeschaal.
		if (rows.slice(Math.max(0, index - 5), index).join(' ').includes('@svg-space')) continue;
		if (!SCALE.has(value)) sizes.push(`${file.slice(SRC.length + 1)}:${index + 1} ${value}`);
	}
}
if (sizes.length) {
	findings.push({
		severity: 'major',
		what: `${sizes.length} fontgroottes buiten de schaal 11/13/15/18/24`,
		evidence: sizes.slice(0, 10).join(' | ')
	});
}

// --- v3.3 (D9): --line is een randkleur, geen inkt en geen vulling
//
// Het token is afgestemd op de oppervlakken: als tekst haalt het 1,41 in licht
// en 1,84 in donker, en als vulling onder tekst zakte --text-2 erop naar 4,05
// respectievelijk 3,49. Toegestaan is dus `border`, `outline`, `stroke` en
// `box-shadow` — plus een haarlijn die als blokje getekend wordt, en die
// herken je aan een breedte of hoogte van een paar pixels in hetzelfde blok.
// Wat overblijft is de echte fout: --line als tekstkleur, of als vlak dat
// oplicht onder de muis. Daarvoor bestaat sinds v3.3 --hover.
const lijnmisbruik = [];
for (const file of files) {
	if (file.endsWith('tokens.css')) continue;
	const text = readFileSync(file, 'utf8');
	const rows = text.split('\n');
	for (const [index, line] of rows.entries()) {
		const kaal = line.trim();
		if (kaal.startsWith('//') || kaal.startsWith('*') || kaal.startsWith('/*')) continue;
		const plaats = `${file.slice(SRC.length + 1)}:${index + 1}`;
		if (/(^|[^-])color:\s*var\(--line\)/.test(line)) {
			lijnmisbruik.push(`${plaats} als tekstkleur — ${kaal.slice(0, 50)}`);
			continue;
		}
		if (!/background(-color)?:\s*var\(--line\)/.test(line)) continue;
		// Het omringende blok terugzoeken: van de vorige `{` tot de volgende `}`.
		let start = index;
		while (start > 0 && !rows[start].includes('{')) start--;
		let eind = index;
		while (eind < rows.length - 1 && !rows[eind].includes('}')) eind++;
		const blok = rows.slice(start, eind + 1).join(' ');
		const haarlijn = /(width|height|inline-size|block-size):\s*[1-4]px/.test(blok);
		const hover = /:hover|:focus|:active/.test(rows[start]);
		if (haarlijn && !hover) continue;
		lijnmisbruik.push(`${plaats} als vulling — ${rows[start].trim().slice(0, 40)}`);
	}
}
if (lijnmisbruik.length) {
	findings.push({
		severity: 'major',
		what: `${lijnmisbruik.length}× --line gebruikt als inkt of vulling in plaats van als rand`,
		evidence: lijnmisbruik.slice(0, 8).join(' | ')
	});
}

// --- de kerflijn: aantal plekken
const kerf = [];
for (const file of files) {
	const text = readFileSync(file, 'utf8');
	if (/kerf-anim|stroke-dasharray:\s*6 4|dasharray="6 4"/.test(text)) {
		const hits = [...text.matchAll(/kerf-anim|dasharray[:=]"?\s*6 4/g)].length;
		kerf.push(`${file.slice(SRC.length + 1)} (${hits}x)`);
	}
}

// --- in de browser: mono met tabulaire cijfers voor numerieke waarden
await reset();
const b = await browser();
const page = await open(b, { width: 1440 });
const numeric = await page.$$eval('*', (nodes) =>
	nodes
		.filter((n) => {
			if (n.children.length) return false;
			const t = (n.textContent ?? '').trim();
			// Een waarde: bevat een getal en is kort. Losse cijfers in tekst niet.
			return /^[-+]?\d[\d.,:]*\s*(mm|mm\/s|%|s|px|°|×|x)?$/i.test(t) && t.length < 16;
		})
		.map((n) => {
			const s = getComputedStyle(n);
			return {
				text: n.textContent.trim().slice(0, 14),
				mono: /Plex Mono|monospace/i.test(s.fontFamily),
				tabular: /tabular-nums/.test(s.fontVariantNumeric),
				cls: String(n.className ?? '').slice(0, 30)
			};
		})
);
const notMono = numeric.filter((n) => !n.mono);
const notTabular = numeric.filter((n) => n.mono && !n.tabular);
if (notMono.length) {
	findings.push({
		severity: 'major',
		what: `${notMono.length} van ${numeric.length} numerieke waarden staan niet in mono`,
		evidence: notMono.slice(0, 8).map((n) => `"${n.text}" (.${n.cls})`).join(' | ')
	});
}
if (notTabular.length) {
	findings.push({
		severity: 'major',
		what: `${notTabular.length} mono-waarden zonder tabulaire cijfers`,
		evidence: notTabular.slice(0, 6).map((n) => `"${n.text}" (.${n.cls})`).join(' | ')
	});
}

console.log('kerflijn-vindplaatsen:', kerf.join(' | ') || 'geen');
report('Criticus 1 — tokenpolitie', findings);
await b.close();
