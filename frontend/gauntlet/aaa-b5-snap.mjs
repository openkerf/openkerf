/**
 * B5 — vastklikken op raster, vormen en randen.
 *
 * Meet wat je met een screenshot niet ziet: waar een vorm ná het loslaten écht
 * ligt. Twee rechthoeken worden bewust scheef neergezet; daarna sleept het
 * script de tweede naar de eerste toe en leest de bounds terug uit de API.
 * Exact naast elkaar betekent: verschil onder 0,01 mm.
 */
import { browser, open, BASE } from './harness.mjs';

const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/b5';
const ronde = process.argv[2] ?? 'r1';

const BED = { w: 310, h: 210 };

async function verseVormen() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' });
	// A ligt netjes op ronde maten, B ligt er scheef naast: 3,1 mm te ver naar
	// rechts en 2,7 mm te laag. Dat is precies het geval waarin je nu getallen
	// moet typen.
	for (const r of [
		{ x_mm: 60, y_mm: 60, width_mm: 40, height_mm: 30 },
		{ x_mm: 103.1, y_mm: 62.7, width_mm: 40, height_mm: 30 }
	]) {
		await fetch(`${BASE}/api/design/elements`, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ type: 'rect', ...r })
		});
	}
}

async function dozen() {
	const design = await (await fetch(`${BASE}/api/design`)).json();
	const per = design.units_per_mm;
	return design.elements.map((e) => ({
		id: e.id,
		x0: e.bounds[0] / per,
		y0: e.bounds[1] / per,
		x1: e.bounds[2] / per,
		y1: e.bounds[3] / per
	}));
}

/** Omrekenen van mm op het bed naar schermcoördinaten. */
async function meetlat(page) {
	const bed = await page.locator('.bed').boundingBox();
	const s = bed.width / BED.w;
	return { px: (x, y) => ({ x: bed.x + x * s, y: bed.y + y * s }), s, bed };
}

/**
 * Eén vorm oppakken en verslepen. `van` en `naar` staan in mm op het bed.
 * Geeft een screenshot terug van het moment vlak vóór het loslaten — daar
 * staan de hulplijnen op.
 */
async function sleep(page, van, naar, { alt = false, shot = null } = {}) {
	const lat = await meetlat(page);
	const a = lat.px(van.x, van.y);
	const b = lat.px(naar.x, naar.y);
	await page.mouse.move(a.x, a.y);
	await page.mouse.down();
	await page.mouse.move(a.x, a.y); // eerst selecteren via de klik
	await page.mouse.up();
	await page.waitForTimeout(250);

	if (alt) await page.keyboard.down('Alt');
	await page.mouse.move(a.x, a.y);
	await page.mouse.down();
	await page.mouse.move((a.x + b.x) / 2, (a.y + b.y) / 2, { steps: 6 });
	await page.mouse.move(b.x, b.y, { steps: 6 });
	await page.waitForTimeout(200);
	if (shot) await page.screenshot({ path: shot });
	const hulplijnen = await page.locator('.guide').count();
	await page.mouse.up();
	if (alt) await page.keyboard.up('Alt');
	await page.waitForTimeout(500);
	return hulplijnen;
}

async function pagina(b, width, theme) {
	const page = await open(b, { width, theme, path: '/?tab=design' });
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(400);
	if (!(await page.locator('.bed').count())) {
		console.log(`  ! geen bed op ${width}/${theme}, url ${page.url()}`);
	}
	return page;
}

const b = await browser();
const bevindingen = [];
const notify = (r) => {
	bevindingen.push(r);
	console.log(r);
};

