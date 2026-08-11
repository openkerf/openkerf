import { browser, open } from './harness.mjs';
import { mkdirSync } from 'node:fs';

const DIR = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/lagen';
mkdirSync(DIR, { recursive: true });
const ronde = process.argv[2] ?? 'r1';

const b = await browser();
for (const [naam, width] of [['1440', 1440], ['1024', 1024], ['390', 390]]) {
	for (const theme of ['light', 'dark']) {
		for (const [tab, label] of [['layers', 'lagen'], ['design', 'bewerken']]) {
			const page = await open(b, { width, theme, path: `/?tab=${tab}` });
			// Herstelvenster wegklikken
			const later = page.locator('button', { hasText: 'Later' });
			if (await later.count()) await later.first().click().catch(() => {});
			// Op tablet moet het paneel open
			const opener = page.locator('button[aria-label*="igenschap"], .paneel-knop');
			if (width < 1200 && (await opener.count())) await opener.first().click().catch(() => {});
			await page.waitForTimeout(600);
			await page.screenshot({ path: `${DIR}/${ronde}-${label}-${naam}-${theme}.png`, fullPage: false });
			if (page.problems?.length) console.log(naam, theme, tab, page.problems.slice(0, 3));
			await page.context().close();
		}
	}
}
await b.close();
console.log('klaar', ronde);
