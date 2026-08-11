/**
 * Lege staten, fouten en offline — ronde-screenshots.
 *
 * Elke staat op 1440 / 1024 / 390, licht en donker. De staten die alleen op de
 * desktop bestaan (dialogen) worden op 390 overgeslagen: daar bestaat het
 * paneel niet.
 */
import { mkdirSync } from 'node:fs';
import { browser, open } from './harness.mjs';

const DIR = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/lege-staten';
mkdirSync(DIR, { recursive: true });

const only = process.argv.slice(2);
const wil = (naam) => only.length === 0 || only.some((o) => naam.includes(o));

async function weg(page) {
	// Het welkomscherm van een verse installatie staat vóór de app; dit
	// oppervlak gaat over de app erachter.
	const rond = page.getByRole('button', { name: /rondkijken zonder machine/i });
	if (await rond.count().catch(() => 0)) {
		await rond.first().click().catch(() => {});
		await page.waitForTimeout(900);
	}
	// "Werk van een vorige sessie" wegklikken.
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count().catch(() => 0)) await later.first().click().catch(() => {});
	await page.waitForTimeout(300);
}

/** Op tablet zit de helft van de rail achter "Meer gereedschap". */
async function rail(page, title) {
	const knop = page.locator(`button[title="${title}"], button[title^="${title}"]`).first();
	if (!(await knop.isVisible().catch(() => false))) {
		// De tablet-rail heet nu eens "Meer", dan weer "Meer gereedschap".
		await page
			.locator('button[title="Meer"], button[title="Meer gereedschap"]')
			.first()
			.click()
			.catch(() => {});
		await page.waitForTimeout(300);
	}
	if (await knop.isVisible().catch(() => false)) {
		await knop.click();
	} else {
		// In het tabletmenu staan de woorden erbij in plaats van een title.
		await page.getByRole('menuitem', { name: new RegExp(title, 'i') }).first().click();
	}
	await page.waitForTimeout(700);
}

async function schiet(page, naam, width, theme) {
	await page.screenshot({ path: `${DIR}/${naam}-${width}-${theme}.png` });
	console.log(`${naam}-${width}-${theme}.png`);
}

const STATEN = [
	{
		naam: 'koud-ontwerp',
		pad: '/?tab=design',
		doe: async () => {}
	},
	{ naam: 'koud-job', pad: '/?tab=job', doe: async () => {} },
	{
		naam: 'bibliotheek-leeg',
		pad: '/?tab=design',
		desktopOnly: true,
		doe: async (page) => {
			await rail(page, 'Materiaalbibliotheek');
		}
	},
	{
		naam: 'bibliotheek-geen-zoekresultaat',
		pad: '/?tab=design',
		desktopOnly: true,
		doe: async (page) => {
			await rail(page, 'Materiaalbibliotheek');
			const zoek = page.locator('input[type="search"], input[placeholder*="oek" i]').first();
			if (await zoek.count()) {
				await zoek.fill('zirkonium');
				await page.waitForTimeout(500);
			}
		}
	},
	{
		naam: 'testraster-geen-resultaten',
		pad: '/?tab=design',
		desktopOnly: true,
		doe: async (page) => {
			await rail(page, 'Testraster');
		}
	},
	{
		naam: 'presetariat',
		pad: '/?tab=design',
		desktopOnly: true,
		doe: async (page) => {
			await rail(page, 'Presetariat');
		}
	},
	{
		naam: 'clipart-leeg',
		pad: '/?tab=design',
		desktopOnly: true,
		doe: async (page) => {
			await rail(page, 'Clipart');
		}
	},
	{
		naam: 'kapot-bestand',
		pad: '/?tab=design',
		doe: async (page) => {
			// Door de echte invoer, niet langs de API: wat de gebruiker ziet is
			// wat de UI met het antwoord doet, niet wat de server terugstuurt.
			// Een .svg die geen svg is — een hernoemd of half gedownload bestand.
			const veld = page.locator('input[type="file"][accept*="svg"]').first();
			if (await veld.count()) {
				await veld.setInputFiles({
					name: 'kapot.svg',
					mimeType: 'image/svg+xml',
					buffer: Buffer.from('dit is geen tekening')
				});
			}
			await page.waitForTimeout(1500);
		}
	},
	{
		naam: 'job-zonder-lagen',
		pad: '/?tab=job',
		doe: async (page) => {
			const start = page.getByRole('button', { name: /job starten|starten/i }).first();
			if (await start.count()) await start.click().catch(() => {});
			await page.waitForTimeout(700);
		}
	}
];

const b = await browser();
for (const staat of STATEN) {
	if (!wil(staat.naam)) continue;
	for (const width of [1440, 1024, 390]) {
		if (staat.desktopOnly && width === 390) continue;
		for (const theme of ['light', 'dark']) {
			const page = await open(b, { width, theme, path: staat.pad });
			await weg(page);
			// Eén onbereikbare knop mag niet de hele ronde kosten.
			try {
				await staat.doe(page);
			} catch (e) {
				console.log(`  ! ${staat.naam} ${width}: ${String(e).slice(0, 90)}`);
			}
			await schiet(page, staat.naam, width, theme);
			if (page.problems.length) console.log('  console:', page.problems.slice(0, 3));
			await page.context().close();
		}
	}
}
await b.close();
