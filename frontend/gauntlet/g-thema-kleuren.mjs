/**
 * D2 / L6 — de tien laagkleuren, gemeten in de drie gangbare vormen van
 * kleurenblindheid.
 *
 * c6 kijkt alleen naar deuteranopie. Deze meter doet er protanopie en
 * tritanopie bij, want laag 4 botste bij protanopie harder (21,9) dan bij
 * deuteranopie (24,4) — en dan repareer je met c6 in de hand het verkeerde.
 * Daarnaast: haalt elke kleur nog 3:1 tegen het bed, en is het nummer op het
 * vakje leesbaar?
 *
 * De kleuren komen uit het echte scherm (getComputedStyle op :root), niet uit
 * een lijst in dit bestand — anders meet je je eigen aanname.
 *
 * Gebruik: OK_BASE=... node gauntlet/g-thema-kleuren.mjs
 */
import { browser, open, report, reset } from './harness.mjs';
import { eisScherm, eisHeleBuild } from './g-thema-guard.mjs';

const DREMPEL = 28;

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const lum = (c) => {
	const k = c.map((v) => {
		const s = v / 255;
		return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * k[0] + 0.7152 * k[1] + 0.0722 * k[2];
};
const cr = (a, b) => {
	const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
	return (x + 0.05) / (y + 0.05);
};
// Dezelfde benaderingen als c6-a11y voor deuteranopie, met de twee andere
// vormen ernaast (Brettel/Viénot).
const sims = {
	deuteranopie: ([r, g, b]) => [0.625 * r + 0.375 * g, 0.7 * r + 0.3 * g, 0.3 * g + 0.7 * b],
	protanopie: ([r, g, b]) => [0.567 * r + 0.433 * g, 0.558 * r + 0.442 * g, 0.242 * g + 0.758 * b],
	tritanopie: ([r, g, b]) => [0.95 * r + 0.05 * g, 0.433 * g + 0.567 * b, 0.475 * g + 0.525 * b]
};
const afstand = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

const findings = [];
const b = await browser();
const per = {};

for (const theme of ['light', 'dark']) {
	await reset();
	const page = await open(b, { width: 1440, theme, path: '/?tab=layers' });
	const later = await page.$('button:has-text("Later")');
	if (later) await later.click().catch(() => {});
	await eisScherm(page, '.topbar', `lagenpaneel (${theme})`);
	await eisHeleBuild(page);
	per[theme] = await page.evaluate(() => {
		const s = getComputedStyle(document.documentElement);
		return {
			lagen: Array.from({ length: 10 }, (_, i) => s.getPropertyValue(`--layer-${i + 1}`).trim()),
			bed: s.getPropertyValue('--bed').trim()
		};
	});
	await page.context().close();
}
await b.close();

// De reeks is per afspraak in beide thema's gelijk; dat controleren we ook.
if (per.light.lagen.join() !== per.dark.lagen.join()) {
	findings.push({
		severity: 'major',
		what: 'De laagkleuren verschillen per thema',
		evidence: `licht ${per.light.lagen.join(' ')} | donker ${per.dark.lagen.join(' ')}`
	});
}

const lagen = per.light.lagen;
console.log('laagkleuren uit het scherm:', lagen.join(' '));

for (const [naam, f] of Object.entries(sims)) {
	const botsingen = [];
	let laagste = { d: Infinity };
	for (let i = 0; i < 10; i++) {
		for (let j = i + 1; j < 10; j++) {
			const d = afstand(f(hex(lagen[i])), f(hex(lagen[j])));
			if (d < laagste.d) laagste = { d, paar: `${i + 1}/${j + 1}` };
			if (d < DREMPEL) botsingen.push(`laag ${i + 1} en ${j + 1} (${d.toFixed(1)})`);
		}
	}
	console.log(
		naam.padEnd(14),
		`laagste afstand ${laagste.d.toFixed(1)} bij lagen ${laagste.paar}`,
		botsingen.length ? `| botsingen: ${botsingen.join(', ')}` : '| geen botsingen'
	);
	if (botsingen.length) {
		findings.push({
			severity: 'minor',
			what: `Laagkleuren lopen door elkaar bij ${naam}`,
			evidence: botsingen.join(' | ')
		});
	}
}

console.log('\nkleur tegen het bed (grens 3:1) en het nummer op het vakje (grens 4,5:1):');
for (let i = 0; i < 10; i++) {
	const kleur = hex(lagen[i]);
	const rij = [];
	for (const t of ['light', 'dark']) rij.push(`${t} ${cr(kleur, hex(per[t].bed)).toFixed(2)}`);
	const nummer = Math.max(cr(kleur, [255, 255, 255]), cr(kleur, [0, 0, 0]));
	console.log(
		`  laag ${String(i + 1).padEnd(2)} ${lagen[i]}`,
		rij.join('  ').padEnd(28),
		`nummer ${nummer.toFixed(2)}`,
		nummer < 4.5 ? ' <<< geen inkt haalt AA' : ''
	);
	if (nummer < 4.5) {
		findings.push({
			severity: 'major',
			what: `Het nummer op laagvakje ${i + 1} is met geen enkele inkt leesbaar`,
			evidence: `${lagen[i]}: wit ${cr(kleur, [255, 255, 255]).toFixed(2)}, zwart ${cr(kleur, [0, 0, 0]).toFixed(2)}`
		});
	}
}

report('D2/L6 — laagkleuren bij kleurenblindheid', findings);
