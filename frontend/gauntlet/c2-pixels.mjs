/**
 * Criticus 2 — de pixelrechter.
 *
 * Meet in plaats van te kijken: uitlijning, spacing tussen gelijksoortige
 * elementen, overloop, en of paren die identiek horen te zijn dat ook zijn.
 * Screenshots gaan naar gauntlet/shots als archief.
 */
import { browser, open, report, reset, WIDTHS } from './harness.mjs';

await reset();
const b = await browser();
const findings = [];
const seen = new Set();

function add(severity, what, evidence) {
	const key = `${severity}|${what}`;
	if (seen.has(key)) return;
	seen.add(key);
	findings.push({ severity, what, evidence });
}

for (const theme of ['light', 'dark']) {
	for (const [name, width] of Object.entries(WIDTHS)) {
		const page = await open(b, { width, theme });
		const failed = [];
		page.on('response', (r) => {
			if (r.status() >= 400) failed.push(`${r.status()} ${r.url().slice(-70)}`);
		});
		await page.waitForTimeout(600);
		await page.screenshot({ path: `gauntlet/shots/app-${name}-${theme}.png`, fullPage: false });

		// --- horizontale overloop
		const overflow = await page.evaluate(() => {
			const d = document.documentElement;
			return { scroll: d.scrollWidth, client: d.clientWidth };
		});
		if (overflow.scroll > overflow.client + 1) {
			add('major', `Pagina scrollt horizontaal op ${width}px`,
				`scrollWidth ${overflow.scroll} > clientWidth ${overflow.client} (${name}/${theme})`);
		}

		// --- tekst die buiten zijn doos valt
		const clipped = await page.$$eval('*', (nodes) =>
			nodes
				.filter((n) => n.children.length === 0 && (n.textContent ?? '').trim())
				.filter((n) => {
					// SVG-tekst heeft geen CSS-doos: clientWidth is er 2 waar de
					// letter 8 pixels breed is, dus deze meting slaat er altijd op
					// aan terwijl er niets afgesneden wordt. Gecontroleerd door te
					// kijken (liniaal-"0" op 1024px staat er heel). De leesbaarheid
					// van canvastekst wordt hieronder apart in schermpixels gemeten.
					if (n.namespaceURI && n.namespaceURI.includes('svg')) return false;
					const s = getComputedStyle(n);
					if (s.overflow === 'hidden' || s.textOverflow === 'ellipsis') return false;
					return n.scrollWidth > n.clientWidth + 1 && n.clientWidth > 0;
				})
				.map((n) => ({
					text: n.textContent.trim().slice(0, 30),
					cls: String(n.className ?? '').slice(0, 26),
					over: n.scrollWidth - n.clientWidth
				}))
				.slice(0, 6)
		);
		if (clipped.length) {
			add('major', `Tekst loopt uit zijn doos op ${width}px`,
				clipped.map((c) => `"${c.text}" (.${c.cls}) +${c.over}px`).join(' | ') + ` [${name}/${theme}]`);
		}

		// --- gelijksoortige elementen die niet gelijk zijn
		for (const [label, selector] of [['knoppen in het rechterpaneel', '.panel-scroll button.rot'],
										 ['tabbladen', '.tabs .tab']]) {
			const boxes = await page.$$eval(selector, (nodes) =>
				nodes.map((n) => {
					const r = n.getBoundingClientRect();
					const s = getComputedStyle(n);
					return { h: +r.height.toFixed(1), pad: s.padding, radius: s.borderRadius, size: s.fontSize };
				})
			);
			if (boxes.length > 1) {
				const heights = [...new Set(boxes.map((x) => x.h))];
				if (heights.length > 1) {
					add('minor', `${label}: verschillende hoogtes`,
						`${heights.join(' / ')} px op ${width} (${theme})`);
				}
				const radii = [...new Set(boxes.map((x) => x.radius))];
				if (radii.length > 1) {
					add('minor', `${label}: verschillende radius`, radii.join(' / ') + ` op ${width}`);
				}
			}
		}

		// --- contrast van elke tekst tegen zijn achtergrond
		const low = await page.$$eval('*', (nodes) => {
			function parse(c) {
				const m = c.match(/[\d.]+/g);
				if (!m) return null;
				const [r, g, b, a] = m.map(Number);
				return { rgb: [r, g, b], a: a === undefined ? 1 : a };
			}
			function over(top, bottom) {
				// Een halfdoorzichtige achtergrond mengt met wat eronder ligt.
				// Zonder dit meet je 10% accent als volle accentkleur, en dan
				// "vind" je contrastfouten die er niet zijn.
				return top.rgb.map((c, i) => c * top.a + bottom[i] * (1 - top.a));
			}
			function lum([r, g, b]) {
				const f = (v) => {
					v /= 255;
					return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
				};
				return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
			}
			function bgOf(node) {
				// Van boven naar beneden stapelen tot er een dekkende laag is.
				const stack = [];
				let n = node;
				while (n) {
					const layer = parse(getComputedStyle(n).backgroundColor);
					if (layer && layer.a > 0) {
						stack.push(layer);
						if (layer.a >= 0.999) break;
					}
					n = n.parentElement;
				}
				let base = [255, 255, 255];
				for (const layer of stack.reverse()) base = over(layer, base);
				return base;
			}
			const bad = [];
			for (const n of nodes) {
				if (n.children.length || !(n.textContent ?? '').trim()) continue;
				const r = n.getBoundingClientRect();
				if (!r.width || !r.height) continue;
				const s = getComputedStyle(n);
				const fgRaw = parse(s.color);
				if (!fgRaw) continue;
				const bg = bgOf(n);
				const fg = over(fgRaw, bg);
				const l1 = lum(fg), l2 = lum(bg);
				const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
				const px = parseFloat(s.fontSize);
				const large = px >= 18.66 || (px >= 14 && +s.fontWeight >= 700);
				const need = large ? 3 : 4.5;
				if (ratio < need) {
					bad.push({
						text: n.textContent.trim().slice(0, 24),
						cls: String(n.className ?? '').slice(0, 22),
						ratio: +ratio.toFixed(2),
						need,
						size: s.fontSize
					});
				}
			}
			return bad.slice(0, 10);
		});
		if (low.length) {
			add(theme === 'dark' ? 'major' : 'major', `Te laag tekstcontrast (${theme})`,
				low.map((l) => `"${l.text}" ${l.ratio}:1 < ${l.need} (${l.size}, .${l.cls})`).join(' | '));
		}

		if (page.problems.length) {
			// Het verzoek erbij: "404" zonder adres is geen bevinding maar een raadsel.
			add('major', 'Fouten in de browserconsole',
				[...new Set(page.problems)].slice(0, 4).join(' | ') +
					(failed.length ? ` — mislukte verzoeken: ${[...new Set(failed)].join(', ')}` : '') +
					` [${name}/${theme}]`);
		}
		await page.context().close();
	}
}

