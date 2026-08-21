/**
 * Punt 2: na saving mag geen enkel venster nog beweren dat het ontwerp
 * gewijzigd is.
 *
 * De server set bij `/api/project/export.openkerf` en `/api/design/export.svg`
 * `document.clean()`, maar de client haalde die vlag nooit opnieuw op: een
 * download via `<a href download>` verandert niets in de elementenboom, dus er
 * komt geen signaal en dus geen `design.load()`. Gemeten op de oude code:
 * tekenen → project saving → "Nieuw project" gaf *"Dit ontwerp is gewijzigd
 * since de last keer saving"* terwijl `/api/design` `dirty: false` zei.
 *
 * Een waarschuwing die ook komt als er niets aan de hand is, leer je
 * wegklikken. Dát is de schade — niet de zin zelf.
 *
 * Gebruik: node gauntlet/fc-saving.mjs
 */
import { browser, open, BASE } from './harness.mjs';

const H = { 'Content-Type': 'application/json' };
const LEUGEN = 'gewijzigd since de last keer saving';

await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE', headers: H }).catch(() => {});
await fetch(`${BASE}/api/project/new`, { method: 'POST', headers: H, body: '{}' });

const b = await browser();
const fouten = [];

async function ronde(naam, saving) {
	// 1600px: daaronder verhuist het projectpaar naar het railmenu.
	const page = await open(b, { width: 1600 });
	await fetch(`${BASE}/api/design/elements`, {
		method: 'POST',
		headers: H,
		body: JSON.stringify({ type: 'rect', x_mm: 10, y_mm: 10, width_mm: 30, height_mm: 20 })
	});
	await page.waitForTimeout(1200);

	const download = page.waitForEvent('download', { timeout: 10000 }).catch(() => null);
	await saving(page);
	const bestand = await download;
	await page.waitForTimeout(1200);

	const opServer = (await (await fetch(`${BASE}/api/design`)).json()).dirty;

	await page.locator('button:has-text("Project")').first().click();
	await page.waitForTimeout(200);
	await page.locator('button:has-text("Nieuw project")').first().click();
	await page.waitForTimeout(600);
	const tekst = await page
		.locator('[role="dialog"], dialog, .dialog')
		.filter({ hasText: 'Opnieuw beginnen' })
		.first()
		.innerText()
		.catch(() => '(geen venster)');

	console.log(`\n### ${naam}`);
	console.log('   download   :', bestand ? bestand.suggestedFilename() : 'GEEN');
	console.log('   dirty server:', opServer);
	console.log('   venster     :', tekst.replace(/\s+/g, ' ').slice(0, 160));
	if (!bestand) fouten.push(`${naam}: er kwam geen bestand`);
	if (opServer !== false) fouten.push(`${naam}: de server noemt het ontwerp nog gewijzigd`);
	if (tekst.includes(LEUGEN)) fouten.push(`${naam}: het venster beweert nog "${LEUGEN}"`);
	await page.context().close();
	await fetch(`${BASE}/api/project/new`, { method: 'POST', headers: H, body: '{}' });
}

await ronde('project saving', async (page) => {
	await page.locator('button:has-text("Project")').first().click();
	await page.waitForTimeout(250);
	await page.locator('a:has-text("Project saving")').first().click();
});

await ronde('dit vel exporteren', async (page) => {
	await page.locator('a:has-text("Exporteren")').first().click();
});

await b.close();
if (fouten.length) {
	console.log('\nFAAL');
	for (const f of fouten) console.log(' -', f);
	process.exit(1);
}
console.log('\nGOED — na saving beweert niets meer dat er niet-opgeslagen werk is.');
