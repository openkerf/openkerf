/**
 * Metingen voor het oppervlak "canvas en lagen" (g-canvas).
 *
 * Screenshots zijn het archief, dit is het argument: hoeveel gloedjes er
 * liggen, of de meldingen ergens achter vallen, hoe hoog een laagrij is en of
 * de liniaal buiten het bed doorloopt.
 */
import { browser, open, reset, BASE } from './harness.mjs';

async function dismiss(page) {
	const later = await page.$('button:has-text("Later")');
	if (later) {
		await later.click();
		await page.waitForTimeout(300);
	}
}

async function zaai(page, { veel = false } = {}) {
	await page.evaluate(async (veel) => {
		const post = (u, b) =>
			fetch(u, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(b)
			}).then((r) => r.json().catch(() => null));
		const lagen = [];
		for (const type of ['engrave', 'cut', 'raster'])
			lagen.push(await post('/api/design/operations', { type }));
		if (veel)
			for (const type of ['cut', 'engrave', 'cut', 'raster', 'engrave', 'dots', 'cut'])
				lagen.push(await post('/api/design/operations', { type }));
		const v = [];
		v.push(await post('/api/design/elements', { type: 'rect', x_mm: 20, y_mm: 20, width_mm: 120, height_mm: 80 }));
		v.push(await post('/api/design/elements', { type: 'circle', cx_mm: 260, cy_mm: 90, r_mm: 45 }));
		v.push(await post('/api/design/elements', { type: 'rect', x_mm: 60, y_mm: 150, width_mm: 200, height_mm: 90 }));
		v.push(await post('/api/design/elements', { type: 'text', x_mm: 40, y_mm: 270, text: 'OpenKerf', font_size_mm: 24 }));
		v.push(await post('/api/design/elements', { type: 'circle', cx_mm: 470, cy_mm: 30, r_mm: 38 }));
		for (const [vorm, laag] of [
			[v[0], lagen[0]],
			[v[1], lagen[1]],
			[v[4], lagen[1]],
			[v[2], lagen[2]]
		]) {
			if (!vorm?.ids || !laag?.id) continue;
			await post('/api/design/assign', { ids: vorm.ids, operation_id: laag.id });
		}
		const design = await fetch('/api/design').then((r) => r.json());
		const eigen = new Set(lagen.map((l) => l?.id));
		for (const op of design.operations) {
			if (eigen.has(op.id) || !op.element_ids.length) continue;
			await post('/api/design/unassign', { ids: op.element_ids, operation_id: op.id });
		}
	}, veel);
	await page.waitForTimeout(1200);
}

/** Ligt `a` (deels) onder `b`? Dat is wat "achter de camerapil" betekent. */
function overlapt(a, b) {
	if (!a || !b) return false;
	return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

const meet = async (page) =>
	page.evaluate(() => {
		const doos = (sel) => {
			const el = document.querySelector(sel);
			if (!el) return null;
			const r = el.getBoundingClientRect();
			return { x: +r.x.toFixed(1), y: +r.y.toFixed(1), width: +r.width.toFixed(1), height: +r.height.toFixed(1) };
		};
		const teksten = (sel) => [...document.querySelectorAll(sel)].map((n) => (n.textContent ?? '').trim());
		const rulerX = [...document.querySelectorAll('.ruler-x text')].map((n) => n.textContent);
		const rulerY = [...document.querySelectorAll('.ruler-y text')].map((n) => n.textContent);
		return {
			gloed: document.querySelectorAll('.buiten-gloed').length,
			gloedVel: document.querySelectorAll('.buiten-gloed.velrand').length,
			meldingen: teksten('.buiten-strook .regel'),
			meldingDoos: doos('.buiten-strook'),
			cameraDoos: doos('.camstrip'),
			zoomDoos: doos('.zoom'),
			nummers: teksten('.laagnummer'),
			oorsprong: !!document.querySelector('.oorsprong'),
			rulerX,
			rulerY,
			negatiefX: rulerX.filter((t) => t && t.startsWith('-')).length,
			negatiefY: rulerY.filter((t) => t && t.startsWith('-')).length,
			rijen: [...document.querySelectorAll('.layer')].map((n) => +n.getBoundingClientRect().height.toFixed(1)),
			compactAan: !!document.querySelector('.layer.compact'),
			dichtheidKnop: !!document.querySelector('.dichtheid'),
			sorteerKnop: [...document.querySelectorAll('.lijst-balk .rot')].map((n) => ({
				tekst: (n.textContent ?? '').trim(),
				uit: n.disabled
			})),
			grepen: document.querySelectorAll('.greep').length,
			lijstHoogte: (() => {
				const el = document.querySelector('.layer');
				if (!el) return null;
				const paneel = el.closest('.panel, .side, aside, .paneel');
				return paneel ? +paneel.getBoundingClientRect().height.toFixed(1) : null;
			})()
		};
	});

const b = await browser();
for (const breedte of [1440, 1024]) {
	for (const thema of ['light', 'dark']) {
		await reset();
		let page = await open(b, { width: breedte, theme: thema, path: '/?tab=design' });
		await dismiss(page);
		await zaai(page);
		let m = await meet(page);
		console.log(`\n== ${breedte} ${thema} canvas`);
		console.log('  gloed:', m.gloed, 'waarvan vel:', m.gloedVel);
		console.log('  meldingen:', JSON.stringify(m.meldingen));
		console.log('  melding achter zoombalk?', overlapt(m.meldingDoos, m.zoomDoos));
		console.log('  melding achter camerapil?', overlapt(m.meldingDoos, m.cameraDoos), m.cameraDoos);
		console.log('  laagnummers:', JSON.stringify(m.nummers), 'oorsprong:', m.oorsprong);
		console.log('  liniaal x:', m.rulerX.join(' '), '| negatief:', m.negatiefX);
		console.log('  liniaal y:', m.rulerY.join(' '), '| negatief:', m.negatiefY);
		await page.context().close();

		await reset();
		page = await open(b, { width: breedte, theme: thema, path: '/?tab=layers' });
		await dismiss(page);
		await zaai(page, { veel: true });
		m = await meet(page);
		console.log(`== ${breedte} ${thema} lagen (10 lagen)`);
		console.log('  ruim  rijhoogtes:', m.rijen.join(' '), '| paneelhoogte:', m.lijstHoogte);
		console.log('  grepen:', m.grepen, '| sorteerknop:', JSON.stringify(m.sorteerKnop));
		await page.click('.dichtheid');
		await page.waitForTimeout(300);
		const c = await meet(page);
		console.log('  compact rijhoogtes:', c.rijen.join(' '), '| compact aan:', c.compactAan);
		console.log('  in beeld ruim:', Math.floor((m.lijstHoogte ?? 0) / (m.rijen[0] || 1)),
			'compact:', Math.floor((c.lijstHoogte ?? 0) / (c.rijen[0] || 1)));
		await page.context().close();
	}
}
await b.close();
console.log('\nbase', BASE);
