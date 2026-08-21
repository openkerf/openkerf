/**
 * Contrastauditor voor de setup-wizard, in beide thema's.
 *
 * Het punt van dit script is de áchtergrond, niet de tekst. Een badge legt zijn
 * eigen kleur als doorzichtige waas onder zichzelf; wie dan
 * `getComputedStyle(el).backgroundColor` afleest, meet `rgba(…, 0.14)` en
 * vergelijkt tekst met een kleur die niemand ziet. Daarom stapelen we hier de
 * hele voorouderketen op elkaar, van de body omhoog, precies zoals de browser
 * dat doet — inclusief elke doorzichtige laag onderweg.
 */
import { browser, open, BASE } from './harness.mjs';

/** Een echte machine uit de catalogus, zodat de stappen hun scherm tonen. */
const CATALOGUS = 'g3v8-amc';

/**
 * Het pad dat de engine teruggeeft na het aanmaken. Het script set hem zelf
 * neer: zonder machine opent OpenKerf op het welkomstscherm en meet je overal
 * de vangnetpagina in plaats van de wizard.
 */
const MACHINE = await fetch(`${BASE}/api/machines`, {
	method: 'POST',
	headers: { 'Content-Type': 'application/json' },
	body: JSON.stringify({ info: CATALOGUS, label: '5030 CO2' })
})
	.then((r) => r.json())
	.then((m) => m.path)
	.catch(() => 'newly');

/*
 * Twee lijsten, en dat onderscheid is het halve script.
 *
 * Een wizardstap zonder de queryparameter die hij nodig heeft rendert niet het
 * scherm maar de vangnetpagina ernaast: `/setup/done` zonder `?machine=` valt
 * in "Deze machine bestaat niet (meer)", en `/setup/name?type=lhystudios` geeft
 * een leeg naamveld met een uitgeschakelde knop, omdat `lhystudios` een
 * apparaatpad is en geen catalogussleutel. Meet je die, dan meet je de guard en
 * de disabled-staat — allebei het meten waard, geen van beide het scherm waar
 * het label om vraagt. Vandaar twee lijsten met eerlijke namen.
 *
 * Elke route noemt daarnaast een **merkteken**: iets dat alleen op dát scherm
 * staat. Ontbreekt het, dan is de meting ongeldig — ook als de pagina er verder
 * prima uitziet. Dat is strenger dan "staat er geen guard-kop": een route kan
 * ook op een ánder echt scherm landen, met tekst en al, en dan vindt een auditor
 * die alleen op rampen let nog steeds netjes niets.
 */
const ECHT = [
	['overzicht', '/setup', 'Jouw machines'],
	['soort', '/setup/kind', 'Wat voor machine'],
	['type', '/setup/type', /model|type|kies/i],
	['naam', `/setup/name?type=${CATALOGUS}`, 'Geef de machine een naam'],
	['instellen', `/setup/settings?machine=${MACHINE}`, /werkgebied|bed|breedte/i],
	['klaar', `/setup/done?machine=${MACHINE}`, 'staat klaar']
];

const VANGNET = [
	['naam-leeg', '/setup/name?type=lhystudios', 'Geef de machine een naam'],
	['klaar-guard', '/setup/done', 'bestaat niet'],
	['instellen-standaard', '/setup/settings?machine=lhystudios', /werkgebied|bed|breedte/i]
];

const ROUTES = [...ECHT, ...VANGNET];

const AUDIT = `() => {
	const ontleed = (s) => {
		const m = String(s).match(/rgba?\\(\\s*([\\d.]+)[\\s,]+([\\d.]+)[\\s,]+([\\d.]+)(?:[\\s,/]+([\\d.]+))?/);
		if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]];
		// color(srgb r g b / a) — wat color-mix teruggeeft in sommige browsers
		const c = String(s).match(/color\\(srgb\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)(?:\\s*\\/\\s*([\\d.]+))?/);
		if (c) return [c[1] * 255, c[2] * 255, c[3] * 255, c[4] === undefined ? 1 : +c[4]];
		return null;
	};
	const opElkaar = (boven, onder) => {
		const a = boven[3];
		return [boven[0] * a + onder[0] * (1 - a), boven[1] * a + onder[1] * (1 - a),
			boven[2] * a + onder[2] * (1 - a), 1];
	};
	// De echte achtergrond: van de body naar boven alles op elkaar leggen.
	const achtergrond = (el) => {
		const keten = [];
		for (let p = el; p; p = p.parentElement) keten.push(p);
		let kleur = [255, 255, 255, 1];
		for (const n of keten.reverse()) {
			const c = ontleed(getComputedStyle(n).backgroundColor);
			if (c && c[3] > 0) kleur = opElkaar(c, kleur);
		}
		return kleur;
	};
	const lum = ([r, g, b]) => {
		const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
		return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
	};
	const ratio = (a, b) => {
		const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
		return (x + 0.05) / (y + 0.05);
	};

	const uit = [];
	let laagste = { r: 99, t: '' };
	for (const el of document.querySelectorAll('*')) {
		const r = el.getBoundingClientRect();
		if (r.width === 0 || r.height === 0) continue;
		// Alleen knopen met eigen tekst, anders meet je containers dubbel.
		const eigen = [...el.childNodes]
			.filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join(' ').trim();
		if (!eigen) continue;
		const s = getComputedStyle(el);
		if (s.visibility === 'hidden' || +s.opacity === 0) continue;
		const fg = ontleed(s.color);
		if (!fg) continue;
		const bg = achtergrond(el);
		// Doorzichtige tekst nog even over zijn achtergrond leggen.
		const echt = fg[3] < 1 ? opElkaar(fg, bg) : fg;
		const px = parseFloat(s.fontSize);
		const dik = +s.fontWeight >= 700 || (+s.fontWeight >= 600 && px >= 18.66);
		const groot = px >= 24 || (px >= 18.66 && dik);
		const eis = groot ? 3 : 4.5;
		const gemeten = ratio(echt, bg);
		// Ook de krapste geslaagde meting bewaren: een groene uitslag zonder
		// getal zegt niet of er marge was of dat het op het randje ging.
		if (gemeten < laagste.r) laagste = { r: +gemeten.toFixed(2), t: eigen.slice(0, 22), eis };
		if (gemeten < eis) {
			uit.push({
				t: eigen.slice(0, 26), px: +px.toFixed(1), eis,
				r: +gemeten.toFixed(2),
				fg: echt.slice(0, 3).map(Math.round).join(','),
				bg: bg.slice(0, 3).map(Math.round).join(','),
				cls: String(el.className).slice(0, 30)
			});
		}
	}
	return { fouten: uit, laagste };
}`;

