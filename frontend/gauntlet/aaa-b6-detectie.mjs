/**
 * B6 — machinedetectie in stap 1 van de wizard.
 *
 * Vier staten, want die zie je alle vier in de praktijk:
 *   rust     — vóór je op de knop drukt
 *   bezig    — het zoeken loopt (in het echt 2-3 s; hier vastgezet)
 *   gevonden — er zijn kandidaten (in het echt hardware; hier een stub)
 *   leeg     — niets gevonden, de vaakst voorkomende uitkomst (echte scan)
 *
 * De stub is alleen voor de vondstenstaat: zonder laser op tafel is er niets te
 * fotograferen, en de belangrijkste kaart van deze opdracht ongezien laten is
 * geen optie.
 */
import { mkdirSync } from 'node:fs';
import { browser, open, BASE, WIDTHS } from './harness.mjs';

const DIR = '../../screenshots/aaa/b6';
mkdirSync(new URL(DIR + '/', import.meta.url), { recursive: true });

const VONDSTEN = {
	candidates: [
		{
			id: 'udp:192.168.1.55',
			transport: 'netwerk',
			title: 'Ruida-besturing op het netwerk',
			where: '192.168.1.55',
			detail: 'antwoordde op poort 50200',
			kind: 'co2-ruida',
			confidence: 'zeker',
			why: 'Dit adres antwoordde op de ask die de Ruida-driver ook stelt bij het verbinden.',
			suggestions: [{ key: 'ruida-beta', label: 'Ruida', family: 'K-Series CO2-Laser' }],
			settings: { interface: 'udp', address: '192.168.1.55' }
		},
		{
			id: 'usb:1a86:5512:1.4',
			transport: 'usb',
			title: 'K40-bord (CH341)',
			where: 'USB 1a86:5512',
			detail: null,
			kind: 'co2-k40',
			confidence: 'waarschijnlijk',
			why: 'Dit is de CH341-chip die op de M2- en M3-Nano-borden van een K40 zit.',
			suggestions: [
				{ key: 'm2-nano', label: 'M2 Nano', family: 'K-Series CO2-Laser' },
				{ key: 'm3-nano', label: 'M3 Nano', family: 'K-Series CO2-Laser' }
			],
			settings: {}
		},
		{
			id: 'serial:/dev/cu.usbserial-1420',
			transport: 'serieel',
			title: 'CH340-seriële poort',
			where: '/dev/cu.usbserial-1420',
			detail: 'USB2.0-Serial',
			kind: 'diode',
			confidence: 'onzeker',
			why: 'De CH340 zit op vrijwel elk GRBL-diodeframe, en op veel andere apparaten.',
			suggestions: [
				{ key: 'grbl-generic', label: 'GRBL (generiek)', family: 'Generic' },
				{ key: 'grbl-fluidnc', label: 'FluidNC', family: 'Generic' }
			],
			settings: { serial_port: '/dev/cu.usbserial-1420' }
		}
	],
	searched: ['USB', 'seriële poorten', 'netwerk 192.168.1.0/24'],
	notes: [],
	duration_ms: 2410
};

async function shoot(page, naam, breedte, thema) {
	await page.screenshot({
		path: new URL(`${DIR}/${naam}-${breedte}-${thema}.png`, import.meta.url).pathname,
		fullPage: true
	});
}

const b = await browser();

for (const [device, breedte] of Object.entries(WIDTHS)) {
	for (const thema of ['light', 'dark']) {
		// --- rust ------------------------------------------------------------
		let page = await open(b, { width: breedte, theme: thema, path: '/setup/kind' });
		await shoot(page, 'rust', breedte, thema);

		// --- bezig -----------------------------------------------------------
		await page.route('**/api/machines/scan*', async (route) => {
			await new Promise((r) => setTimeout(r, 30000));
			await route.abort();
		});
		await page.getByRole('button', { name: 'Machines zoeken' }).click();
		await page.waitForTimeout(2500);
		await shoot(page, 'bezig', breedte, thema);
		// En de staat die je in de praktijk het meest vervelend vindt: het duurt
		// te lang. Na acht seconden hoort er een uitweg te staan.
		await page.waitForTimeout(7000);
		await shoot(page, 'traag', breedte, thema);
		await page.context().close();

		// --- gevonden --------------------------------------------------------
		page = await open(b, { width: breedte, theme: thema, path: '/setup/kind' });
		await page.route('**/api/machines/scan*', (route) =>
			route.fulfill({ json: VONDSTEN })
		);
		await page.getByRole('button', { name: 'Machines zoeken' }).click();
		await page.waitForSelector('.vondst', { timeout: 5000 });
		await page.waitForTimeout(300);
		await shoot(page, 'gevonden', breedte, thema);
		await page.context().close();

		// --- leeg (echte scan over het echte netwerk) ------------------------
		page = await open(b, { width: breedte, theme: thema, path: '/setup/kind' });
		await page.getByRole('button', { name: 'Machines zoeken' }).click();
		await page.waitForSelector('.niets', { timeout: 20000 });
		await shoot(page, 'leeg', breedte, thema);
		await page.context().close();
	}
}

await b.close();
console.log('klaar —', BASE);
