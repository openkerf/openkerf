/**
 * Regressie: loopt het werk door tussen twee schermen op dezelfde server?
 *
 * Twee dingen die stuk waren en die je alleen ziet met twee vensters open:
 *
 * 1. De telefoon haalde zijn rasterlijst één keer op, bij het opbouwen van de
 *    pagina. Maak je op de desktop een raster, dan bleef de telefoon leeg tot
 *    je hem handmatig verversde — precies de volgorde waarin je hem gebruikt.
 * 2. Een pauze was nergens te zien. `LaserJob.status` kent geen pauze en
 *    `running` blijft `true`, dus beide schermen bleven "Bezig" tonen met een
 *    pauzeknop erbij, en de hervatknop verscheen nooit. De vlag komt nu van
 *    `driver.paused`, via `paused` in de status-snapshot.
 *
 * Draaien: OK_BASE=http://127.0.0.1:<poort> node gauntlet/telefoon-doorloop.mjs
 */
import { chromium } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8090';
const log = (...a) => console.log(...a);
const api = async (p, o) => {
	try {
		return await (await fetch(BASE + p, o)).json();
	} catch (e) {
		return { _fout: String(e) };
	}
};

const fouten = [];
const eis = (goed, wat, bewijs) => {
	log(`${goed ? 'ok  ' : 'FOUT'} ${wat}${bewijs ? ` — ${bewijs}` : ''}`);
	if (!goed) fouten.push(wat);
};

const b = await chromium.launch();
const desk = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
const fon = await (
	await b.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 })
).newPage();
await desk.goto(BASE + '/?tab=job', { waitUntil: 'domcontentloaded' });
await fon.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
// De telefoon heeft geen statusbalk — dat is een andere compositie.
await desk.waitForSelector('.statusbar', { timeout: 20000 });
await fon.waitForSelector('.rol', { timeout: 20000 });
await desk.waitForTimeout(1200);

// --------------------------------------------- 1. nieuw raster van de desktop
const fonRasters = () =>
	fon.evaluate(() => [...document.querySelectorAll('label.raster')].length);

const voor = await fonRasters();
const grid = await api('/api/library/testgrids', {
	method: 'POST',
	headers: { 'Content-Type': 'application/json' },
	body: JSON.stringify({
		operation: 'snijden',
		speed_min: 8, speed_max: 20, speed_steps: 2,
		power_min: 40, power_max: 90, power_steps: 2
	})
});
// Ruim boven de verversingsklok van de telefoon (10 s), zonder te verversen.
await fon.waitForTimeout(15000);
const na = await fonRasters();
eis(na > voor, 'de telefoon ziet een raster van de desktop zonder verversen', `${voor} → ${na} rijen (raster ${grid.id})`);

// ------------------------------------------------------ 2. pauze en hervatten
await api('/api/job/start', { method: 'POST' });
await desk.waitForTimeout(4000);
const stand = async () => ({
	bron: (await api('/api/status')).devices?.[0]?.paused,
	desktop: await desk.evaluate(() =>
		[...document.querySelectorAll('.statusbar > span')].map((s) => s.textContent.trim().replace(/\s+/g, ' ')).join(' | ')),
	telefoon: await fon.evaluate(() =>
		[...document.querySelectorAll('button')].map((x) => x.textContent.trim()).filter((t) => /^(pauze|hervat)/i.test(t)).join(','))
});

const pz = fon.locator('button:not([disabled])').filter({ hasText: /^Pauze/i }).first();
if (!(await pz.count())) {
	eis(false, 'de telefoon heeft een pauzeknop tijdens een job');
} else {
	await pz.click();
	await fon.waitForTimeout(4000);
	const p = await stand();
	eis(p.bron === true, 'de pauze komt bij de driver aan', `paused=${p.bron}`);
	eis(/Hervatten/.test(p.desktop), 'de desktop toont Hervatten na een pauze op de telefoon', p.desktop);
	eis(/Pauze/.test(p.desktop) === false || /Hervatten/.test(p.desktop), 'de desktop staat niet meer op Bezig', p.desktop);
	eis(/hervat/i.test(p.telefoon), 'de telefoon toont zelf ook een hervatknop', p.telefoon);

	const hv = desk.getByRole('button', { name: /^Hervatten$/ }).first();
	await hv.click({ timeout: 8000 }).catch((e) => log('   klik mislukte:', String(e).slice(0, 70)));
	await desk.waitForTimeout(4000);
	const h = await stand();
	// Hier zat de tweede fout: `resume` meldde op een lihuiyu "Resumed" en liet
	// de driver staan. Deze regel is de enige die dat aantoont.
	eis(h.bron === false, 'hervatten laat de machine ook echt lopen', `paused=${h.bron}`);
	eis(/Pauze/.test(h.desktop), 'de desktop staat weer op pauzeren', h.desktop);
}

await api('/api/job/stop', { method: 'POST' });
await api('/api/spooler/clear', { method: 'POST' });
await api(`/api/library/testgrids/${grid.id}`, { method: 'DELETE' });

log(fouten.length ? `\n${fouten.length} fout(en)` : '\nalles goed');
await b.close();
process.exit(fouten.length ? 1 : 0);
