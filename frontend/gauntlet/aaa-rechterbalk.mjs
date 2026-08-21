/**
 * Screenshots van het Bewerken-tabblad in de rechterbalk (oppervlak "rechterbalk").
 *
 * Drie staten — één vorm, meerdere vormen, een groep — op drie breedtes in twee
 * thema's. Meet meteen de hoogte van het paneel: dat is de klacht die gemeten
 * moet worden, niet alleen bekeken.
 */
import { chromium } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8131';
const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/rechterbalk';
const ronde = process.argv[2] ?? 'voor';

async function ids() {
	const design = await (await fetch(`${BASE}/api/design`)).json();
	return design.elements.map((e) => e.id);
}

/** Een element dat in een groep zit — nodig om de groep weer op te heffen. */
async function inEenGroep() {
	const design = await (await fetch(`${BASE}/api/design`)).json();
	return design.elements.find((e) => e.group_id)?.id ?? null;
}

const b = await chromium.launch();
const metingen = [];

async function schiet(naam, select, width, theme, acties = []) {
	const ctx = await b.newContext({
		viewport: { width, height: width === 390 ? 844 : 900 },
		deviceScaleFactor: 1,
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
	await page.goto(`${BASE}/?tab=design&select=${select.join(',')}`, {
		waitUntil: 'domcontentloaded'
	});
	await page.waitForSelector('.statusbar', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(1200);
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(400);

	// Handelingen in de echte UI: alleen zo zie je wat een gebruiker ziet ná
	// het klikken, en dus of het anker verschijnt.
	for (const label of acties) {
		await page.getByRole('button', { name: label, exact: true }).first().click();
		await page.waitForTimeout(900);
	}

	// De hoogte van álles in het paneel, ook wat je moet scrollen om te zien.
	const maat = await page
		.evaluate(() => {
			const scroll = document.querySelector('.panel-scroll');
			if (!scroll) return null;
			return {
				zichtbaar: Math.round(scroll.clientHeight),
				inhoud: Math.round(scroll.scrollHeight),
				breedte: Math.round(scroll.clientWidth)
			};
		})
		.catch(() => null);
	metingen.push({ naam, width, theme, ...(maat ?? {}) });

	const bestand = `${OUT}/${ronde}-${naam}-${width}-${theme}`;
	await page.screenshot({ path: `${bestand}-vol.png` });
	const paneel = page.locator('.panel-scroll').first();
	if (await paneel.count()) {
		// Het hele paneel, ook het deel onder de vouw.
		await paneel
			.screenshot({ path: `${bestand}-paneel.png` })
			.catch(() => {});
	}
	await ctx.close();
}

// Id's opnieuw ophalen per staat: groeperen en opheffen delen nieuwe id's uit,
// dus een lijst van vóór die stap wijst daarna elders heen — en dan fotografeer
// je een andere selectie dan je denkt.
for (const [naam, hoeveel] of [
	['een', 1],
	['meer', 3]
]) {
	const alle = await ids();
	if (alle.length < hoeveel) throw new Error(`Te weinig elementen: ${alle.length}`);
	const sel = alle.slice(0, hoeveel);
	for (const width of [1440, 1024, 390]) {
		for (const theme of ['light', 'dark']) await schiet(naam, sel, width, theme);
	}
}
const alle = await ids();

// Draaien en spiegelen in de échte UI, zodat het anker ("Terugzetten")
// verschijnt zoals een gebruiker het te zien krijgt. Na afloop terugzetten,
// anders erft de volgende staat de scheve vorm.
const herstel = async () => {
	await fetch(`${BASE}/api/design/mirror`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ ids: [alle[0]], axis: 'horizontal' })
	});
	await fetch(`${BASE}/api/design/rotate`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ ids: [alle[0]], angle_deg: 0, absolute: true })
	});
};
for (const width of [1440, 1024]) {
	for (const theme of ['light', 'dark']) {
		await schiet('gedraaid', [alle[0]], width, theme, [
			'+90 graden draaien',
			'Horizontaal spiegelen'
		]);
		await herstel();
	}
}

// Groeperen verandert de id's, dus dat gebeurt ná de andere staten.
await fetch(`${BASE}/api/design/group`, {
	method: 'POST',
	headers: { 'Content-Type': 'application/json' },
	body: JSON.stringify({ ids: alle.slice(0, 2) })
});
const gegroepeerd = await inEenGroep();
for (const width of [1440, 1024, 390]) {
	for (const theme of ['light', 'dark']) await schiet('groep', [gegroepeerd], width, theme);
}
// Opheffen met een id dát in de groep zit; met het eerste id van de lijst
// erbuiten weigert de engine, en dan erft de volgende ronde de groep.
await fetch(`${BASE}/api/design/ungroup`, {
	method: 'POST',
	headers: { 'Content-Type': 'application/json' },
	body: JSON.stringify({ ids: [gegroepeerd] })
});

await b.close();
console.table(metingen);
