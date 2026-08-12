/**
 * D7 — elke plek waar de merkkleur tekst is, nagemeten.
 *
 * Niet in de bron tellen maar in het beeld meten: loop over alle zichtbare
 * elementen met tekst, pak de berekende `color`, zoek het eerste voorouder-
 * vlak dat écht een kleur heeft, en reken het contrast uit. Alles wat op de
 * accentkleur (of de accent-tekstkleur) staat, komt in de lijst — dus ook de
 * plekken die niemand had aangewezen.
 *
 * Grens: 4,5:1, of 3,0:1 vanaf 18,66px (of 14px vet), conform WCAG AA.
 *
 * Gebruik: OK_BASE=... node gauntlet/g-thema-accent.mjs
 */
import { browser, open, report, reset } from './harness.mjs';
import { eisScherm, eisHeleBuild } from './g-thema-guard.mjs';

const findings = [];
const b = await browser();

/** De schermen waar accenttekst voorkomt, plus de vensters die je moet openen. */
const schermen = [
	{ naam: 'werkgebied · bewerken', path: '/?tab=design' },
	{ naam: 'werkgebied · lagen', path: '/?tab=layers' },
	{ naam: 'werkgebied · job', path: '/?tab=job' },
	{ naam: 'wizard · soort', path: '/setup/soort' },
	{ naam: 'wizard · instellen', path: '/setup/instellen?machine=ruida' },
	{ naam: 'wizard · klaar', path: '/setup/klaar' }
];
const vensters = [
	['materiaalbibliotheek', 'button[title="Materiaalbibliotheek"]'],
	['presetariat', 'button[title^="Presetariat"]'],
	['generatoren', 'button[title^="Generatoren"]'],
	['clipart', 'button[title^="Clipart"]'],
	['testraster', 'button[title="Testraster"]']
];

const meting = `(() => {
	const parse = (s) => {
		const m = String(s).match(/rgba?\\(\\s*([\\d.]+)[\\s,]+([\\d.]+)[\\s,]+([\\d.]+)(?:[\\s,/]+([\\d.]+))?/);
		return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null;
	};
	const lum = (c) => {
		const k = c.slice(0, 3).map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
		return 0.2126 * k[0] + 0.7152 * k[1] + 0.0722 * k[2];
	};
	const ratio = (a, c) => { const [x, y] = [lum(a), lum(c)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
	const over = (fg, bg) => [0, 1, 2].map((i) => fg[i] * fg[3] + bg[i] * (1 - fg[3]));
	const root = getComputedStyle(document.documentElement);
	const accent = parse(root.getPropertyValue('--accent').trim().startsWith('#')
		? (() => { const h = root.getPropertyValue('--accent').trim(); return 'rgb(' + [1,3,5].map((i) => parseInt(h.slice(i, i+2), 16)).join(',') + ')'; })()
		: root.getPropertyValue('--accent'));
	// Achtergrond: klim omhoog tot een vlak dat niet doorzichtig is, en stapel
	// de doorzichtige lagen die je onderweg tegenkomt op elkaar.
	const achter = (el) => {
		const stapel = [];
		for (let n = el; n; n = n.parentElement) {
			const c = parse(getComputedStyle(n).backgroundColor);
			if (!c || c[3] === 0) continue;
			stapel.push(c);
			if (c[3] === 1) break;
		}
		let kleur = stapel.pop() ?? [255, 255, 255, 1];
		while (stapel.length) kleur = [...over(stapel.pop(), kleur), 1];
		return kleur;
	};
	const uit = [];
	for (const el of document.querySelectorAll('*')) {
		const r = el.getBoundingClientRect();
		if (r.width < 1 || r.height < 1) continue;
		const tekst = [...el.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim()).map((n) => n.textContent.trim()).join(' ');
		if (!tekst) continue;
		const s = getComputedStyle(el);
		const kleur = parse(s.color);
		if (!kleur) continue;
		// Alleen de accentkleur interesseert ons hier.
		if (Math.abs(kleur[0] - accent[0]) + Math.abs(kleur[1] - accent[1]) + Math.abs(kleur[2] - accent[2]) > 6) continue;
		const bg = achter(el);
		const px = parseFloat(s.fontSize);
		const vet = parseInt(s.fontWeight, 10) >= 700;
		const groot = px >= 18.66 || (vet && px >= 14);
		uit.push({
			tekst: tekst.slice(0, 28),
			cls: String(el.className?.baseVal ?? el.className ?? '').slice(0, 24),
			px, groot,
			bg: 'rgb(' + bg.slice(0, 3).map((v) => Math.round(v)).join(' ') + ')',
			cr: +ratio(kleur, bg).toFixed(2),
			grens: groot ? 3 : 4.5
		});
	}
	return uit;
})()`;

let totaal = 0;
const gezakt = [];

for (const theme of ['light', 'dark']) {
	for (const scherm of schermen) {
		await reset();
		const page = await open(b, { width: 1440, theme, path: scherm.path });
		const later = await page.$('button:has-text("Later")');
		if (later) await later.click().catch(() => {});
		// Poort: sta ik op het scherm dat ik denk te meten, en is de build heel?
		await eisScherm(page, scherm.path.startsWith('/setup') ? '.setup' : '.topbar', `${scherm.naam} (${theme})`);
		if (scherm === schermen[0]) await eisHeleBuild(page);
		const rijen = await page.evaluate(meting);
		totaal += rijen.length;
		for (const r of rijen) if (r.cr < r.grens) gezakt.push({ ...r, waar: `${scherm.naam} (${theme})` });

		// Vensters alleen op het werkgebied.
		if (scherm.path.startsWith('/?')) {
			for (const [naam, sel] of vensters) {
				const knop = await page.$(sel);
				if (!knop) continue;
				await knop.click();
				await page.waitForTimeout(700);
				const extra = await page.evaluate(meting);
				totaal += extra.length;
				for (const r of extra) if (r.cr < r.grens) gezakt.push({ ...r, waar: `${naam} (${theme})` });
				await page.keyboard.press('Escape');
				await page.waitForTimeout(300);
			}
		}
		await page.context().close();
	}
}

console.log(`accentteksten gemeten: ${totaal} | onder de grens: ${gezakt.length}`);
for (const g of gezakt.slice(0, 20)) {
	console.log(`  ${g.cr} (grens ${g.grens}) "${g.tekst}" .${g.cls} ${g.px}px op ${g.bg} — ${g.waar}`);
}
if (gezakt.length) {
	findings.push({
		severity: 'major',
		what: `${gezakt.length} van ${totaal} accentteksten onder de contrastgrens`,
		evidence: gezakt.slice(0, 6).map((g) => `${g.cr}:1 "${g.tekst}" (${g.waar})`).join(' | ')
	});
}
report('D7 — de merkkleur als tekst', findings);
await b.close();
