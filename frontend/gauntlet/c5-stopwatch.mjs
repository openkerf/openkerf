/**
 * Criticus 5 — de stopwatch.
 *
 * Meten met de Performance API, niet met een gevoel. Koude start, import van
 * 5000 paden, pannen en zoomen met dat bestand, themawissel en de
 * statusupdates.
 */
import { readFileSync } from 'node:fs';
import { browser, open, report, reset } from './harness.mjs';

const BIG = '/Users/Jelle.Tigchelaar/.claude/jobs/ef487fda/tmp/gauntlet/5000.svg';
await reset();
const b = await browser();
const findings = [];

// --- koude start tot bruikbaar canvas
const context = await b.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const t0 = Date.now();
await page.goto('http://127.0.0.1:8090/', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar');
await page.waitForFunction(() => document.querySelector('svg[role="img"]') !== null, { timeout: 20000 });
const usable = Date.now() - t0;
const nav = await page.evaluate(() => {
	const n = performance.getEntriesByType('navigation')[0];
	const paint = performance.getEntriesByType('paint');
	return {
		dom: Math.round(n.domContentLoadedEventEnd),
		load: Math.round(n.loadEventEnd),
		fcp: Math.round(paint.find((p) => p.name === 'first-contentful-paint')?.startTime ?? 0),
		transfer: Math.round(
			performance.getEntriesByType('resource').reduce((s, r) => s + (r.transferSize || 0), 0) / 1024
		)
	};
});
console.log(`koude start: bruikbaar na ${usable} ms | FCP ${nav.fcp} ms | DOM ${nav.dom} ms | overgedragen ${nav.transfer} KB`);
if (usable > 3000) {
	findings.push({ severity: 'major', what: 'Koude start boven 3 s', evidence: `${usable} ms tot bruikbaar canvas` });
}

// --- import van 5000 paden
const svg = readFileSync(BIG, 'utf8');
const importMs = await page.evaluate(async (body) => {
	const form = new FormData();
	form.append('file', new File([body], 'groot.svg', { type: 'image/svg+xml' }));
	const t = performance.now();
	await fetch('/api/job/load', { method: 'POST', body: form });
	return Math.round(performance.now() - t);
}, svg);
await page.reload({ waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar');
const t1 = Date.now();
await page.waitForFunction(() => document.querySelectorAll('svg path').length > 500, { timeout: 60000 });
const drawMs = Date.now() - t1;
const drawn = await page.evaluate(() => document.querySelectorAll('svg path').length);
console.log(`import 5000 paden: ${importMs} ms engine | ${drawMs} ms tot ${drawn} paden in beeld`);
if (importMs + drawMs > 10000) {
	findings.push({ severity: 'major', what: 'Import van 5000 paden duurt te lang',
		evidence: `${importMs} ms engine + ${drawMs} ms tekenen` });
}

// --- pannen en zoomen met dat bestand: beeldsnelheid meten
// Echte muisgebeurtenissen via Playwright (die zijn "trusted"), en één
// richting op: heen en weer zoomen eindigt op de beginmaat en dan meet je
// niets. De teller loopt in de pagina mee.
const bedBefore = await page.evaluate(() => document.querySelector('.bed')?.getBoundingClientRect().width ?? 0);
await page.evaluate(() => {
	window.__frames = 0;
	window.__stop = false;
	const tick = () => { window.__frames++; if (!window.__stop) requestAnimationFrame(tick); };
	requestAnimationFrame(tick);
	window.__t0 = performance.now();
});
const surface = await page.$('svg[role="img"]');
const box = await surface.boundingBox();
await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
for (let i = 0; i < 20; i++) {
	await page.mouse.wheel(0, -120);
	await page.waitForTimeout(30);
}
for (let i = 0; i < 20; i++) {
	await page.mouse.move(box.x + box.width / 2 + i * 4, box.y + box.height / 2 + i * 2);
	await page.waitForTimeout(20);
}
const perf = await page.evaluate(() => {
	window.__stop = true;
	const seconds = (performance.now() - window.__t0) / 1000;
	return { fps: Math.round(window.__frames / seconds),
		bed: document.querySelector('.bed')?.getBoundingClientRect().width ?? 0 };
});
const zoomed = Math.abs(perf.bed - bedBefore) > 1;
console.log(`zoomen met 5000 paden: ${perf.fps} fps (bed ${Math.round(bedBefore)} -> ${Math.round(perf.bed)} px)`);
if (!zoomed) {
	findings.push({ severity: 'major', what: 'De zoommeting bewoog niets — meting ongeldig',
		evidence: `bedbreedte bleef ${Math.round(bedBefore)} px` });
} else if (perf.fps < 45) {
	findings.push({ severity: 'major', what: 'Zoomen met 5000 paden haalt geen vloeiend beeld',
		evidence: `${perf.fps} fps tijdens 20 zoomstappen en 20 muisbewegingen (doel 60, ondergrens 45)` });
}

// --- themawissel: geen flits
const flash = await page.evaluate(async () => {
	const root = document.documentElement;
	const before = getComputedStyle(root).getPropertyValue('--surface-0').trim();
	const t = performance.now();
	root.setAttribute('data-theme', before.startsWith('#f') ? 'dark' : 'light');
	await new Promise((r) => requestAnimationFrame(r));
	const after = getComputedStyle(root).getPropertyValue('--surface-0').trim();
	// Op de duur kijken, niet op de eigenschap: 'all' is gewoon de
	// standaardwaarde en zegt niets zolang de duur nul is.
	const style = getComputedStyle(document.body);
	const transition = `${style.transitionProperty} / ${style.transitionDuration}`;
	return { ms: Math.round(performance.now() - t), before, after, transition };
});
console.log(`themawissel: ${flash.ms} ms, ${flash.before} -> ${flash.after}, body-transitie: ${flash.transition}`);
if (flash.ms > 100) {
	findings.push({ severity: 'major', what: 'Themawissel duurt te lang', evidence: `${flash.ms} ms` });
}

// --- statusupdates mogen de UI niet laten stotteren
const jank = await page.evaluate(async () => {
	let long = 0;
	const observer = new PerformanceObserver((list) => { long += list.getEntries().length; });
	try { observer.observe({ entryTypes: ['longtask'] }); } catch { return -1; }
	await new Promise((r) => setTimeout(r, 4000));
	observer.disconnect();
	return long;
});
console.log(`lange taken tijdens 4 s statusupdates: ${jank}`);
if (jank > 6) {
	findings.push({ severity: 'major', what: 'Statusupdates blokkeren de hoofdthread',
		evidence: `${jank} longtasks (>50ms) in 4 seconden rust` });
}

await page.evaluate(() => fetch('/api/design/clear', { method: 'POST' }));
report('Criticus 5 — stopwatch', findings);
await b.close();
