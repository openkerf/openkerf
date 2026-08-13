/**
 * Regressietest bij de terugmelding over het testraster.
 *
 * Twee dingen die Jelle in echt gebruik vond, allebei alleen te zien door de
 * flow af te lopen — niet door de code te lezen:
 *
 *  1. "Nog een raster maken" tekende meteen een tweede bord op precies dezelfde
 *     plek, en liet de melding van het vorige bord ("De job staat in de
 *     wachtrij") staan onder het nummer van het nieuwe.
 *  2. Tijdens het typen van een bereik is een tussenstand bijna altijd even
 *     ongeldig ("van" hoger dan "tot"). Het voorbeeldblok verdween dan
 *     compleet: het formulier sprong van 506 naar 810 px breed.
 *
 * Beide falen op de oude code en slagen op de nieuwe.
 */
import { browser, open, BASE } from './harness.mjs';

const post = (p, b) =>
	fetch(BASE + p, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(b ?? {})
	});

const fouten = [];
const eis = (waar, wat) => {
	console.log(`${waar ? 'ok  ' : 'FOUT'}  ${wat}`);
	if (!waar) fouten.push(wat);
};

const materialen = await (await fetch(BASE + '/api/library/materials')).json();
const materiaal =
	materialen.find((m) => m.name === 'Testhout FB') ??
	(await (await post('/api/library/materials', { name: 'Testhout FB' })).json());

await fetch(BASE + '/api/design/autosave', { method: 'DELETE' }).catch(() => {});
await post('/api/design/clear');

const b = await browser();
const page = await open(b, { width: 1440, theme: 'dark', path: '/?tab=design' });
const later = page.getByRole('button', { name: /later/i });
if (await later.count()) await later.first().click().catch(() => {});

await page.locator('button.tool[title="Testraster"]').first().click();
await page.waitForSelector('.wizard', { timeout: 10000 });
await page.waitForTimeout(1500);
await page.locator('.wizard .grid select').first().selectOption(String(materiaal.id));
await page.waitForTimeout(1200);

const stand = () =>
	page.evaluate(() => {
		const q = (s) => document.querySelector(s);
		return {
			voorbeeld: !!q('.preview'),
			voorbeeldBreedte: q('.preview')
				? +q('.preview').getBoundingClientRect().width.toFixed(1)
				: 0,
			formulierBreedte: +q('.werkbank .grid').getBoundingClientRect().width.toFixed(1),
			onaf: q('.preview .onaf')?.textContent.trim().replace(/\s+/g, ' ') ?? null,
			gelukt: q('.gelukt')?.textContent.trim().replace(/\s+/g, ' ') ?? null,
			knop: [...document.querySelectorAll('.actions .btn')]
				.map((k) => k.textContent.trim().replace(/\s+/g, ' '))
				.pop()
		};
	});

// ---------------------------------------------------------------- punt 2
const rust = await stand();
const invoer = page.getByLabel('Snelheid van (mm/s)', { exact: true });
await invoer.click();
await invoer.fill('');
await invoer.type('30', { delay: 60 }); // 30 > tot(25): even ongeldig
await page.waitForTimeout(1200);
const tussen = await stand();

eis(tussen.voorbeeld, 'het voorbeeld blijft staan bij een ongeldige tussenstand');
eis(
	tussen.formulierBreedte === rust.formulierBreedte,
	`het formulier verspringt niet (${rust.formulierBreedte} → ${tussen.formulierBreedte} px)`
);
eis(
	tussen.voorbeeldBreedte === rust.voorbeeldBreedte,
	`de voorbeeldkolom houdt zijn breedte (${rust.voorbeeldBreedte} → ${tussen.voorbeeldBreedte} px)`
);
eis(!!tussen.onaf, `de reden staat naast het voorbeeld: ${tussen.onaf}`);
eis(
	!/speed_max|speed_min/.test(tussen.onaf ?? ''),
	'de reden is Nederlands en geen veldnaam uit de API'
);

await invoer.fill('5');
await page.waitForTimeout(1200);
eis((await stand()).onaf === null, 'de melding verdwijnt zodra het weer klopt');

// ---------------------------------------------------------------- punt 1
await page.locator('.actions .btn').last().click();
await page.waitForSelector('.gelukt', { timeout: 15000 });
await page.waitForTimeout(1200);
await page.locator('.branden .btn.primary').click(); // job starten
await page.waitForTimeout(2500);
const nastart = await stand();
eis(/wachtrij|weiger|Netwerkfout|machine/i.test(nastart.gelukt ?? ''), 'de job meldt zich');

const voorRasters = (await (await fetch(BASE + '/api/library/testgrids')).json()).length;
await page.locator('.actions .btn').last().click(); // "Nog een raster instellen"
await page.waitForTimeout(2000);
const opnieuw = await stand();
const naRasters = (await (await fetch(BASE + '/api/library/testgrids')).json()).length;

eis(opnieuw.gelukt === null, 'de melding van het vorige bord blijft niet staan');
eis(
	naRasters === voorRasters,
	`er wordt niet stiekem een tweede bord getekend (${voorRasters} → ${naRasters})`
);
eis(/tekenen/i.test(opnieuw.knop ?? ''), `de hoofdknop staat weer op tekenen: ${opnieuw.knop}`);
eis(
	/valt over raster/i.test(opnieuw.onaf ?? ''),
	`het vorige bord op dezelfde plek wordt gemeld: ${opnieuw.onaf}`
);

// En zodra je opschuift, is de waarschuwing weg.
const startX = page.getByLabel('Start X (mm)', { exact: true });
await startX.fill('200');
await page.waitForTimeout(1200);
eis((await stand()).onaf === null, 'opschuiven haalt de botsingsmelding weg');

console.log('\nconsolefouten:', page.problems);
await b.close();
console.log(fouten.length ? `\n${fouten.length} EIS(EN) GEFAALD` : '\nalles goed');
process.exit(fouten.length ? 1 : 0);
