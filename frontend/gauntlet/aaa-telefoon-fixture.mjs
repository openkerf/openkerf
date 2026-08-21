/**
 * Eén staat die het mock-device niet kan leveren: een job halverwege.
 *
 * De Lihuiyu-mock springt binnen twee seconden naar 99,97% en blijft daar
 * hangen, dus een ring op 37% krijg je nooit te zien. Hier verbouwen we de
 * binnenkomende snapshot in de browser — puur om de tekening te kunnen
 * beoordelen. Alles op deze schermafdruk is echte UI-code; alleen het getal
 * is gezet.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8106';
const map = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/telefoon';
mkdirSync(map, { recursive: true });

const b = await chromium.launch();
for (const theme of ['light', 'dark']) {
	const context = await b.newContext({
		viewport: { width: 390, height: 844 },
		deviceScaleFactor: 1,
		colorScheme: theme
	});
	const page = await context.newPage();
	await page.addInitScript((t) => {
		const set = () => document.documentElement?.setAttribute('data-theme', t);
		set();
		document.addEventListener('DOMContentLoaded', set);

		const Origineel = window.WebSocket;
		function verbouw(tekst) {
			try {
				const payload = JSON.parse(tekst);
				for (const d of payload?.data?.devices ?? []) {
					for (const j of d.spooler?.jobs ?? []) {
						j.running = true;
						j.status = 'Running';
						j.progress = 0.37;
						j.steps_done = Math.round((j.steps_total ?? 0) * 0.37);
						j.elapsed_seconds = 96;
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
				super.onmessage = (event) =>
					fn(new MessageEvent('message', { data: verbouw(event.data) }));
			}
		};
	}, theme);
	await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3500);
	await page.screenshot({ path: `${map}/r4-job37-390-${theme}.png` });
	await context.close();
}
await b.close();
console.log('klaar');
