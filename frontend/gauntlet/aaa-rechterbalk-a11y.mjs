/**
 * Toegankelijkheid van de selectiekaart.
 *
 * c6-a11y kijkt alleen naar de standaardroute (het Job-tabblad), dus dit
 * oppervlak komt daar niet langs. Twaalf knoppen zonder woord erin staat of
 * valt met hun naam voor een schermlezer: zonder naam is een pictogram voor
 * die gebruiker een lege knop.
 */
import { chromium } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8131';
const d = await (await fetch(`${BASE}/api/design`)).json();
const ids = d.elements.map((e) => e.id);

const b = await chromium.launch();
const bevindingen = [];

for (const theme of ['light', 'dark']) {
	const ctx = await b.newContext({
		viewport: { width: 1440, height: 900 },
		deviceScaleFactor: 1,
		colorScheme: theme
	});
	const page = await ctx.newPage();
	if (theme === 'dark')
		await page.addInitScript(() => {
			const zet = () => document.documentElement?.setAttribute('data-theme', 'dark');
			zet();
			document.addEventListener('DOMContentLoaded', zet);
		});
	await page.goto(`${BASE}/?tab=design&select=${ids.slice(0, 3).join(',')}`, {
		waitUntil: 'domcontentloaded'
	});
	await page.waitForSelector('.statusbar', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(1200);
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(400);

	const uit = await page.evaluate(() => {
		const kaart = document.querySelector('.selected');
		const naamloos = [];
		for (const knop of kaart.querySelectorAll('button')) {
			const naam = (knop.getAttribute('aria-label') || knop.textContent || '').trim();
			if (!naam) naamloos.push(knop.className || knop.outerHTML.slice(0, 60));
		}
		const zonderTitel = [...kaart.querySelectorAll('button')].filter(
			(k) => !k.textContent.trim() && !k.title
		).length;
		// Velden moeten een label hebben; een <label> eromheen telt mee.
		const veldenZonderLabel = [...kaart.querySelectorAll('input')].filter(
			(i) => !i.getAttribute('aria-label') && !i.closest('label')
		).length;
		// Elk pictogram is aria-hidden, anders leest een schermlezer de SVG.
		const svgZichtbaar = [...kaart.querySelectorAll('svg')].filter(
			(s) => s.getAttribute('aria-hidden') !== 'true'
		).length;
		return {
			knoppen: kaart.querySelectorAll('button').length,
			naamloos,
			zonderTitel,
			veldenZonderLabel,
			svgZichtbaar
		};
	});

	// Toetsenbord: is elke knop in de kaart met tab te bereiken, in leesvolgorde?
	const volgorde = await page.evaluate(() => {
		const kaart = document.querySelector('.selected');
		return [...kaart.querySelectorAll('button, input, summary')]
			.filter((n) => !n.disabled)
			.map((n) => (n.getAttribute('aria-label') || n.textContent || n.tagName).trim().slice(0, 22));
	});

	console.log(`\n--- ${theme}`);
	console.log('knoppen in de kaart:', uit.knoppen);
	console.log('zonder toegankelijke naam:', uit.naamloos.length, uit.naamloos);
	console.log('pictogramknop zonder title:', uit.zonderTitel);
	console.log('invoervelden zonder label:', uit.veldenZonderLabel);
	console.log('svg niet aria-hidden:', uit.svgZichtbaar);
	console.log('tabvolgorde:', volgorde.join(' → '));

	if (uit.naamloos.length)
		bevindingen.push({ severity: 'blocker', wat: `${theme}: knop zonder naam` });
	if (uit.zonderTitel) bevindingen.push({ severity: 'minor', wat: `${theme}: knop zonder title` });
	if (uit.veldenZonderLabel)
		bevindingen.push({ severity: 'major', wat: `${theme}: veld zonder label` });
	if (uit.svgZichtbaar)
		bevindingen.push({ severity: 'minor', wat: `${theme}: svg niet verborgen` });
	await ctx.close();
}

await b.close();
console.log('\n### Rechterbalk — toegankelijkheid');
console.log(bevindingen.length ? bevindingen : 'geen bevindingen');