const b = await browser();
let totaal = 0;
let kapot = 0;
const krapste = [];
for (const breedte of [1440, 390]) {
	for (const thema of ['light', 'dark']) {
		for (const [naam, pad, merkteken] of ROUTES) {
			const page = await open(b, { width: breedte, theme: thema, path: pad });
			await page.waitForTimeout(500);
			// Borg: nul bevindingen op een verkeerd scherm is ook nul bevindingen.
			// Twee routes maten een ronde lang een vangnetpagina, en dat viel niet
			// op omdat de uitslag groen bleef. Een meting telt daarom pas als het
			// merkteken van dít scherm er echt staat.
			const tekst = await page.evaluate(() => document.body.innerText);
			const gezien =
				merkteken instanceof RegExp ? merkteken.test(tekst) : tekst.includes(merkteken);
			if (!gezien) {
				const kop = await page.evaluate(
					() => document.querySelector('h1, h2')?.textContent.trim().slice(0, 40) ?? '(geen kop)'
				);
				console.log(
					`\n!! ${breedte} ${thema} ${naam} (${pad}): merkteken ${merkteken} niet gevonden` +
						` — de pagina toont "${kop}". Meting ongeldig.`
				);
				kapot++;
				await page.context().close();
				continue;
			}
			// De auditor staat als string zodat hij één bron heeft; hem als
			// expressie doorgeven levert de functie op in plaats van zijn
			// uitkomst, dus roepen we hem hier aan.
			const eerste = await page.evaluate(`(${AUDIT})()`);
			const slecht = eerste.fouten;
			let krapst = eerste.laagste;
			// Ook in hover-staat meten. Een hover wisselt vaak alleen de
			// achtergrond en laat de tekstkleur staan; dat is precies waar het
			// kruimelpad op stukliep (4,14 in licht, 3,42 in donker) en wat je
			// nooit ziet als je alleen de ruststand meet.
			for (const el of await page.$$('a, button')) {
				if (!(await el.isVisible())) continue;
				await el.hover({ force: true }).catch(() => {});
				await page.waitForTimeout(60);
				const raak = await page.evaluate(`(${AUDIT})()`);
				if (raak.laagste.r < krapst.r) krapst = { ...raak.laagste, hover: true };
				for (const x of raak.fouten)
					if (!slecht.some((s) => s.t === x.t)) slecht.push({ ...x, hover: true });
			}
			if (slecht.length) {
				totaal += slecht.length;
				console.log(`\n${breedte} ${thema} ${naam}`);
				for (const x of slecht)
					console.log(
						`  [${x.r} < ${x.eis}]${x.hover ? ' (hover)' : ''} "${x.t}" ${x.px}px` +
							`  fg=${x.fg} bg=${x.bg}  .${x.cls}`
					);
			}
			krapste.push({ naam, breedte, thema, ...krapst });
			await page.context().close();
		}
	}
}
await b.close();
console.log(
	totaal === 0 ? '\nwizard: alles haalt zijn eis' : `\nwizard: ${totaal} bevindingen`
);
console.log('\nkrapste geslaagde meting per scherm (over beide thema\'s en breedtes):');
for (const [naam] of ECHT) {
	const rijen = krapste.filter((k) => k.naam === naam);
	if (!rijen.length) { console.log(`  ${naam.padEnd(22)} niet gemeten`); continue; }
	const m = rijen.reduce((a, b) => (b.r < a.r ? b : a));
	console.log(
		`  ${naam.padEnd(22)} ${String(m.r).padStart(6)}:1 (eis ${m.eis})` +
			`${m.hover ? ' hover' : ''}  "${m.t}" — ${m.breedte} ${m.thema}`
	);
}
console.log(
	kapot === 0
		? `gemeten: ${ECHT.length} echte schermen + ${VANGNET.length} vangnetpagina's, 2 thema's, 2 breedtes`
		: `LET OP: ${kapot} metingen ongeldig — die schermen zijn niet beoordeeld`
);
if (kapot) process.exitCode = 1;
