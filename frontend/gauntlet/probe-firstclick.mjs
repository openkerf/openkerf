import { browser, open } from './harness.mjs';
const b = await browser();
for (const wachten of [0, 1500, 4000]) {
	const page = await open(b, { width: 1440 });
	await page.waitForTimeout(wachten);
	const knop = await page.$('button[title^="Generatoren"]');
	await knop.click({ force: true });
	await page.waitForTimeout(500);
	const open1 = await page.$$eval('.backdrop', (n) => n.length);
	console.log(`extra wachttijd ${wachten} ms -> venster open: ${open1 ? 'ja' : 'NEE'}`);
	await page.context().close();
}
await b.close();
