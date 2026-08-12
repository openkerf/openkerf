/**
 * Screenshotset voor het oppervlak "canvas en lagen" (gauntlet AAA, g-canvas).
 *
 * Staten: het bed met werk in drie lagen, een vorm die buiten het bed hangt,
 * het lagenpaneel, en het lagenpaneel met veel lagen (dichtheid, L5).
 * Drie breedtes, twee thema's.
 */
import { mkdirSync } from 'node:fs';
import { browser, open, reset, BASE } from './harness.mjs';

const RONDE = process.env.RONDE ?? 'r0';
const DIR = `../screenshots/aaa/g-canvas`;
mkdirSync(DIR, { recursive: true });

async function dismiss(page) {
	const later = await page.$('button:has-text("Later")');
	if (later) {
		await later.click();
		await page.waitForTimeout(300);
	}
}

/** Drie lagen met werk erin, plus één vorm die over de bedrand hangt. */
async function zaai(page, { veel = false } = {}) {
	await page.evaluate(async (veel) => {
		const post = (u, b) =>
			fetch(u, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(b)
			}).then((r) => r.json().catch(() => null));

		const lagen = [];
		for (const type of ['engrave', 'cut', 'raster']) lagen.push(await post('/api/design/operations', { type }));
		if (veel) {
			for (const type of ['cut', 'engrave', 'cut', 'raster', 'engrave', 'dots', 'cut'])
				lagen.push(await post('/api/design/operations', { type }));
		}

		const vormen = [];
		vormen.push(await post('/api/design/elements', { type: 'rect', x_mm: 20, y_mm: 20, width_mm: 120, height_mm: 80 }));
		vormen.push(await post('/api/design/elements', { type: 'circle', cx_mm: 260, cy_mm: 90, r_mm: 45 }));
		vormen.push(await post('/api/design/elements', { type: 'rect', x_mm: 60, y_mm: 150, width_mm: 200, height_mm: 90 }));
		vormen.push(await post('/api/design/elements', { type: 'text', x_mm: 40, y_mm: 270, text: 'OpenKerf', font_size_mm: 24 }));
		// Deze hangt over de rechter- en bovenrand van het bed heen (C2).
		vormen.push(await post('/api/design/elements', { type: 'circle', cx_mm: 470, cy_mm: 30, r_mm: 38 }));

		const paar = [
			[vormen[0], lagen[0]],
			[vormen[1], lagen[1]],
			[vormen[4], lagen[1]],
			[vormen[2], lagen[2]]
		];
		for (const [vorm, laag] of paar) {
			if (!vorm?.ids || !laag?.id) continue;
			await post('/api/design/assign', { ids: vorm.ids, operation_id: laag.id });
		}
		// De classificatie hangt alles ook in zijn eigen verzamellaag; die halen
		// we eraf zodat elke vorm precies één laagkleur draagt.
		const design = await fetch('/api/design').then((r) => r.json());
		const eigen = new Set(lagen.map((l) => l?.id));
		for (const op of design.operations) {
			if (eigen.has(op.id) || !op.element_ids.length) continue;
			await post('/api/design/unassign', { ids: op.element_ids, operation_id: op.id });
		}
	}, veel);
	await page.waitForTimeout(1200);
}

const STATEN = [
	['canvas', '/?tab=design', async (p) => { await zaai(p); }],
	[
		// Uitgezoomd: hier moet de liniaal buiten het bed doorlopen (C4) en het
		// oorsprongmerk los van de bedrand te zien zijn (C5).
		'uitgezoomd',
		'/?tab=design',
		async (p) => {
			await zaai(p);
			for (let i = 0; i < 4; i++) await p.click('.zoom button[title="Uitzoomen"]');
			await p.waitForTimeout(400);
		}
	],
	[
		// Ingezoomd op de oorsprong: het merk op ware grootte.
		'oorsprong',
		'/?tab=design',
		async (p) => {
			await zaai(p);
			for (let i = 0; i < 5; i++) await p.click('.zoom button[title="Inzoomen"]');
			await p.waitForTimeout(400);
		}
	],
	['lagen', '/?tab=layers', async (p) => { await zaai(p); }],
	['lagen-veel', '/?tab=layers', async (p) => { await zaai(p, { veel: true }); }],
	[
		'lagen-compact',
		'/?tab=layers',
		async (p) => {
			await zaai(p, { veel: true });
			await p.click('.dichtheid');
			await p.waitForTimeout(300);
		}
	],
	[
		// Middenin een sleepbeweging: de opgetilde rij en de lijn op de bestemming.
		'lagen-sleep',
		'/?tab=layers',
		async (p) => {
			await zaai(p, { veel: true });
			const greep = (await p.$$('.greep'))[8];
			if (!greep) return;
			const doos = await greep.boundingBox();
			const doel = (await p.$$('.layer'))[2];
			const doelDoos = await doel.boundingBox();
			await p.mouse.move(doos.x + doos.width / 2, doos.y + doos.height / 2);
			await p.mouse.down();
			await p.mouse.move(doos.x + doos.width / 2, doelDoos.y + 4, { steps: 12 });
			await p.waitForTimeout(300);
		}
	],
	[
		'lagen-open',
		'/?tab=layers',
		async (p) => {
			await zaai(p);
			const chip = await p.$('.layer .chip');
			if (chip) await chip.click();
			await p.waitForTimeout(400);
		}
	]
];

const b = await browser();
for (const [klasse, breedte] of [
	['desktop', 1440],
	['tablet', 1024],
	['telefoon', 390]
]) {
	for (const thema of ['licht', 'donker']) {
		for (const [naam, pad, stap] of STATEN) {
			// Op 390 px is er geen canvas en geen lagenpaneel: de telefoon toont
			// PhoneView (bewust, zie DESIGN-SYSTEM — ontwerpen doe je op de
			// desktop). Eén opname is daar het bewijs dat er niets gebroken is;
			// de andere staten bestaan er niet.
			if (breedte < 768 && naam !== 'canvas') continue;
			await reset();
			const page = await open(b, {
				width: breedte,
				theme: thema === 'donker' ? 'dark' : 'light',
				path: pad
			});
			await dismiss(page);
			await stap(page);
			await page.waitForTimeout(600);
			await page.screenshot({ path: `${DIR}/${RONDE}-${klasse}-${thema}-${naam}.png` });
			if (page.problems.length) console.log('  ! console:', page.problems.slice(0, 3));
			await page.context().close();
		}
	}
	console.log(klasse, 'klaar');
}
await b.close();
console.log('klaar ->', DIR, 'base', BASE);
