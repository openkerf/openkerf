/**
 * Twee staten die het mock-device niet levert, en die precies de grens van
 * gat J8 aftasten:
 *
 * - `vers`: een job die net gespoold is (loopt niet, nul voortgang). Hoort
 *   "Bezig" te zijn met een Pauze-knop — niet "Pauze" met een Hervat-knop.
 * - `pauze`: de machine meldt zelf `laser_status: "pause"`. Hoort "Pauze" te
 *   zijn met een Hervat-knop.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8106';
const map = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/telefoon';
mkdirSync(map, { recursive: true });

const staten = {
	vers: { laser: 'idle', running: false, progress: 0, elapsed: 0, status: 'Waiting' },
	pauze: { laser: 'pause', running: false, progress: 0.42, elapsed: 110, status: 'Paused' }
};

const b = await chromium.launch();
for (const [naam, s] of Object.entries(staten)) {
	const context = await b.newContext({
		viewport: { width: 390, height: 844 },
		deviceScaleFactor: 1,
		colorScheme: 'light'
	});
	const page = await context.newPage();
	await page.addInitScript((s) => {
		const Origineel = window.WebSocket;
		function verbouw(tekst) {
			try {
				const payload = JSON.parse(tekst);
				for (const d of payload?.data?.devices ?? []) {
					d.laser_status = s.laser;
					for (const j of d.spooler?.jobs ?? []) {
						j.running = s.running;
						j.status = s.status;
						j.progress = s.progress;
						j.elapsed_seconds = s.elapsed;
						j.steps_done = Math.round((j.steps_total ?? 0) * s.progress);
						j.estimate_seconds = 260;
					}
				}
				return JSON.stringify(payload);
			} catch {
				return tekst;
			}
		}
		window.WebSocket = class extends Origineel {
			set onmessage(fn) {
				super.onmessage = (e) => fn(new MessageEvent('message', { data: verbouw(e.data) }));
			}
		};
	}, s);
	await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);
	const knoppen = await page.$$eval('.noodrem button', (ns) =>
		ns.map((n) => ({ t: (n.textContent ?? '').trim(), uit: n.disabled }))
	);
	const kop = await page.locator('header .staat').first().textContent();
	console.log(naam, '→ kop:', kop?.trim(), '| noodrem:', JSON.stringify(knoppen));
	await page.screenshot({ path: `${map}/j8-${naam}-390-light.png` });
	await context.close();
}
await b.close();
