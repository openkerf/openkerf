/**
 * Criticus 3 — de interactiepurist.
 *
 * Staten, motion en toetsenbord. Layout-shift bij hover of focus is de
 * belangrijkste meting: die verraadt een rand die verschijnt in plaats van
 * van kleur wisselt.
 */
import { browser, open, report, reset } from './harness.mjs';

await reset();
const b = await browser();
const findings = [];
const page = await open(b, { width: 1440 });
await page.waitForTimeout(500);

// --- layout-shift bij hover en focus
const shifts = [];
const buttons = await page.$$('button:not([disabled])');
for (const button of buttons.slice(0, 40)) {
	const before = await button.boundingBox();
	if (!before || before.width === 0) continue;
	await button.hover({ force: true }).catch(() => {});
	await page.waitForTimeout(60);
	const hovered = await button.boundingBox();
	await button.focus().catch(() => {});
	await page.waitForTimeout(60);
	const focused = await button.boundingBox();
	const label = (await button.textContent())?.trim().slice(0, 18) || (await button.getAttribute('aria-label')) || '?';
	const moved = (a, c) =>
		Math.abs(a.x - c.x) > 0.5 || Math.abs(a.y - c.y) > 0.5 ||
		Math.abs(a.width - c.width) > 0.5 || Math.abs(a.height - c.height) > 0.5;
	if (hovered && moved(before, hovered)) shifts.push(`"${label}" hover: ${before.width}x${before.height} -> ${hovered.width}x${hovered.height}`);
	if (focused && moved(before, focused)) shifts.push(`"${label}" focus: ${before.width}x${before.height} -> ${focused.width}x${focused.height}`);
}
if (shifts.length) {
	findings.push({ severity: 'major', what: `${shifts.length} componenten verspringen bij hover of focus`,
		evidence: shifts.slice(0, 6).join(' | ') });
}

// --- zichtbare focusring in accent
const focusRing = await page.evaluate(() => {
	const el = document.querySelector('button:not([disabled])');
	el.focus();
	const s = getComputedStyle(el);
	const pseudo = getComputedStyle(el, ':focus-visible');
	return { outline: s.outlineStyle + ' ' + s.outlineWidth + ' ' + s.outlineColor,
		pseudoOutline: pseudo.outlineColor, accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() };
});
if (focusRing.outline.startsWith('none')) {
	findings.push({ severity: 'major', what: 'Geen zichtbare focusring op knoppen',
		evidence: `outline = ${focusRing.outline}` });
}

// --- transitieduur
const durations = await page.$$eval('*', (nodes) => {
	const found = {};
	for (const n of nodes.slice(0, 900)) {
		const d = getComputedStyle(n).transitionDuration;
		if (!d || d === '0s') continue;
		for (const part of d.split(',').map((x) => x.trim())) found[part] = (found[part] ?? 0) + 1;
	}
	return found;
});
const allowed = new Set(['0.15s', '0.25s', '150ms', '250ms']);
const odd = Object.entries(durations).filter(([d]) => !allowed.has(d));
if (odd.length) {
	findings.push({ severity: 'minor', what: 'Transitieduur buiten 150/250ms',
		evidence: odd.map(([d, n]) => `${d} (${n}x)`).join(' | ') });
}

// --- prefers-reduced-motion
const reduced = await b.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
const rp = await reduced.newPage();
await rp.goto('http://127.0.0.1:8090/', { waitUntil: 'domcontentloaded' });
await rp.waitForSelector('.statusbar', { timeout: 20000 });
await rp.waitForTimeout(400);
const stillAnimating = await rp.$$eval('*', (nodes) =>
	nodes
		.filter((n) => {
			const s = getComputedStyle(n);
			// 0,01ms is hoe de reduced-motion-regel een animatie uitzet; dat telt
			// als stil, niet als lopend.
			const seconds = parseFloat(s.animationDuration) * (/ms$/.test(s.animationDuration) ? 0.001 : 1);
			return s.animationName !== 'none' && s.animationPlayState === 'running' && seconds > 0.05;
		})
		.map((n) => `${n.tagName.toLowerCase()}.${String(n.className?.baseVal ?? n.className ?? '').slice(0, 22)}:${getComputedStyle(n).animationName}`)
		.slice(0, 6)
);
if (stillAnimating.length) {
	findings.push({ severity: 'major', what: 'Animaties lopen door bij prefers-reduced-motion',
		evidence: stillAnimating.join(' | ') + ' (alleen jobvoortgang mag)' });
}
await reduced.close();

