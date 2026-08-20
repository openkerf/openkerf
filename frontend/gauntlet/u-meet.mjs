/**
 * Wat de verbouwing meetbaar deed.
 *
 * De screenshots zijn het archief, de metingen zijn het argument: hoe hoog is
 * de paneelkolom, hoeveel knoppen staan er in, en hoeveel instellingen zie je
 * in de bibliotheek zonder te scrollen.
 */
import { chromium } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const els = (await (await fetch(`${BASE}/api/design`)).json()).elements.map((e) => e.id);
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
const page = await ctx.newPage();

async function open(pad) {
	await page.goto(BASE + pad, { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar').catch(() => {});
	await page.waitForTimeout(900);
	const later = page.getByRole('button', { name: /^Later$/ });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(250);
}

const paneel = () =>
	page.evaluate(() => {
		const s = document.querySelector('.panel-scroll');
		if (!s) return null;
		return { zichtbaar: Math.round(s.clientHeight), inhoud: Math.round(s.scrollHeight) };
	});

const uit = {};
await open(`/?tab=design&select=${els[0]}`);
uit.paneelEenVorm = await paneel();
uit.knoppenInPaneel = await page.locator('.panel-scroll button').count();

await open(`/?tab=design&select=${els.slice(0, 3).join(',')}`);
uit.paneelDrieVormen = await paneel();

await open('/');
await page.click('button[title="Materiaalbibliotheek"]');
await page.waitForTimeout(1100);
uit.bibliotheek = await page.evaluate(() => {
	const rijen = [...document.querySelectorAll('.preset')];
	const zichtbaar = rijen.filter((r) => {
		const d = r.getBoundingClientRect();
		return d.top >= 0 && d.bottom <= window.innerHeight;
	});
	return {
		instellingen: rijen.length,
		zichtbaarZonderScrollen: zichtbaar.length,
		hoogtePerInstelling: rijen.length
			? Math.round(rijen[0].getBoundingClientRect().height)
			: 0,
		knoppenPerInstelling: rijen.length ? rijen[0].querySelectorAll('button').length : 0
	};
});
console.log(JSON.stringify(uit, null, 2));
await b.close();
