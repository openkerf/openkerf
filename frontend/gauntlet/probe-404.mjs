import { browser, open, reset } from './harness.mjs';
await reset();
const b = await browser();
for (const [theme, width] of [['light', 1440], ['dark', 1440], ['light', 1024], ['light', 390]]) {
	const ctx = await b.newContext({ viewport: { width, height: 900 }, colorScheme: theme });
	const page = await ctx.newPage();
	const bad = [];
	page.on('response', (r) => { if (r.status() >= 400) bad.push(`${r.status()} ${r.url().slice(-60)}`); });
	await page.goto('http://127.0.0.1:8090/', { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar');
	await page.waitForTimeout(1200);
	console.log(theme, width, '->', bad.length ? bad.join(' | ') : 'geen mislukte verzoeken');
	await ctx.close();
}
await b.close();
