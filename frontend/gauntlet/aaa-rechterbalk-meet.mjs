/**
 * Meten in plaats van kijken: past de selectiekaart binnen het paneel, halen
 * de raakdoelen 44 px met 12 px ertussen, en hoe hoog is het geheel?
 */
import { chromium } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8131';

const design = await (await fetch(`${BASE}/api/design`)).json();
// Langste naam eerst: dat is de zaak waarin de kopregel de kaart uit liep.
const alle = [...design.elements]
	.sort((a, b) => b.label.length - a.label.length)
	.map((e) => e.id);

const b = await chromium.launch();
for (const [naam, sel] of [
	['een', [alle[0]]],
	['meer', alle.slice(0, 3)]
]) {
	for (const width of [1440, 1024]) {
		const ctx = await b.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
		const page = await ctx.newPage();
		await page.goto(`${BASE}/?tab=design&select=${sel.join(',')}`, {
			waitUntil: 'domcontentloaded'
		});
		await page.waitForSelector('.statusbar', { timeout: 20000 }).catch(() => {});
		await page.waitForTimeout(1200);
		const later = page.getByRole('button', { name: /later/i });
		if (await later.count()) await later.first().click().catch(() => {});
		await page.waitForTimeout(400);

		const uitkomst = await page.evaluate(() => {
			const scroll = document.querySelector('.panel-scroll');
			const kaart = document.querySelector('.selected');
			if (!scroll || !kaart) return null;
			const sr = scroll.getBoundingClientRect();
			const kr = kaart.getBoundingClientRect();
			// Overloop van kínderen, niet van de kaart zelf. Een grid-item
			// krimpt niet onder zijn inhoud en steekt dan buiten de kaart uit
			// terwijl de kaart netjes binnen het paneel blijft — de kaart meten
			// mist dat volledig, en precies die failure stond op de screenshot.
			const cs = getComputedStyle(kaart);
			const binnenRechts =
				kr.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth);
			const uitstekend = [...kaart.querySelectorAll('*')]
				.map((n) => ({
					wat: (n.getAttribute('aria-label') || n.className || n.tagName)
						.toString()
						.slice(0, 28),
					over: +(n.getBoundingClientRect().right - binnenRechts).toFixed(1)
				}))
				.filter((x) => x.over > 0.5);
			const doelen = [...kaart.querySelectorAll('button, input, summary')]
				.map((n) => {
					const r = n.getBoundingClientRect();
					return {
						wat: (n.getAttribute('aria-label') || n.textContent || n.tagName).trim().slice(0, 26),
						w: Math.round(r.width),
						h: Math.round(r.height),
						x: Math.round(r.x),
						y: Math.round(r.y),
						r: Math.round(r.right)
					};
				})
				.filter((d) => d.w > 0);
			// Kleinste tussenruimte tussen twee doelen die elkaar op dezelfde
			// regel raken.
			let kleinsteGat = Infinity;
			let gatTussen = null;
			for (const a of doelen)
				for (const c of doelen) {
					// Alleen buren op dezelfde regel; anders vergelijk je een knop
					// bovenin met een veld onderin en meet je onzin.
					if (a === c || c.x < a.r) continue;
					if (c.y > a.y + a.h - 6 || a.y > c.y + c.h - 6) continue;
					const gat = c.x - a.r;
					if (gat >= 0 && gat < kleinsteGat) {
						kleinsteGat = gat;
						gatTussen = `${a.wat} | ${c.wat}`;
					}
				}
			return {
				paneel: Math.round(sr.width),
				kaartRechts: Math.round(kr.right),
				paneelRechts: Math.round(sr.right),
				overloop: Math.round(kr.right - sr.right),
				uitstekend,
				hoogte: Math.round(scroll.scrollHeight),
				zichtbaar: Math.round(scroll.clientHeight),
				teKlein: doelen.filter((d) => d.h < 44 || d.w < 44).map((d) => `${d.wat}=${d.w}x${d.h}`),
				gatTussen,
				kleinsteDoel: Math.min(...doelen.map((d) => Math.min(d.h, d.w))),
				kleinsteGat: kleinsteGat === Infinity ? null : kleinsteGat,
				aantal: doelen.length
			};
		});
		console.log(naam, width, JSON.stringify(uitkomst));
		await ctx.close();
	}
}
await b.close();
