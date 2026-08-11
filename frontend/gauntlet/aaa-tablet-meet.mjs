/** Raakdoelen op tablet: grootte, onderlinge afstand, en waar de kernacties zitten. */
import { browser, open } from './harness.mjs';

const b = await browser();
const page = await open(b, { width: 1024, theme: 'light', path: '/?tab=job' });
const later = page.getByRole('button', { name: /later/i });
if (await later.count()) await later.first().click().catch(() => {});
await page.waitForTimeout(400);

const alles = await page.$$eval(
	'.rail button, .rail label, .topbar button, .topbar a, .topbar label, .camstrip button, .camstrip input, .paneelgreep, .sheet, .zoombar button, .zoombar *',
	(nodes) =>
		nodes
			.filter((n) => n.getBoundingClientRect().width > 0)
			.map((n) => {
				const r = n.getBoundingClientRect();
				return {
					wat: (n.getAttribute('title') || n.getAttribute('aria-label') || n.textContent || '').trim().slice(0, 34),
					zone: n.closest('.rail') ? 'rail' : n.closest('.topbar') ? 'topbar' : n.closest('.camstrip') ? 'cam' : 'anders',
					x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)
				};
			})
);
console.log('--- doelen ---');
for (const d of alles) console.log(`${d.zone.padEnd(7)} ${String(d.w).padStart(4)}x${String(d.h).padStart(3)} @${d.x},${d.y}  ${d.wat}`);

// Afstand tussen Stop en Start job in de bovenbalk
const paar = alles.filter((d) => /^Stop$|Start job/.test(d.wat));
if (paar.length === 2) {
	const [a, c] = paar.sort((p, q) => p.x - q.x);
	console.log(`\nStop→Start gat: ${c.x - (a.x + a.w)}px`);
}

// Kan je pauzeren zonder het paneel? Tellen wat er per tab/staat bereikbaar is.
for (const tab of ['design', 'layers', 'job']) {
	await page.goto(`${process.env.OK_BASE}/?tab=${tab}`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(900);
	const n = await page.getByRole('button', { name: /pauze|pauzeer/i }).count();
	console.log(`tab=${tab}: pauzeknoppen zichtbaar = ${n}`);
}
await b.close();