// --- dode klikzones: cursor pointer zonder handler of href
const dead = await page.$$eval('*', (nodes) =>
	nodes
		.filter((n) => {
			if (getComputedStyle(n).cursor !== 'pointer') return false;
			if (n.closest('button, a, label, input, select, [role="button"], [onclick]')) return false;
			return n.getBoundingClientRect().width > 0;
		})
		.map((n) => `${n.tagName.toLowerCase()}.${String(n.className ?? '').slice(0, 24)}`)
		.slice(0, 6)
);
if (dead.length) {
	findings.push({ severity: 'minor', what: 'Cursor belooft klikbaar zonder actie', evidence: dead.join(' | ') });
}

// --- sneltoetsen op het canvas: pijl = 0,1 mm, shift = 1 mm
await page.evaluate(async () => {
	await fetch('/api/design/elements', {
		method: 'POST', headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ type: 'rect', x_mm: 40, y_mm: 40, width_mm: 20, height_mm: 10 })
	});
});
await page.reload({ waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar', { timeout: 20000 });
await page.waitForTimeout(700);
// Op de omtrek klikken, niet in het midden: een vorm zonder vulling heeft
// daar niets om te raken — net als in Inkscape en LightBurn.
// Playwright's boundingBox() telt de 12px trefzone mee, dus box.x ligt elf
// pixels naast de lijn. Het punt in de pagina zelf uitrekenen raakt wel.
const spot = await page.evaluate(() => {
	const el = document.querySelector('svg path.hit');
	if (!el) return null;
	const r = el.getBoundingClientRect();
	return { x: r.x + 1, y: r.y + r.height / 2 };
});
if (spot) await page.mouse.click(spot.x, spot.y);
await page.waitForTimeout(500);
console.log('  selectie:', await page.evaluate(() => location.search) || '(geen)');
const readX = async () =>
	page.evaluate(async () => {
		const d = await (await fetch('/api/design')).json();
		const e = d.elements[0];
		return e ? +(e.bounds[0] / d.units_per_mm).toFixed(3) : null;
	});
const start = await readX();
await page.keyboard.press('ArrowRight');
await page.waitForTimeout(700);
const afterArrow = await readX();
await page.keyboard.down('Shift');
await page.keyboard.press('ArrowRight');
await page.keyboard.up('Shift');
await page.waitForTimeout(700);
const afterShift = await readX();
if (start !== null && afterArrow !== null) {
	const step = +(afterArrow - start).toFixed(3);
	const big = +(afterShift - afterArrow).toFixed(3);
	if (Math.abs(step - 0.1) > 0.02 || Math.abs(big - 1) > 0.05) {
		findings.push({ severity: 'major', what: 'Pijltjesstap klopt niet met het design system',
			evidence: `pijl: ${step} mm (verwacht 0,1) | shift+pijl: ${big} mm (verwacht 1)` });
	} else {
		console.log(`pijlstap ${step} mm, shift ${big} mm — klopt`);
	}
} else {
	findings.push({ severity: 'minor', what: 'Pijltjesstap niet te meten', evidence: 'geen element geselecteerd via het canvas' });
}
await page.evaluate(() => fetch('/api/design/clear', { method: 'POST' }));

report('Criticus 3 — interactiepurist', findings);
await b.close();
