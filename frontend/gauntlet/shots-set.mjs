/**
 * De volledige screenshotset: elk scherm en elke relevante staat, op drie
 * apparaatklassen in beide thema's. Input voor de experts, niet bijlage.
 */
import { mkdirSync } from 'node:fs';
import { browser, open, reset } from './harness.mjs';

const RONDE = process.env.RONDE ?? 'ronde-2';
const DIR = `../screenshots/${RONDE}`;
mkdirSync(DIR, { recursive: true });

await reset();
const b = await browser();

// Een ontwerp met inhoud, zodat de schermen niet leeg zijn.
{
	const page = await open(b, { width: 1440 });
	await page.evaluate(async () => {
		await fetch('/api/design/elements', { method: 'POST', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ type: 'rect', x_mm: 20, y_mm: 20, width_mm: 60, height_mm: 40 }) });
		await fetch('/api/design/elements', { method: 'POST', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ type: 'circle', cx_mm: 150, cy_mm: 60, r_mm: 25 }) });
		await fetch('/api/design/generate/qrcode', { method: 'POST', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ text: 'openkerf', size_mm: 30, x_mm: 210, y_mm: 30 }) });
		const m = await (await fetch('/api/library/materials', { method: 'POST',
			headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'Berkentriplex' }) })).json();
		for (const [op, s, p, src] of [['snijden', 12, 65, 'testraster'], ['graveren-vector', 250, 20, 'geextrapoleerd']]) {
			await fetch('/api/library/presets', { method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ material_id: m.id, operation: op, thickness_mm: 3, speed_mm_s: s, power_percent: p, source: src }) });
		}
	});
	await page.context().close();
}

const SCHERMEN = [
	['canvas', async () => {}],
	['lagen', async (p) => { await p.click('button[role="tab"]:has-text("Lagen")').catch(() => {}); }],
	['job', async (p) => { await p.click('button[role="tab"]:has-text("Job")').catch(() => {}); }],
	['bibliotheek', async (p) => { await p.click('button[title="Materiaalbibliotheek"]').catch(() => {}); }],
	['generatoren', async (p) => { await p.click('button[title^="Generatoren"]').catch(() => {}); }],
	['clipart', async (p) => { await p.click('button[title^="Clipart"]').catch(() => {}); }],
	['setup', async (p) => { await p.goto('http://127.0.0.1:8090/setup', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(600); }]
];

for (const [klasse, breedte] of [['desktop', 1440], ['tablet', 1024], ['telefoon', 390]]) {
	for (const thema of ['licht', 'donker']) {
		for (const [naam, stap] of SCHERMEN) {
			const page = await open(b, { width: breedte, theme: thema === 'donker' ? 'dark' : 'light' });
			await page.waitForTimeout(500);
			await stap(page);
			await page.waitForTimeout(700);
			await page.screenshot({ path: `${DIR}/${klasse}-${thema}-${naam}.png` });
			await page.context().close();
		}
	}
	console.log(klasse, 'klaar');
}
await b.close();
