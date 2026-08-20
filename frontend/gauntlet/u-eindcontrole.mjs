/**
 * De eindcontrole van FUNCTIONALITEIT.md: is elke handeling die verhuisd is,
 * nog bereikbaar — en waar?
 *
 * Alleen de verhuisde handelingen worden hier machinaal nagelopen. Wat op zijn
 * plek is blijven staan, staat er nog; wat verplaatst is, is precies waar een
 * regressie zich zou verstoppen.
 */
import { chromium } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const MOD = process.platform === 'darwin' ? 'Meta' : 'Control';

async function zaai() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/project/new`, { method: 'POST' });
	for (const v of [
		{ type: 'rect', x_mm: 20, y_mm: 20, width_mm: 40, height_mm: 25 },
		{ type: 'rect', x_mm: 80, y_mm: 60, width_mm: 40, height_mm: 25 },
		{ type: 'rect', x_mm: 150, y_mm: 20, width_mm: 40, height_mm: 25 },
		{ type: 'text', x_mm: 25, y_mm: 140, text: 'Kerf', height_mm: 12 }
	])
		await fetch(`${BASE}/api/design/elements`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(v)
		});
	const d = await (await fetch(`${BASE}/api/design`)).json();
	return d.elements.map((e) => e.id);
}

const els = await zaai();
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
const page = await ctx.newPage();
const fouten = [];
page.on('pageerror', (e) => fouten.push(String(e).slice(0, 120)));

async function open(pad = `/?tab=design&select=${els.slice(0, 3).join(',')}`) {
	await page.goto(BASE + pad, { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar').catch(() => {});
	await page.waitForTimeout(900);
	const later = page.getByRole('button', { name: /^Later$/ });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(250);
}

/** Het objectmenu openen op de selectie. */
async function objectmenu() {
	// Géén Escape vooraf: dat wíst de selectie (en daarmee het sleepkader waar
	// we op moeten rechtsklikken). `open()` herlaadt de pagina toch al, dus er
	// staat nooit een menu open.
	const doos = await page.locator('.grab').first().boundingBox();
	if (!doos) throw new Error('geen selectiekader');
	await page.mouse.click(doos.x + doos.width / 2, doos.y + doos.height / 2, { button: 'right' });
	await page.waitForTimeout(350);
}

const uitslag = [];
async function toets(nummer, wat, waar, hoe) {
	try {
		const gevonden = await hoe();
		uitslag.push({ nr: nummer, actie: wat, waar, gevonden: gevonden ? 'ja' : 'NEE' });
	} catch (e) {
		uitslag.push({ nr: nummer, actie: wat, waar, gevonden: 'FOUT: ' + String(e).slice(0, 60) });
	}
}

const inBalk = (naam) => async () => {
	await open();
	return (await page.getByRole('toolbar').getByRole('button', { name: naam, exact: true }).count()) > 0;
};

const inMenu = (naam, submenu = null) => async () => {
	await open();
	await objectmenu();
	if (submenu) {
		await page.getByRole('menuitem', { name: submenu, exact: true }).hover();
		await page.waitForTimeout(300);
	}
	const n = await page.getByRole('menu').getByText(naam, { exact: true }).count();
	await page.keyboard.press('Escape');
	return n > 0;
};

// ── Verhuisd naar de actiebalk ──
for (const [nr, naam] of [
	['7.2', 'Ongedaan maken'],
	['7.3', 'Opnieuw'],
	['7.19', 'Links uitlijnen'],
	['7.20', 'Horizontaal centreren'],
	['7.21', 'Rechts uitlijnen'],
	['7.22', 'Horizontaal verdelen'],
	['7.23', 'Boven uitlijnen'],
	['7.24', 'Verticaal centreren'],
	['7.25', 'Onder uitlijnen'],
	['7.26', 'Verticaal verdelen'],
	['7.27', 'Horizontaal spiegelen'],
	['7.28', 'Verticaal spiegelen'],
	['7.29', 'Groeperen'],
	['7.30', 'Groep opheffen']
])
	await toets(nr, naam, 'actiebalk', inBalk(naam));

// ── Verhuisd naar het rechterklikmenu ──
for (const [nr, naam, sub] of [
	['7.14', '90° linksom', 'Draaien'],
	['7.17', '90° rechtsom', 'Draaien'],
	['7.32', 'Splitsen in losse vormen', 'Pad bewerken'],
	['7.33', 'Vullen — voor rasteren', null],
	['7.34', 'Alleen in de snijlaag', 'Laag'],
	['7.35', 'Alleen in de graveerlaag', 'Laag'],
	['7.36', 'Alleen in de rasterlaag', 'Laag'],
	['7.37', 'Verenigen', 'Combineren'],
	['7.38', 'Verschil', 'Combineren'],
	['7.39', 'Doorsnede', 'Combineren'],
	['7.40', 'Uitsluiten', 'Combineren'],
	['7.41', 'Nesten', 'Pad bewerken'],
	['7.42', 'Offset…', 'Pad bewerken'],
	['7.43', 'Vereenvoudigen', 'Pad bewerken'],
	['7.44', 'Arcering (hatch)', 'Pad bewerken'],
	['7.45', 'Wobble', 'Pad bewerken'],
	['7.46', 'Hoeken…', null]
])
	await toets(nr, naam, sub ? `menu › ${sub}` : 'menu', inMenu(naam, sub));

// ── Tekst bewerken: alleen bij een tekstvorm ──
await toets('7.18', 'Tekst bewerken…', 'menu (tekst)', async () => {
	await open(`/?tab=design&select=${els[3]}`);
	await objectmenu();
	const n = await page.getByRole('menu').getByText('Tekst bewerken…', { exact: true }).count();
	await page.keyboard.press('Escape');
	return n > 0;
});

// ── Canvasmenu ──
await toets('4.6', 'Naar de selectie', 'canvasmenu + zoombalk', async () => {
	await open();
	await page.mouse.click(760, 640, { button: 'right' });
	await page.waitForTimeout(350);
	const n = await page.getByRole('menu').getByText('Naar de selectie', { exact: true }).count();
	await page.keyboard.press('Escape');
	// Ook via de zoomuitklap.
	await page.locator('.zoom .val').first().click();
	await page.waitForTimeout(300);
	const m = await page.getByRole('menu').getByText('Naar de selectie', { exact: true }).count();
	await page.keyboard.press('Escape');
	return n > 0 && m > 0;
});
await toets('4.4', 'Het hele bed', 'canvasmenu + zoombalk', async () => {
	await open();
	await page.locator('.zoom .val').first().click();
	await page.waitForTimeout(300);
	const n = await page.getByRole('menu').getByText('Het hele bed', { exact: true }).count();
	await page.keyboard.press('Escape');
	return n > 0;
});
await toets('4.9', 'Vastklikken aan/uit', 'zoombalk + canvasmenu', async () => {
	await open();
	const knop = await page.locator('.zoom .snap').count();
	await page.mouse.click(760, 640, { button: 'right' });
	await page.waitForTimeout(350);
	const n = await page
		.getByRole('menu')
		.getByText('Vastklikken op raster en vormen', { exact: true })
		.count();
	await page.keyboard.press('Escape');
	return knop > 0 && n > 0;
});

// ── Afbeeldingsacties: geen afbeelding in dit ontwerp, dus alleen de
//    aanwezigheid in de lijst is hier te toetsen — dat doet acties.test.ts.

// ── De bibliotheek ──
await toets('11.7', 'Herkomst van een preset', 'bibliotheek › rijmenu', async () => {
	await open('/');
	await page.click('button[title="Materiaalbibliotheek"]');
	await page.waitForTimeout(900);
	if (!(await page.locator('.preset .meer').count())) return false;
	await page.locator('.preset .meer').first().click();
	await page.waitForTimeout(350);
	const n = await page.getByRole('menu').getByText('Herkomst en bewijs', { exact: true }).count();
	const m = await page.getByRole('menu').getByText('Waarden bijstellen', { exact: true }).count();
	const w = await page.getByRole('menu').getByText('Instelling verwijderen', { exact: true }).count();
	const d = await page.getByRole('menu').getByText('Delen met Presetariat', { exact: true }).count();
	await page.keyboard.press('Escape');
	return n > 0 && m > 0 && w > 0 && d > 0;
});
await toets('11.2', 'Filteren op materiaal', 'bibliotheek › lijst links', async () => {
	await open('/');
	await page.click('button[title="Materiaalbibliotheek"]');
	await page.waitForTimeout(900);
	return (await page.locator('.matrij').count()) > 1;
});

// ── Een laagrij ──
await toets('8.x', 'Laagacties (rijmenu)', 'Lagen › rechterklik op een rij', async () => {
	await open('/?tab=layers');
	const rij = page.locator('.layer').first();
	const doos = await rij.boundingBox();
	await page.mouse.click(doos.x + 80, doos.y + 14, { button: 'right' });
	await page.waitForTimeout(350);
	const n = await page.getByRole('menu').getByText(/vormen in deze laag selecteren/).count();
	await page.keyboard.press('Escape');
	return n > 0;
});

console.table(uitslag);
const mis = uitslag.filter((r) => r.gevonden !== 'ja');
console.log(mis.length ? `NIET GEVONDEN: ${mis.map((r) => r.actie).join(', ')}` : 'alles bereikbaar');
console.log('paginafouten:', fouten.slice(0, 5));
await b.close();