// ── 1. De hoofdmeting: twee rechthoeken exact naast elkaar, per device/thema.
for (const [naam, width] of [['desktop', 1440], ['tablet', 1024], ['telefoon', 390]]) {
	for (const theme of ['light', 'dark']) {
		await verseVormen();
		const page = await pagina(b, width, theme);

		// Op de telefoon zit het canvas mogelijk achter een tab; dan slaan we over
		// en melden dat.
		if (!(await page.locator('.bed').count())) {
			// Op de telefoon bestaat het canvas niet; toch vastleggen wat er dán
			// staat, want de kijkplicht vraagt alle drie de breedtes.
			await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-0-geen-canvas.png` });
			notify(`${naam}/${theme}: geen canvas op dit device, niets te snappen`);
			await page.context().close();
			continue;
		}

		await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-1-scheef.png` });

		// B oppakken in zijn midden en naar rechts náást A schuiven: doel is de
		// rechterrand van A (x=100) plus de halve breedte, en de bovenrand van A.
		const doel = { x: 100 + 20, y: 60 + 15 };
		const lijnen = await sleep(
			page,
			{ x: 103.1 + 20, y: 62.7 + 15 },
			{ x: doel.x + 1.4, y: doel.y + 1.1 }, // bewust 1,4/1,1 mm ernaast
			{ shot: `${OUT}/${ronde}-${naam}-${theme}-2-hulplijnen.png` }
		);
		await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-3-vast.png` });

		const [A, B] = (await dozen()).sort((p, q) => p.x0 - q.x0);
		const gat = B.x0 - A.x1;
		const scheef = B.y0 - A.y0;
		notify(
			`${naam}/${theme}: hulplijnen ${lijnen}, gat ${gat.toFixed(3)} mm, hoogteverschil ${scheef.toFixed(3)} mm`
		);
		if (page.problems.length) bevindingen.push(`  console: ${page.problems.slice(0, 2)}`);
		await page.context().close();
	}
}

// ── 2. Alt schakelt uit.
{
	await verseVormen();
	const page = await pagina(b, 1440, 'light');
	const lijnen = await sleep(
		page,
		{ x: 103.1 + 20, y: 62.7 + 15 },
		{ x: 121.4, y: 76.1 },
		{ alt: true, shot: `${OUT}/${ronde}-desktop-light-4-alt.png` }
	);
	const [A, B] = (await dozen()).sort((p, q) => p.x0 - q.x0);
	notify(
		`alt ingedrukt: hulplijnen ${lijnen}, gat ${(B.x0 - A.x1).toFixed(3)} mm (hoort ≠ 0)`
	);
	await page.context().close();
}

// ── 3. Zoom: dezelfde sleep op 400% en op 25%.
for (const [label, tikken, mis] of [
	['400', -13, 2],
	['25', 13, 2]
]) {
	await verseVormen();
	const page = await pagina(b, 1440, 'light');
	// Met het wiel zoomen en niet met de knoppen: het wiel houdt het punt onder
	// de cursor op zijn plek, dus blijven de twee rechthoeken in beeld. Met de
	// knoppen schuift het werk op 400% zo van het scherm af.
	{
		const lat = await meetlat(page);
		const mid = lat.px(100, 75);
		await page.mouse.move(mid.x, mid.y);
		for (let i = 0; i < 13; i++) {
			await page.mouse.wheel(0, tikken < 0 ? -120 : 120);
			await page.waitForTimeout(50);
		}
	}
	await page.waitForTimeout(400);
	const zoom = await page.locator('.zoom .val').innerText();
	const mmPerPx = await page.evaluate(
		(w) => w / document.querySelector('.bed').getBoundingClientRect().width,
		BED.w
	);

	// Hoe ver mag je ernaast zitten en toch vastklikken? De trefafstand hoort in
	// schermpixels te staan, dus op 400% moet 0,5 mm ruim buiten bereik vallen
	// en op 25% er ruim binnen.
	const lijnen = await sleep(
		page,
		{ x: 103.1 + 20, y: 62.7 + 15 },
		{ x: 120 + mis, y: 75 + mis },
		{ shot: `${OUT}/${ronde}-desktop-light-5-zoom${label}.png` }
	);
	const [A, B] = (await dozen()).sort((p, q) => p.x0 - q.x0);
	notify(
		`zoom ${zoom} (1 px = ${mmPerPx.toFixed(3)} mm, trefafstand ${(9 * mmPerPx).toFixed(2)} mm): ` +
			`hulplijnen ${lijnen}, gat ${(B.x0 - A.x1).toFixed(3)} mm bij ${mis} mm ernaast`
	);
	await page.context().close();
}

// ── 4. De bedrand: een vorm naar de linkerbovenhoek slepen.
for (const theme of ['light', 'dark']) {
	await verseVormen();
	const page = await pagina(b, 1440, theme);
	const lijnen = await sleep(
		page,
		{ x: 103.1 + 20, y: 62.7 + 15 },
		{ x: 21.6, y: 16.4 }, // 1,6 / 1,4 mm buiten de hoek 20,15 (= rand 0,0)
		{ shot: `${OUT}/${ronde}-desktop-${theme}-6-bedrand.png` }
	);
	const doos = (await dozen()).sort((p, q) => p.x0 - q.x0)[0];
	notify(
		`bedrand ${theme}: hulplijnen ${lijnen}, linkerboven op ${doos.x0.toFixed(3)}, ${doos.y0.toFixed(3)} mm`
	);
	await page.context().close();
}

// ── 5. Schalen: een hoekgreep tegen de rand van de buurvorm aan.
{
	await verseVormen();
	const page = await pagina(b, 1440, 'light');
	const lat = await meetlat(page);
	// B selecteren, dan de linkerbovengreep naar de rechteronderhoek van A.
	const mid = lat.px(103.1 + 20, 62.7 + 15);
	await page.mouse.click(mid.x, mid.y);
	await page.waitForTimeout(300);
	const greep = lat.px(103.1, 62.7);
	const doelpx = lat.px(101.3, 91.4); // 1,3 / 1,4 mm naast de hoek 100, 90
	await page.mouse.move(greep.x, greep.y);
	await page.mouse.down();
	await page.mouse.move((greep.x + doelpx.x) / 2, (greep.y + doelpx.y) / 2, { steps: 6 });
	await page.mouse.move(doelpx.x, doelpx.y, { steps: 6 });
	await page.waitForTimeout(200);
	const lijnen = await page.locator('.guide').count();
	await page.screenshot({ path: `${OUT}/${ronde}-desktop-light-7-schalen.png` });
	await page.mouse.up();
	await page.waitForTimeout(600);
	const [A, B] = (await dozen()).sort((p, q) => p.x0 - q.x0);
	notify(
		`schalen: hulplijnen ${lijnen}, hoek B op ${B.x0.toFixed(3)}, ${B.y0.toFixed(3)} mm ` +
			`(hoek A: ${A.x1.toFixed(3)}, ${A.y1.toFixed(3)})`
	);
	await page.context().close();
}

// ── 6. De schakelaar naast de zoomregeling, en Alt die hem omkeert.
{
	await verseVormen();
	const page = await pagina(b, 1440, 'light');
	const knop = page.locator('.zoom .snap');
	await knop.click(); // uit
	await page.waitForTimeout(200);
	await page.screenshot({ path: `${OUT}/${ronde}-desktop-light-8-schakelaar-uit.png` });
	let lijnen = await sleep(page, { x: 103.1 + 20, y: 62.7 + 15 }, { x: 121.4, y: 76.1 });
	let s = (await dozen()).sort((p, q) => p.x0 - q.x0);
	notify(
		`schakelaar uit: hulplijnen ${lijnen}, gat ${(s[1].x0 - s[0].x1).toFixed(3)} mm (hoort ≠ 0), ` +
			`aria-pressed=${await knop.getAttribute('aria-pressed')}`
	);

	// Met de schakelaar uit hoort Alt hem juist even aan te zetten.
	await verseVormen();
	await page.reload();
	await page.waitForTimeout(1200);
	const later = page.getByRole('button', { name: /later/i });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(400);
	lijnen = await sleep(
		page,
		{ x: 103.1 + 20, y: 62.7 + 15 },
		{ x: 121.4, y: 76.1 },
		{ alt: true, shot: `${OUT}/${ronde}-desktop-light-9-uit-plus-alt.png` }
	);
	s = (await dozen()).sort((p, q) => p.x0 - q.x0);
	notify(
		`schakelaar uit + alt: hulplijnen ${lijnen}, gat ${(s[1].x0 - s[0].x1).toFixed(3)} mm (hoort 0), ` +
			`stand onthouden = ${(await knop.getAttribute('aria-pressed')) === 'false'}`
	);
	await knop.click(); // netjes weer aan voor de volgende meting
	await page.context().close();
}

await b.close();
console.log('\n### B5 — vastklikken');
for (const r of bevindingen) console.log(r);
