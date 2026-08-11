/**
 * Criticus 6 — de toegankelijkheidsauditor.
 *
 * Axe op elk scherm, volledige toetsenbordronde, dubbele codering van de
 * laagkleuren, en touch-targets in de PWA-maat.
 */
import AxeBuilder from '@axe-core/playwright';
import { browser, open, report, reset } from './harness.mjs';

await reset();
const b = await browser();
const findings = [];

async function scan(page, waar) {
	const result = await new AxeBuilder({ page })
		.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
		.analyze();
	const serious = result.violations.filter((v) => ['critical', 'serious'].includes(v.impact));
	const rest = result.violations.filter((v) => !['critical', 'serious'].includes(v.impact));
	if (serious.length) {
		findings.push({
			severity: 'major',
			what: `axe: ${serious.length} ernstige overtredingen op ${waar}`,
			evidence: serious.map((v) => `${v.id} (${v.nodes.length}x: ${v.nodes[0]?.target?.join(' ')})`).join(' | ')
		});
	}
	if (rest.length) {
		findings.push({
			severity: 'minor',
			what: `axe: ${rest.length} lichte overtredingen op ${waar}`,
			evidence: rest.map((v) => `${v.id} (${v.nodes.length}x)`).join(' | ')
		});
	}
	return result.violations.length;
}

// --- hoofdscherm, beide thema's
for (const theme of ['light', 'dark']) {
	const page = await open(b, { width: 1440, theme });
	await scan(page, `hoofdscherm (${theme})`);
	await page.context().close();
}

// --- de vensters: elk apart scannen
const page = await open(b, { width: 1440 });
const dialogs = [
	['Materiaalbibliotheek', 'button[title="Materiaalbibliotheek"]'],
	['Presetariat', 'button[title^="Presetariat"]'],
	['Generatoren', 'button[title^="Generatoren"]'],
	['Clipart', 'button[title^="Clipart"]'],
	['Testraster', 'button[title="Testraster"]']
];
for (const [naam, selector] of dialogs) {
	const knop = await page.$(selector);
	if (!knop) {
		findings.push({ severity: 'minor', what: `Venster "${naam}" niet te openen in de test`, evidence: selector });
		continue;
	}
	await knop.click();
	await page.waitForTimeout(500);
	await scan(page, `venster ${naam}`);
	await page.keyboard.press('Escape');
	await page.waitForTimeout(300);
}

// --- toetsenbordronde: bereikbaarheid zonder muis
const reachable = await page.evaluate(() => {
	const focusable = [...document.querySelectorAll(
		'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea, [tabindex]:not([tabindex="-1"])'
	)].filter((n) => n.getBoundingClientRect().width > 0);
	return {
		total: focusable.length,
		unlabelled: focusable
			.filter((n) => {
				const text = (n.textContent ?? '').trim();
				const label = n.getAttribute('aria-label') || n.getAttribute('title') ||
					(n.labels && n.labels.length) || n.getAttribute('alt');
				return !text && !label;
			})
			.map((n) => `${n.tagName.toLowerCase()}.${String(n.className ?? '').slice(0, 24)}`)
			.slice(0, 8)
	};
});
if (reachable.unlabelled.length) {
	findings.push({ severity: 'major', what: `${reachable.unlabelled.length} bedienbare elementen zonder label`,
		evidence: reachable.unlabelled.join(' | ') });
}
console.log('focusbare elementen:', reachable.total);

// --- tabvolgorde: springt hij heen en weer over het scherm?
const order = [];
await page.keyboard.press('Tab');
for (let i = 0; i < 25; i++) {
	const spot = await page.evaluate(() => {
		const el = document.activeElement;
		if (!el || el === document.body) return null;
		const r = el.getBoundingClientRect();
		return { x: Math.round(r.x), y: Math.round(r.y), tag: el.tagName.toLowerCase() };
	});
	if (spot) order.push(spot);
	await page.keyboard.press('Tab');
}
let jumps = 0;
for (let i = 1; i < order.length; i++) {
	// Een sprong van meer dan een halve pagina omhoog is een volgordefout.
	if (order[i].y < order[i - 1].y - 400) jumps++;
}
if (jumps > 1) {
	findings.push({ severity: 'minor', what: 'Tabvolgorde springt over het scherm',
		evidence: `${jumps} sprongen van meer dan 400px omhoog in 25 stappen` });
}

// --- touch-targets in PWA-maat
const small = await open(b, { width: 390 });
const tiny = await small.$$eval('button, a[href], input[type="checkbox"], select', (nodes) =>
	nodes
		.filter((n) => {
			const r = n.getBoundingClientRect();
			return r.width > 0 && (r.width < 40 || r.height < 40);
		})
		.map((n) => {
			const r = n.getBoundingClientRect();
			return `${n.getAttribute('aria-label') || n.textContent?.trim().slice(0, 16) || n.tagName}: ${Math.round(r.width)}x${Math.round(r.height)}`;
		})
		.slice(0, 10)
);
if (tiny.length) {
	findings.push({ severity: 'major', what: `${tiny.length} touch-targets kleiner dan 40px op 390px breed`,
		evidence: tiny.join(' | ') });
}
await small.context().close();

// --- laagkleuren: dubbel gecodeerd en onderscheidbaar bij deuteranopie
const layers = await page.evaluate(() => {
	const style = getComputedStyle(document.documentElement);
	return Array.from({ length: 10 }, (_, i) => style.getPropertyValue(`--layer-${i + 1}`).trim());
});
function deuter([r, g, b]) {
	// Brettel/Viénot-benadering voor deuteranopie.
	return [
		0.625 * r + 0.375 * g + 0.0 * b,
		0.7 * r + 0.3 * g + 0.0 * b,
		0.0 * r + 0.3 * g + 0.7 * b
	];
}
const hexToRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const seen = [];
const collisions = [];
for (const [i, hex] of layers.entries()) {
	if (!/^#[0-9a-f]{6}$/i.test(hex)) continue;
	const d = deuter(hexToRgb(hex));
	for (const [j, other] of seen) {
		const dist = Math.hypot(d[0] - other[0], d[1] - other[1], d[2] - other[2]);
		if (dist < 28) collisions.push(`laag ${j + 1} en ${i + 1} (afstand ${Math.round(dist)})`);
	}
	seen.push([i, d]);
}
console.log('laagkleuren:', layers.filter(Boolean).length, '| botsingen bij deuteranopie:', collisions.length);
if (collisions.length) {
	findings.push({ severity: 'minor', what: 'Laagkleuren lopen door elkaar bij deuteranopie',
		evidence: collisions.slice(0, 4).join(' | ') + ' — het nummer op de chip is het vangnet' });
}

report('Criticus 6 — toegankelijkheid', findings);
await b.close();
