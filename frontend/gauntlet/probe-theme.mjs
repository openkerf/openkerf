import { browser, open, reset } from './harness.mjs';
await reset();
const b = await browser();
const page = await open(b, { width: 1440, theme: 'dark' });
const info = await page.evaluate(() => {
	const out = [];
	let el = document.querySelector('.machine > span:nth-child(2)');
	while (el && el !== document.documentElement) {
		const s = getComputedStyle(el);
		out.push(`${el.tagName.toLowerCase()}.${String(el.className ?? '').slice(0, 20)} bg=${s.backgroundColor} opacity=${s.opacity} filter=${s.filter}`);
		el = el.parentElement;
	}
	return { chain: out, theme: document.documentElement.getAttribute('data-theme'),
		surface1: getComputedStyle(document.documentElement).getPropertyValue('--surface-1').trim(),
		bodyBg: getComputedStyle(document.body).backgroundColor };
});
console.log('data-theme:', info.theme, '| --surface-1:', info.surface1, '| body:', info.bodyBg);
console.log(info.chain.join('\n'));
await b.close();
