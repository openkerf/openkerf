/**
 * De verbindknop, in de drie standen die er zijn, op de echte KH-5030.
 *
 * De statusbalk kon lezen dat er geen machine aan de lijn hing en er niets aan
 * doen. Wat hier gefotografeerd wordt is de knop die dat gat dicht, én de
 * bevestiging die zegt wat verbreken kost: gemeten lukt verbinden precies één
 * keer per proces, dus verbreken is eenrichtingsverkeer tot een herstart.
 *
 * De metingen naast de screenshots zijn het bewijs. Een screenshot laat zien
 * dat er "Verbonden met de laser" stond; dat het waar was, blijkt uit de
 * toestand die de machine zelf meldt.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8146';
const UIT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/verbinden';
mkdirSync(UIT, { recursive: true });

async function staat() {
	const alle = await (await fetch(BASE + '/api/devices')).json();
	const d = alle.find((x) => x.active);
	return { label: d?.label, connection: d?.connection?.state, kop: d?.position?.mm };
}

const b = await chromium.launch();
const metingen = [];

async function pagina(theme) {
	const ctx = await b.newContext({
		viewport: { width: 1440, height: 900 },
		deviceScaleFactor: 2,
		colorScheme: theme
	});
	const page = await ctx.newPage();
	if (theme === 'dark') {
		await page.addInitScript(() => {
			const set = () => document.documentElement?.setAttribute('data-theme', 'dark');
			set();
			document.addEventListener('DOMContentLoaded', set);
		});
	}
	page.fouten = [];
	page.on('pageerror', (e) => page.fouten.push(String(e).slice(0, 120)));
	await page.goto(`${BASE}/?tab=job`, { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(1600);
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(400);
	return { ctx, page };
}

/** De rechterhelft van de balk: daar staat de toestand met zijn knop. */
async function knip(page, naam) {
	const balk = page.locator('.statusbar').first();
	const doos = await balk.boundingBox();
	if (!doos) return;
	await page.screenshot({
		path: `${UIT}/${naam}.png`,
		clip: {
			x: doos.x + doos.width * 0.30,
			y: doos.y - 5,
			width: doos.width * 0.70,
			height: doos.height + 10
		}
	});
}

async function lees(page) {
	const knop = page.locator('.statusbar button.verbind').first();
	return {
		toestand: await page.locator('.statusbar span[title], .statusbar .onthecht, .statusbar .offline')
			.first()
			.innerText()
			.catch(() => '?'),
		knop: (await knop.count()) ? (await knop.innerText()).trim() : '(geen knop)'
	};
}

for (const theme of ['light', 'dark']) {
	const { ctx, page } = await pagina(theme);
	metingen.push({ staat: 'verbonden', theme, ...(await lees(page)), machine: await staat(), fouten: page.fouten.length });
	await knip(page, `verbonden-${theme}`);

	// De bevestiging: één klik op "Verbreken…" en de ask staat er, met de prijs.
	const knop = page.locator('.statusbar button.verbind').first();
	if ((await knop.count()) && (await knop.innerText()).includes('Verbreken')) {
		await knop.click();
		await page.waitForTimeout(500);
		metingen.push({
			staat: 'bevestiging',
			theme,
			ask: (await page.locator('.verbreek-ask').innerText()).replace(/\s+/g, ' '),
			machine: await staat(),
			fouten: page.fouten.length
		});
		await knip(page, `bevestiging-${theme}`);
		await page.locator('.verbreek-ask button', { hasText: /Laten hangen/ }).click();
		await page.waitForTimeout(400);

		// De losse stand. Verbreken via de API en meteen kijken: gemeten staat de
		// connection er binnen ~6 s vanzelf weer, dus dit is een kort venster —
		// en met de app eraan lukte het zes pogingen op rij niet. `los-light.png`
		// is daarom in een aparte ronde gemaakt; kom je hem niet te pakken, dan
		// is dat geen failure in de knop maar de engine die zelf heropent.
		if (theme === 'light') {
			await fetch(BASE + '/api/machine/disconnect', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: '{}'
			});
			await page.waitForTimeout(1400);
			metingen.push({ staat: 'los', theme, ...(await lees(page)), machine: await staat(), fouten: page.fouten.length });
			await knip(page, `los-${theme}`);
		}
	}
	await ctx.close();
}

// En de mislukte poging: verbinden lukt in dit proces niet meer.
{
	const { ctx, page } = await pagina('light');
	const knop = page.locator('.statusbar button.verbind').first();
	if ((await knop.count()) && (await knop.innerText()).includes('Verbinden')) {
		await knop.click();
		await page.waitForTimeout(3500);
		const melding = await page
			.locator('p, .melding, [role="alert"]')
			.allInnerTexts()
			.catch(() => []);
		const woorden = melding.find((m) => m.includes('lukte niet')) ?? '(geen melding gevonden)';
		metingen.push({ staat: 'weigering', theme: 'light', melding: woorden.replace(/\s+/g, ' ').slice(0, 220), machine: await staat() });
		await page.screenshot({ path: `${UIT}/weigering-light.png` });
	}
	await ctx.close();
}

await b.close();
console.log('--- metingen ---');
for (const m of metingen) console.log(JSON.stringify(m));
