/**
 * D10 — draait de typografie ook zonder internet?
 *
 * De proef: alles blokkeren wat niet van onze eigen server komt, en dan kijken
 * of IBM Plex Sans en Mono er echt zijn. Zonder deze meting is "we hosten ze
 * zelf" een bewering; met deze meting is het een feit.
 */
import { browser, open, report, BASE } from './harness.mjs';
import { eisScherm } from './g-thema-guard.mjs';

const findings = [];
const b = await browser();
const context = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const buiten = [];
// Alles wat niet naar onze eigen server gaat, halen we eruit — precies wat een
// werkplaats zonder netwerk doet.
await context.route('**/*', (route) => {
	const url = route.request().url();
	if (url.startsWith(BASE) || url.startsWith('data:') || url.startsWith('blob:')) return route.continue();
	buiten.push(url);
	return route.abort();
});
const page = await context.newPage();
const fouten = [];
page.on('console', (m) => m.type() === 'error' && fouten.push(m.text().slice(0, 120)));
page.on('requestfailed', (r) => { /* geblokkeerde externe verzoeken zijn de bedoeling */ });
await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 30000 });
await page.waitForSelector('.statusbar, .setup, .welkom', { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(1500);
await page.evaluate(() => document.fonts.ready);
// Poort: een blanco pagina levert "geen externe verzoeken" op, en dat zou hier
// als geslaagd lezen. eisHeleBuild kan niet: fetch is hier juist geblokkeerd.
await eisScherm(page, '.topbar, .setup, .welkom', 'offline hoofdscherm');

const uit = await page.evaluate(async () => {
	const s = getComputedStyle(document.documentElement);
	const mono = document.querySelector('.mono');
	// `check()` meldt "nee" voor een gewicht dat nog niemand op het scherm zet,
	// ook als het bestand er prima is. Dus eerst laten laden en dan pas vragen —
	// anders meet je welke gewichten dit scherm gebruikt in plaats van welke de
	// build meelevert.
	for (const w of [400, 500, 600, 700]) {
		await document.fonts.load(`${w} 16px "IBM Plex Sans"`).catch(() => {});
	}
	for (const w of [400, 500]) {
		await document.fonts.load(`${w} 16px "IBM Plex Mono"`).catch(() => {});
	}
	return {
		sans: document.fonts.check('16px "IBM Plex Sans"'),
		mono: document.fonts.check('16px "IBM Plex Mono"'),
		gewichten: [400, 500, 600, 700].map((w) => document.fonts.check(`${w} 16px "IBM Plex Sans"`)),
		geladen: [...document.fonts].map((f) => `${f.family} ${f.weight} ${f.status}`),
		bodyFont: getComputedStyle(document.body).fontFamily,
		monoFont: mono ? getComputedStyle(mono).fontFamily : null,
		tokenUi: s.getPropertyValue('--font-ui').trim()
	};
});

console.log('geblokkeerde externe verzoeken:', buiten.length, buiten.slice(0, 6).join(' | ') || '(geen)');
console.log('fontfaces in het document:', uit.geladen.join(' | '));
console.log('IBM Plex Sans beschikbaar:', uit.sans, '| Mono:', uit.mono, '| gewichten 400/500/600/700:', uit.gewichten.join('/'));
console.log('body font-family:', uit.bodyFont);
console.log('.mono font-family:', uit.monoFont);
console.log('fouten in de console:', fouten.length ? fouten.join(' | ') : 'geen');

if (!uit.sans || !uit.mono) {
	findings.push({ severity: 'major', what: 'Zonder netwerk is IBM Plex niet beschikbaar',
		evidence: `sans ${uit.sans}, mono ${uit.mono} — fontfaces: ${uit.geladen.join(', ')}` });
}
if (uit.gewichten.some((g) => !g)) {
	findings.push({ severity: 'minor', what: 'Niet alle gebruikte gewichten van IBM Plex Sans zijn geladen',
		evidence: `400/500/600/700 = ${uit.gewichten.join('/')}` });
}
// De enige externe herkomst die nog over is, is de `<link>` naar
// fonts.googleapis.com in routes/+layout.svelte. Die is sinds v3.3 overbodig, en
// hij is de bron van de intermitterende c2-major "fouten in de browserconsole".
// Daarom apart gemeld: het is geen fontprobleem meer, het is één regel HTML.
const google = buiten.filter((u) => /googleapis|gstatic/.test(u));
if (google.length) {
	findings.push({
		severity: 'minor',
		what: 'Er staat nog een externe fontverwijzing in de <head>',
		evidence: `${google.join(' | ')} — overbodig sinds v3.3; hij levert offline ${fouten.length} consolefout(en) op`
	});
} else if (fouten.length) {
	findings.push({ severity: 'minor', what: 'Fouten in de browserconsole zonder netwerk', evidence: fouten.join(' | ') });
}
report('D10 — typografie zonder netwerk', findings);
await b.close();
