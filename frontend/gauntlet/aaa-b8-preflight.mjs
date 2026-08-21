/**
 * Kijkplicht voor besluit B8: de pre-flight toont het werkstuk.
 *
 * Vier staten die er in het echt toe doen — een gewoon ontwerp, iets dat over
 * de rand van het vel hangt, een leeg bed, en een ontwerp met veel vormen —
 * op drie breedtes in beide thema's.
 */
import { mkdirSync } from 'node:fs';
import { browser, open, BASE } from './harness.mjs';

const UIT = new URL('../../screenshots/aaa/b8/', import.meta.url).pathname;
mkdirSync(UIT, { recursive: true });

async function api(path, body, method) {
	const r = await fetch(BASE + path, {
		method: method ?? (body ? 'POST' : 'GET'),
		headers: { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	return r.status === 204 ? null : r.json().catch(() => null);
}

async function leeg() {
	await api('/api/design/autosave', undefined, 'DELETE').catch(() => {});
	await api('/api/design/clear', {});
}

async function laag(type, speed, power, ids) {
	const op = await api('/api/design/operations', { type, speed, power_percent: power });
	await api('/api/design/assign', { ids, operation_id: op.id });
	return op;
}

/** Alles uit elke andere laag halen, zodat de kleur klopt met de bedoeling. */
async function alleen(ids, houden) {
	const design = await api('/api/design');
	for (const op of design.operations) {
		if (op.id === houden) continue;
		const overlap = op.element_ids.filter((id) => ids.includes(id));
		if (overlap.length) await api('/api/design/unassign', { ids: overlap, operation_id: op.id });
	}
}

async function vorm(spec) {
	return (await api('/api/design/elements', spec)).ids;
}

const staten = {
	async normaal() {
		await leeg();
		const snij = [];
		for (let i = 0; i < 3; i++)
			snij.push(...(await vorm({ type: 'rect', x_mm: 20 + i * 70, y_mm: 25, width_mm: 55, height_mm: 55 })));
		const grav = [];
		for (let i = 0; i < 3; i++)
			grav.push(...(await vorm({ type: 'circle', cx_mm: 47 + i * 70, cy_mm: 130, r_mm: 22 })));
		const los = await vorm({ type: 'rect', x_mm: 240, y_mm: 110, width_mm: 40, height_mm: 40 });
		const a = await laag('cut', 12, 65, snij);
		await alleen(snij, a.id);
		const b = await laag('engrave', 90, 30, grav);
		await alleen(grav, b.id);
		await alleen(los, '-');
	},
	async buiten() {
		await staten.normaal();
		await vorm({ type: 'rect', x_mm: 275, y_mm: 150, width_mm: 70, height_mm: 45 });
	},
	async leeg() {
		await leeg();
	},
	/** De klassieke importmisser: een tekening die in de verkeerde eenheid
	 *  binnenkomt en honderden millimeters naast het vel landt. */
	async verweg() {
		await staten.normaal();
		await vorm({ type: 'circle', cx_mm: 900, cy_mm: 700, r_mm: 60 });
	},
	async druk() {
		await leeg();
		const ids = [];
		for (let i = 0; i < 60; i++) {
			ids.push(
				...(await vorm({
					type: 'circle',
					cx_mm: 12 + (i % 12) * 25,
					cy_mm: 15 + Math.floor(i / 12) * 38,
					r_mm: 10
				}))
			);
		}
		const op = await laag('cut', 8, 80, ids);
		await alleen(ids, op.id);
		await api(`/api/design/operations/${op.id}`, { passes: 60 }, 'PATCH');
	}
};

const breedtes = [
	['1440', 1440],
	['1024', 1024],
	['390', 390]
];

const b = await browser();
for (const [naam, maak] of Object.entries(staten)) {
	await maak();
	for (const [label, width] of breedtes) {
		for (const theme of ['light', 'dark']) {
			const page = await open(b, { width, theme, path: '/?tab=job' });
			// Het herstelvenster van een vorige sessie wegklikken, anders
			// fotografeer je een backdrop.
			await page.getByRole('button', { name: /Later/ }).click({ timeout: 1200 }).catch(() => {});
			// Op desktop staat de knop in het paneel ("Job starten"), op tablet in
			// de bovenbalk — daar heet hij onder 1200px alleen nog "Start", want
			// het woord "job" is dan weggeknipt. Die knop set zelf het tabblad om.
			const start = page
				.getByRole('button', { name: /^(Job starten|Start(\s*job)?)$/i })
				.filter({ hasNot: page.locator('[disabled]') });
			let geopend = false;
			if (await start.count()) {
				await start.first().click({ timeout: 3000 }).catch(() => {});
				geopend = await page
					.waitForSelector('.preflight', { timeout: 6000 })
					.then(() => true)
					.catch(() => false);
			}
			await page.waitForTimeout(900);
			await page.screenshot({ path: `${UIT}${naam}-${label}-${theme}.png` });
			// En dezelfde staat vergroot: dat is het venster waarin je een failure
			// écht nog kunt zien.
			if (geopend) {
				await page.locator('.vergroot').click({ timeout: 2000 }).catch(() => {});
				const open = await page
					.waitForSelector('.groot svg', { timeout: 3000 })
					.then(() => true)
					.catch(() => false);
				if (open) {
					await page.waitForTimeout(500);
					await page.screenshot({ path: `${UIT}${naam}-groot-${label}-${theme}.png` });
				}
			}
			console.log(
				`${naam.padEnd(8)} ${label.padEnd(5)} ${theme.padEnd(5)} preflight=${geopend}` +
					(page.problems.length ? `  FOUT: ${page.problems[0]}` : '')
			);
			await page.context().close();
		}
	}
}
await b.close();
