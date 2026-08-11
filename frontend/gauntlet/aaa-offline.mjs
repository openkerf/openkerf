/**
 * Offline, fouten en tokens.
 *
 * De verbinding trekken we er echt onderuit (context.setOffline), zodat de
 * WebSocket sluit zoals hij dat bij een herstartende server ook doet.
 */
import { mkdirSync } from 'node:fs';
import { browser, open, BASE } from './harness.mjs';

const DIR = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/lege-staten';
mkdirSync(DIR, { recursive: true });

const only = process.argv.slice(2);
const wil = (n) => only.length === 0 || only.some((o) => n.includes(o));

async function weg(page) {
	const rond = page.getByRole('button', { name: /rondkijken zonder machine/i });
	if (await rond.count().catch(() => 0)) {
		await rond.first().click().catch(() => {});
		await page.waitForTimeout(900);
	}
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count().catch(() => 0)) await later.first().click().catch(() => {});
	await page.waitForTimeout(200);
}

const STATEN = [
	{
		naam: 'verbinding-weg',
		pad: '/?tab=job',
		doe: async (page) => {
			await page.context().setOffline(true);
			await page.waitForTimeout(4000);
		}
	},
	{
		naam: 'verbinding-weg-ontwerp',
		pad: '/?tab=design',
		doe: async (page) => {
			await page.context().setOffline(true);
			await page.waitForTimeout(4000);
		}
	},
	{
		naam: 'verbinding-weg-tijdens-actie',
		pad: '/?tab=job',
		doe: async (page) => {
			await page.context().setOffline(true);
			await page.waitForTimeout(2500);
			// Wat gebeurt er als je nu op een knop drukt die de machine raakt?
			const home = page.getByRole('button', { name: /^home$/i }).first();
			if (await home.count()) await home.click().catch(() => {});
			await page.waitForTimeout(2500);
		}
	},
	{
		naam: 'token-onzin',
		pad: '/?tab=job',
		voor: async (page) => {
			await page.addInitScript(() => localStorage.setItem('openkerf.token', 'nergens-op-slaand'));
		},
		doe: async (page) => {
			const home = page.getByRole('button', { name: /^home$/i }).first();
			if (await home.count()) await home.click().catch(() => {});
			await page.waitForTimeout(1200);
		}
	},
	{
		naam: 'kapot-bestand',
		pad: '/?tab=job',
		doe: async (page) => {
			const uit = await page.evaluate(async (base) => {
				const out = {};
				for (const [route, veld] of [
					['/api/job/load', 'file'],
					['/api/design/elements', 'file']
				]) {
					const body = new FormData();
					body.append(
						veld,
						new Blob(['dit is geen tekening'], { type: 'image/svg+xml' }),
						'kapot.svg'
					);
					out[route] = await fetch(base + route, { method: 'POST', body })
						.then(async (r) => `${r.status} ${(await r.text()).slice(0, 200)}`)
						.catch((e) => String(e));
				}
				return out;
			}, BASE);
			console.log('  ', JSON.stringify(uit, null, 1));
			await page.waitForTimeout(400);
		}
	}
];

const b = await browser();
for (const staat of STATEN) {
	if (!wil(staat.naam)) continue;
	for (const width of [1440, 1024, 390]) {
		for (const theme of ['light', 'dark']) {
			const page = await open(b, { width, theme, path: staat.pad });
			if (staat.voor) {
				await staat.voor(page);
				await page.reload({ waitUntil: 'domcontentloaded' });
				await page.waitForTimeout(1200);
			}
			await weg(page);
			await staat.doe(page);
			await page.screenshot({ path: `${DIR}/${staat.naam}-${width}-${theme}.png` });
			console.log(`${staat.naam}-${width}-${theme}.png`);
			await page.context().setOffline(false).catch(() => {});
			await page.context().close();
		}
	}
}
await b.close();
