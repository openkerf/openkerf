import { browser, open, reset } from './harness.mjs';
await reset();
const b = await browser();
const page = await open(b, { width: 1440, theme: 'dark' });
await page.waitForTimeout(1500);
const out = await page.evaluate(() => {
	const el = document.querySelector('a.machine');
	const cs = getComputedStyle(el);
	return {
		bg: cs.backgroundColor,
		varOnEl: cs.getPropertyValue('--surface-2').trim(),
		varOnRoot: getComputedStyle(document.documentElement).getPropertyValue('--surface-2').trim(),
		rules: [...document.styleSheets].flatMap((sheet) => {
			try { return [...sheet.cssRules]; } catch { return []; }
		}).filter((r) => r.selectorText && r.selectorText.includes('.machine'))
			.map((r) => `${r.selectorText} { ${r.style.background || r.style.backgroundColor} }`)
	};
});
console.log(JSON.stringify(out, null, 1));
await b.close();
