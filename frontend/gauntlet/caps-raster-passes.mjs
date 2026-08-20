/**
 * Passes op een testbord: het veld, en wat het aan de samenvatting verandert.
 *
 * Het geval van Jelle: een materiaal dat op 5 mm/s bijna doorsnijdt, en dat hij
 * op 8 mm/s in twee passes wil proberen. De metingen naast de screenshots zijn
 * het bewijs dat het getal doorwerkt — in de tijdschatting, op het opschrift van
 * het bord, en in de preset die er straks uit rolt.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8150';
const UIT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/passes';
mkdirSync(UIT, { recursive: true });

const b = await chromium.launch();
const metingen = [];

async function pagina(width, theme) {
	const ctx = await b.newContext({
		viewport: { width, height: width === 390 ? 844 : 950 },
		deviceScaleFactor: 1,
		colorScheme: theme
	});
	const page = await ctx.newPage();
	if (theme === 'dark') {
		await page.addInitScript(() => {
			const zet = () => document.documentElement?.setAttribute('data-theme', 'dark');
			zet();
			document.addEventListener('DOMContentLoaded', zet);
		});
	}
	page.fouten = [];
	page.on('pageerror', (e) => page.fouten.push(String(e).slice(0, 120)));
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(1200);
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(300);
	// Het testrasterpaneel openen via de gereedschapsbalk.
	const knop = page.getByRole('button', { name: /testraster/i }).first();
	if (await knop.count()) await knop.click();
	await page.waitForTimeout(2200);
	return { ctx, page };
}

async function veld(page) {
	const rij = page.locator('div.veld', { hasText: 'Passes' }).first();
	if (!(await rij.count())) return { label: '(veld niet gevonden)', waarde: null };
	return {
		label: (await rij.innerText()).replace(/\s+/g, ' ').slice(0, 60),
		waarde: await rij.locator('input').inputValue()
	};
}

async function samenvatting(page) {
	const f = page.locator('.figures').first();
	return (await f.count()) ? (await f.innerText()).replace(/\s+/g, ' ') : '(geen)';
}

async function tijd(page) {
	const k = page.locator('.kosten, .tijd').first();
	return (await k.count()) ? (await k.innerText()).replace(/\s+/g, ' ').slice(0, 90) : '(geen)';
}

for (const width of [1440, 1024]) {
	for (const theme of ['light', 'dark']) {
		const { ctx, page } = await pagina(width, theme);

		metingen.push({ staat: 'een-pass', width, theme, ...(await veld(page)),
			samenvatting: await samenvatting(page), tijd: await tijd(page), fouten: page.fouten.length });
		await page.screenshot({ path: `${UIT}/een-pass-${width}-${theme}.png` });

		// Op twee zetten en kijken wat er meebeweegt.
		const invoer = page.locator('div.veld', { hasText: 'Passes' }).first().locator('input');
		if (await invoer.count()) {
			await invoer.fill('2');
			await invoer.blur();
			await page.waitForTimeout(2200);
		}
		metingen.push({ staat: 'twee-passes', width, theme, ...(await veld(page)),
			samenvatting: await samenvatting(page), tijd: await tijd(page), fouten: page.fouten.length });
		await page.screenshot({ path: `${UIT}/twee-passes-${width}-${theme}.png` });
		await ctx.close();
	}
}

await b.close();
console.log('--- metingen ---');
for (const m of metingen) console.log(JSON.stringify(m));
