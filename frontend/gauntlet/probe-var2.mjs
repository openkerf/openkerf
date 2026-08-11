import { chromium } from 'playwright';
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark' });
const page = await ctx.newPage();
await page.addInitScript(() => {
	document.addEventListener('DOMContentLoaded', () =>
		document.documentElement.setAttribute('data-theme', 'dark'));
});
await page.goto('http://127.0.0.1:8090/', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar');
await page.waitForTimeout(1500);
console.log('machine-bg:', await page.evaluate(() => getComputedStyle(document.querySelector('a.machine')).backgroundColor));
await b.close();
