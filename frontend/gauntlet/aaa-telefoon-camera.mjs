/**
 * De twee camerastaten die deze machine niet kan leveren.
 *
 * 1. geen camera beschikbaar (de plugin ontbreekt of het device heeft er geen)
 * 2. camera "aan", maar de stroom komt niet — de eerlijke uitkomst van een
 *    losgetrokken USB-kabel, en precies wat je op een telefoon te zien krijgt.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8106';
const map = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/telefoon';
mkdirSync(map, { recursive: true });

const staten = {
	'cam-weg': { available: false, running: false, reason: 'Geen camera gevonden op deze machine.' },
	'cam-stuk': { available: true, running: true, uri: '0', calibrated: false }
};

const b = await chromium.launch();
for (const [naam, staat] of Object.entries(staten)) {
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
		}, theme);
		await page.route('**/api/camera', (r) =>
			r.fulfill({ contentType: 'application/json', body: JSON.stringify(staat) })
		);
		await page.route('**/api/camera/start', (r) =>
			r.fulfill({ contentType: 'application/json', body: JSON.stringify(staat) })
		);
		await page.route('**/api/camera/stream.mjpeg*', (r) => r.abort());
		await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(1500);
		if (naam === 'cam-stuk') {
			// `shown` gaat pas aan na een geslaagde start, dus die drukken we in.
			await page.getByRole('button', { name: /camera aanzetten/i }).click();
		}
		await page.waitForTimeout(1500);
		await page.screenshot({ path: `${map}/${naam}-390-${theme}.png` });
		await context.close();
	}
}
await b.close();
console.log('klaar');
