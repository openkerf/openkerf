/**
 * Screenshotset voor het oppervlak "Donker thema, over alles heen".
 *
 * Niet één scherm maar de samenhang: elk paneel, elk venster, in beide thema's
 * naast elkaar, zodat je kunt zien of donker even goed leest als licht.
 */
import { mkdirSync } from 'node:fs';
import { browser, open, reset, BASE } from './harness.mjs';

const RONDE = process.env.RONDE ?? 'r1';
const DIR = `../screenshots/aaa/donker`;
mkdirSync(DIR, { recursive: true });

async function dismiss(page) {
	const later = await page.$('button:has-text("Later")');
	if (later) {
		await later.click();
		await page.waitForTimeout(300);
	}
}

/** Werk op het bed: vijf vormen over vijf lagen, waaronder een zwarte. */
async function vul(page) {
	await page.evaluate(async () => {
		const post = (u, b) =>
			fetch(u, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(b)
			}).then((r) => r.json());
		const patch = (u, b) =>
			fetch(u, {
				method: 'PATCH',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(b)
			});
		const els = [];
		els.push(await post('/api/design/elements', {
			type: 'rect', x_mm: 20, y_mm: 20, width_mm: 70, height_mm: 45
		}));
		els.push(await post('/api/design/elements', { type: 'circle', cx_mm: 150, cy_mm: 55, r_mm: 28 }));
		els.push(await post('/api/design/generate/qrcode', {
			text: 'openkerf', size_mm: 32, x_mm: 225, y_mm: 25
		}));
		els.push(await post('/api/design/generate/polygon', { sides: 6, radius_mm: 28, cx_mm: 60, cy_mm: 130 }));
		els.push(await post('/api/design/elements', {
			type: 'rect', x_mm: 130, y_mm: 110, width_mm: 100, height_mm: 60
		}));

		const kleuren = ['#E5484D', '#FFC53D', '#0090FF', '#000000', '#8D6E63'];
		const soorten = ['cut', 'engrave', 'cut', 'engrave', 'raster'];
		const namen = ['Snijden 3mm', 'Graveren logo', 'Snijden binnen', 'Geïmporteerd zwart', 'Raster foto'];
		const alles = await fetch('/api/design').then((r) => r.json());
		void alles;
		for (let i = 0; i < 5; i++) {
			const op = await post('/api/design/operations', {
				type: soorten[i], label: namen[i], speed: 20 + i * 10, power_percent: 40 + i * 8
			});
			const opId = op?.id ?? op?.operation?.id ?? op?.operation_id;
			if (opId) {
				await patch(`/api/design/operations/${opId}`, { color: kleuren[i] });
				const elId = els[i]?.id ?? els[i]?.element?.id ?? els[i]?.element_id;
				if (elId) await post('/api/design/assign', { ids: [elId], operation_id: opId });
			}
		}
	});
	await page.waitForTimeout(1200);
}

const SCHERMEN = [
	['job', '/?tab=job', async (p) => { await vul(p); }],
	['ontwerp', '/?tab=design', async (p) => { await vul(p); }],
	['lagen', '/?tab=layers', async (p) => { await vul(p); }],
	['leeg-bed', '/?tab=design', async () => {}],
	['materiaal', '/?tab=design', async (p) => {
		await p.click('button[title="Materiaalbibliotheek"]').catch(async () => {
			await p.click('button[title="Meer gereedschap"]');
			await p.waitForTimeout(300);
			await p.click('button[title="Materiaalbibliotheek"]');
		});
		await p.waitForTimeout(1200);
	}],
	['testraster', '/?tab=design', async (p) => {
		await p.click('button[title="Testraster"]').catch(async () => {
			await p.click('button[title="Meer gereedschap"]');
			await p.waitForTimeout(300);
			await p.click('button[title="Testraster"]');
		});
		await p.waitForTimeout(1200);
	}],
	['generatoren', '/?tab=design', async (p) => {
		await p.click('button[title^="Generatoren"]').catch(async () => {
			await p.click('button[title="Meer gereedschap"]');
			await p.waitForTimeout(300);
			await p.click('button[title^="Generatoren"]');
		});
		await p.waitForTimeout(1000);
	}],
	['setup', '/setup', async () => {}]
];

const b = await browser();
for (const [klasse, breedte] of [['desktop', 1440], ['tablet', 1024], ['telefoon', 390]]) {
	for (const thema of ['licht', 'donker']) {
		for (const [naam, pad, stap] of SCHERMEN) {
			if (breedte === 390 && ['lagen', 'generatoren'].includes(naam)) continue;
			if (breedte === 1024 && !['job', 'ontwerp', 'lagen', 'materiaal'].includes(naam)) continue;
			await reset();
			const page = await open(b, {
				width: breedte,
				theme: thema === 'donker' ? 'dark' : 'light',
				path: pad
			});
			await dismiss(page);
			try {
				await stap(page);
			} catch (e) {
				console.log(`  ! ${naam} ${klasse} ${thema}: ${String(e).slice(0, 100)}`);
			}
			await page.waitForTimeout(400);
			await page.screenshot({ path: `${DIR}/${RONDE}-${naam}-${klasse}-${thema}.png` });
			console.log(`${RONDE}-${naam}-${klasse}-${thema}.png`);
			await page.context().close();
		}
	}
}
await b.close();
console.log('klaar —', BASE);
