/**
 * Het bed heeft een eigen familie — en die wordt hier nagerekend.
 *
 * Gemeld door de pre-flight: in v3.2 was `--bed` in donker exact dezelfde kleur
 * als `--surface-2` (1,00:1) en haalde geen enkel token meer dan 1,23:1
 * tegenover het bed. Daardoor kón je het materiaalvel niet met een vlak
 * afbakenen. Deze meter houdt drie dingen vast:
 *
 * 1. Er is minstens één token dat tegenover `--bed` een zichtbaar verschil
 *    geeft. "Zichtbaar" meten we in L* en niet in contrastverhouding: bij een
 *    luminantie van 0,01 zegt 1,10 niets over wat het oog ziet. Ondergrens 3 L*,
 *    dezelfde orde als de kleinste stap in de oppervlaktrap.
 * 2. Het bed blijft los van het podium eronder, anders verdwijnt de bedrand.
 * 3. De tien laagkleuren blijven op de bedvloer *buiten* het vel minstens even
 *    goed leesbaar als op het bed zelf. Dat is de reden dat `--bed-off` de
 *    donkere kant op gaat en niet de vulling van het vel is: het vel vullen kost
 *    laagkleuren hun 3:1, en juist ín het vel ligt het werk.
 *
 * Gebruik: OK_BASE=... node gauntlet/g-thema-bed.mjs
 */
import { browser, open, report, reset } from './harness.mjs';
import { eisScherm, eisHeleBuild } from './g-thema-guard.mjs';

const STAP_MIN = 3;

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
const Lster = (c) => {
	const y = lum(c);
	return y > 0.008856 ? 116 * Math.cbrt(y) - 16 : 903.3 * y;
};

const findings = [];
const b = await browser();

for (const theme of ['light', 'dark']) {
	await reset();
	const page = await open(b, { width: 1440, theme, path: '/?tab=design' });
	const later = await page.$('button:has-text("Later")');
	if (later) await later.click().catch(() => {});
	await eisScherm(page, '.topbar', `werkgebied (${theme})`);
	await eisHeleBuild(page);

	const t = await page.evaluate(() => {
		const s = getComputedStyle(document.documentElement);
		const pak = (n) => s.getPropertyValue(n).trim();
		// De podiumtop uit het verloop plukken: de eerste kleurstop.
		const stage = pak('--stage');
		const stops = [...stage.matchAll(/#[0-9a-fA-F]{6}/g)].map((m) => m[0]);
		return {
			bed: pak('--bed'),
			bedOff: pak('--bed-off'),
			podium: stops[0] ?? null,
			surface2: pak('--surface-2'),
			line: pak('--line'),
			text2: pak('--text-2'),
			danger: pak('--danger'),
			lagen: Array.from({ length: 10 }, (_, i) => pak(`--layer-${i + 1}`))
		};
	});
	await page.context().close();

	const bed = hex(t.bed);
	console.log(`\n== ${theme}`);
	console.log(`  --bed        ${t.bed}  L* ${Lster(bed).toFixed(1)}`);

	// 1. is er iets met een zichtbaar verschil tegenover het bed?
	const buren = [
		['--bed-off', t.bedOff],
		['--surface-2', t.surface2],
		['--line', t.line],
		['podiumtop', t.podium]
	].filter(([, v]) => /^#[0-9a-fA-F]{6}$/.test(v ?? ''));

	let beste = { stap: -1 };
	for (const [naam, waarde] of buren) {
		const stap = Math.abs(Lster(hex(waarde)) - Lster(bed));
		const verhouding = cr(hex(waarde), bed);
		if (naam !== 'podiumtop' && stap > beste.stap) beste = { naam, waarde, stap, verhouding };
		console.log(
			`  ${naam.padEnd(12)} ${waarde}  L*-stap ${stap.toFixed(1).padStart(5)}  contrast ${verhouding.toFixed(2)}`
		);
	}
	if (beste.stap < STAP_MIN) {
		findings.push({
			severity: 'major',
			what: `Geen enkel token tekent zich af tegen --bed in ${theme}`,
			evidence: `beste is ${beste.naam} met ${beste.stap.toFixed(1)} L* (ondergrens ${STAP_MIN}) — een vel is dan niet met een vlak af te bakenen`
		});
	}

	// 2. blijft het bed los van het podium?
	if (t.podium) {
		const tegenPodium = cr(hex(t.podium), bed);
		console.log(`  bed tegen podium: ${tegenPodium.toFixed(2)}`);
		if (tegenPodium < 1.12) {
			findings.push({
				severity: 'minor',
				what: `Het bed komt in ${theme} niet los van het podium`,
				evidence: `${tegenPodium.toFixed(2)}:1 — de bedrand valt weg`
			});
		}
	}

	// 3. laagkleuren op de bedvloer buiten het vel
	const opBed = t.lagen.map((l) => cr(hex(l), bed));
	const opOff = t.lagen.map((l) => cr(hex(l), hex(t.bedOff)));
	const nBed = opBed.filter((r) => r >= 3).length;
	const nOff = opOff.filter((r) => r >= 3).length;
	console.log(
		`  laagkleuren >= 3:1 — op het bed ${nBed}/10, buiten het vel ${nOff}/10` +
			`  | --text-2 buiten het vel ${cr(hex(t.text2), hex(t.bedOff)).toFixed(2)}` +
			`  | --danger ${cr(hex(t.danger), hex(t.bedOff)).toFixed(2)}`
	);
	if (nOff < nBed) {
		// In licht is dit structureel en niet op te lossen: `--bed` is zuiver wit,
		// het lichtste dat er is, dus élke vulling binnen het bed is donkerder en
		// kost de lichtste laagkleuren contrast. Laag 5 (teal) is de enige die van
		// kant wisselt, van 3,07 naar 2,84, en een vorm die buiten het vel ligt
		// krijgt van de pre-flight toch al `--danger` (4,92 hierop). Daarom een nit
		// met de reden erbij in plaats van een minor die om een fix vraagt die niet
		// bestaat. De échte uitweg staat in DESIGN-SYSTEM.md als open punt: het
		// lichte bed van zuiver wit af halen, en dat is een eigen opdracht.
		const gewisseld = t.lagen
			.map((l, i) => [i + 1, opBed[i], opOff[i]])
			.filter(([, a, c]) => a >= 3 && c < 3)
			.map(([n, a, c]) => `laag ${n}: ${a.toFixed(2)} → ${c.toFixed(2)}`);
		findings.push({
			severity: theme === 'light' ? 'nit' : 'minor',
			what: `--bed-off kost ${nBed - nOff} laagkleur(en) de 3:1 in ${theme}`,
			evidence:
				`${nBed}/10 op het bed, ${nOff}/10 erbuiten — ${gewisseld.join(', ')}. ` +
				(theme === 'light'
					? 'Onvermijdelijk zolang --bed zuiver wit is; buiten het vel markeert de pre-flight met --danger.'
					: 'Hier wél op te lossen: kies een --bed-off die verder van de middentonen af ligt.')
		});
	}
}

report('Het bed als eigen familie', findings);
await b.close();