// --- tekst in de bed-SVG: blijft die leesbaar bij elke zoom?
// Dit werd gemist doordat de tokencontrole alleen naar de wáárde keek: 11px in
// een SVG die in millimeters rekent, is 11 millimeter. Op het scherm meten is
// de enige controle die dat vangt.
{
	const page = await open(b, { width: 1440 });
	await page.evaluate(() =>
		fetch('/api/design/elements', {
			method: 'POST', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ type: 'rect', x_mm: 20, y_mm: 20, width_mm: 20, height_mm: 20 })
		})
	);
	await page.reload({ waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar');
	await page.waitForTimeout(900);
	const spot = await page.evaluate(() => {
		const el = document.querySelector('svg path.hit');
		if (!el) return null;
		const r = el.getBoundingClientRect();
		return { x: r.x + 1, y: r.y + r.height / 2 };
	});
	if (spot) {
		await page.mouse.click(spot.x, spot.y);
		await page.waitForTimeout(400);
		const surface = await page.$('svg[role="img"]');
		const box = await surface.boundingBox();
		await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
		const gemeten = [];
		for (const zoom of [0, 6, 12]) {
			for (let i = 0; i < (zoom ? 6 : 0); i++) {
				await page.mouse.wheel(0, -120);
				await page.waitForTimeout(25);
			}
			const hoogte = await page.evaluate(() => {
				const t = [...document.querySelectorAll('svg text')]
					.filter((n) => /mm/.test(n.textContent ?? ''))
					.map((n) => n.getBoundingClientRect().height);
				return t.length ? Math.round(Math.max(...t)) : null;
			});
			if (hoogte) gemeten.push(`${zoom ? `${zoom} stappen` : 'geen zoom'}: ${hoogte}px`);
		}
		const tegroot = gemeten.filter((g) => Number(g.match(/(\d+)px/)[1]) > 24);
		const teklein = gemeten.filter((g) => Number(g.match(/(\d+)px/)[1]) < 8);
		if (tegroot.length || teklein.length) {
			add('major', 'Tekst op het canvas schaalt mee met de zoom',
				`gemeten hoogtes: ${gemeten.join(' | ')} (moet tussen 8 en 24 px blijven)`);
		} else {
			console.log('canvaslabels blijven leesbaar:', gemeten.join(' | '));
		}
	}
	await page.evaluate(() => fetch('/api/design/clear', { method: 'POST' }));
	await page.context().close();
}

// --- SVG-tekst in schermpixels
// Elke uitzondering op de typeschaal (@svg-space) hoort hier langs te komen:
// een viewBox in millimeters of eigen eenheden zegt niets over wat je ziet.
{
	const page = await open(b, { width: 1440 });
	await page.waitForTimeout(600);
	const later = await page.$('button:has-text("Later")');
	if (later) { await later.click(); await page.waitForTimeout(300); }
	await page.click('button[title^="Generatoren"]').catch(() => {});
	await page.waitForTimeout(400);
	await page.click('button:has-text("Doos")').catch(() => {});
	await page.waitForTimeout(500);
	// Niet de omhullende doos meten: die is voor cijfers ongeveer 0,6 em, dus
	// een correcte 11px-liniaal komt eruit als 6,6 en dan "vindt" de meter een
	// fout die er niet is. Wat telt is de gerenderde lettergrootte: de
	// opgegeven font-size maal de schaal waarmee de SVG op het scherm staat.
	const klein = await page.$$eval('svg text', (ns) =>
		ns
			.filter((n) => (n.textContent ?? '').trim() && n.getBoundingClientRect().height > 0)
			.map((n) => {
				const ctm = n.getScreenCTM();
				const schaal = ctm ? Math.sqrt(Math.abs(ctm.a * ctm.d - ctm.b * ctm.c)) : 1;
				const opgegeven = parseFloat(getComputedStyle(n).fontSize) || 0;
				return {
					t: n.textContent.trim().slice(0, 14),
					px: +(opgegeven * schaal).toFixed(1)
				};
			})
			.filter((x) => x.px > 0 && x.px < 10.5)
	);
	console.log('SVG-tekst onder 10,5 schermpixels:', klein.length ? klein : 'geen');
	if (klein.length) {
		findings.push({ severity: 'major', what: 'SVG-tekst kleiner dan de ondergrens van de schaal',
			evidence: klein.map((x) => `"${x.t}" ${x.px}px`).join(' | ') });
	}
	await page.context().close();
}

report('Criticus 2 — pixelrechter', findings);
await b.close();
