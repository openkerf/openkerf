import { chromium } from 'playwright';
const b = await chromium.launch();
for (const theme of ['light', 'dark']) {
	const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: theme });
	const page = await ctx.newPage();
	const errs = [];
	page.on('pageerror', (e) => errs.push(String(e.stack ?? e).slice(0, 300)));
	if (theme === 'dark') {
		await page.addInitScript(() => document.documentElement.setAttribute('data-theme', 'dark'));
	}
	await page.goto('http://127.0.0.1:8090/', { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar');
	await page.waitForTimeout(800);
	console.log(`${theme}: ${errs.length} fouten`, errs[0] ? '\n  ' + errs[0].split('\n')[0] : '');
	if (errs[0]) console.log('  ' + errs[0].split('\n').slice(1, 3).join('\n  '));
	await ctx.close();
}
await b.close();
