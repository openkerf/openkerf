/**
 * Draait het ontwerp zichzelf op hol na één wijziging?
 *
 * `design.load()` set `loading` (een $state) op true en leest die waarde ook
 * als herintredingsslot. Een $effect dat load() aanroept, neemt daarmee
 * `loading` als afhankelijkheid over: laden set hem, dat maakt het effect
 * ongeldig, dat roept opnieuw aan. Eén echte wijziging is genoeg om die lus te
 * starten, en hij stopt daarna nooit meer — ook niet als je het werk weggooit.
 *
 * Gemeten in verzoeken per seconde naar /api/design.
 */
import { browser, open, reset } from '/Users/Jelle.Tigchelaar/git/openkerf/frontend/gauntlet/harness.mjs';

const b = await browser();
await reset();
const page = await open(b, { width: 1440 });
await page.waitForTimeout(1500);
const later = await page.$('button:has-text("Later")');
if (later) { await later.click(); await page.waitForTimeout(400); }

let n = 0;
page.on('response', (r) => {
	const p = new URL(r.url()).pathname;
	if (p === '/api/design') n++;
});

async function perSeconde(label, seconden = 5) {
	const start = n;
	await page.waitForTimeout(seconden * 1000);
	const tempo = (n - start) / seconden;
	console.log(`${label.padEnd(26)} ${tempo.toFixed(1)} verzoeken/s naar /api/design`);
	return tempo;
}

const rust = await perSeconde('voor de wijziging');

await page.evaluate(() =>
	fetch('/api/design/elements', {
		method: 'POST', headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ type: 'rect', x_mm: 20, y_mm: 20, width_mm: 30, height_mm: 20 })
	})
);
await page.waitForTimeout(2000);
const na = await perSeconde('na één getekende vorm');

await page.evaluate(() => fetch('/api/design/clear', { method: 'POST' }));
await page.waitForTimeout(2000);
const leeg = await perSeconde('na het leegmaken');

await b.close();

// Eén wijziging mag een handvol herlaadslagen kosten, geen stroom.
const grens = 3;
const stuk = [['rust', rust], ['na wijziging', na], ['na leegmaken', leeg]].filter(([, v]) => v > grens);
if (stuk.length) {
	console.error(`\nFOUT: ${stuk.map(([k, v]) => `${k} ${v.toFixed(1)}/s`).join(', ')} — grens is ${grens}/s`);
	process.exit(1);
}
console.log('\nGoed: het ontwerp laadt alleen bij een wijziging.');
