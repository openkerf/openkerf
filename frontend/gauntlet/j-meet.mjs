/**
 * Waar staat de voortgang, en hoeveel ervan moet je scrollen?
 *
 * Dat is de klacht in één maat: "als alles loopt is de voortgangsindicator
 * helemaal onderaan". Deze meting leest de y-positie van de voortgangsbalk in het
 * Job-paneel, en of hij binnen het zichtbare deel valt.
 */
import { chromium } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const post = (p) =>
	fetch(BASE + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
const page = await ctx.newPage();

async function meet(naam) {
	await page.goto(BASE + '/?tab=job', { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar').catch(() => {});
	await page.waitForTimeout(1500);
	const later = page.getByRole('button', { name: /^Later$/ });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(400);
	return page.evaluate((naam) => {
		const scroll = document.querySelector('.panel-scroll');
		const vak = scroll?.getBoundingClientRect();
		// De voortgangsbalk: het nieuwe blok bovenaan, of de oude spoolerkaart.
		const balk =
			document.querySelector('.nu-balk') ??
			document.querySelector('.panel-scroll .progress') ??
			document.querySelector('.panel-scroll svg.progress');
		const doos = balk?.getBoundingClientRect();
		const knoppen = scroll ? scroll.querySelectorAll('button').length : 0;
		return {
			naam,
			paneelInhoud: scroll ? Math.round(scroll.scrollHeight) : null,
			paneelZichtbaar: scroll ? Math.round(scroll.clientHeight) : null,
			voortgangGevonden: Boolean(doos),
			// Afstand van de bovenkant van het paneel tot de balk: hoeveel je moet
			// scrollen voordat je hem ziet.
			voortgangOpY: doos && vak ? Math.round(doos.top - vak.top + (scroll?.scrollTop ?? 0)) : null,
			zonderScrollenZichtbaar:
				doos && vak ? doos.top >= vak.top && doos.bottom <= vak.bottom : null,
			knoppenInPaneel: knoppen
		};
	}, naam);
}

const uit = [];
await post('/api/job/stop');
await post('/api/spooler/clear');
await new Promise((r) => setTimeout(r, 900));
uit.push(await meet('stil'));

await post('/api/job/start');
await new Promise((r) => setTimeout(r, 2200));
uit.push(await meet('werk onderweg'));

await post('/api/job/pause');
await new Promise((r) => setTimeout(r, 1200));
uit.push(await meet('gepauzeerd'));

await post('/api/job/stop');
await post('/api/spooler/clear');
console.table(uit);
await b.close();
