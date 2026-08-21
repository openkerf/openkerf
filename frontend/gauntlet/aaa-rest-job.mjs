/**
 * Pre-flight en jobcontrole: de rondes van agent rest-job.
 *
 * Opent het Job-tabblad, klapt de pre-flight open en fotografeert hem op alle
 * drie de breedtes in beide thema's. Meet daarnaast waar de notifications staan en
 * welke kleur hun linkerbalk heeft — dat is het verschil tussen "buiten het
 * bed" (rood) en "buiten het vel" (oranje) dat je op een screenshot van 390px
 * anders op je blauwe oog moet geloven.
 */
import { browser, open, BASE, WIDTHS } from './harness.mjs';

const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/rest-job';
const ronde = process.argv[2] ?? 'voor';

/**
 * `zonderRaster` doet alsof deze engine geen rasteraar heeft.
 *
 * Sinds onze eigen rasteraar geregistreerd wordt (`openkerf_api/rasterizer.py`)
 * brandt een rasterlaag gewoon, en dan is de blokkade in de pre-flight terecht
 * onzichtbaar. Om hem tóch te kunnen fotograferen wordt hier alleen het
 * antwoord van `/api/job/layers` omgezet naar wat een engine zónder rasteraar
 * meldt — dezelfde vorm die `test_a_raster_layer_promises_no_time_on_an_engine
 * _that_cannot_burn_it` vastlegt. De component en de markup zijn echt.
 */
const zonderRaster = process.argv.includes('--zonder-raster');

const b = await browser();
const metingen = [];

for (const [naam, width] of Object.entries(WIDTHS)) {
	for (const theme of ['light', 'dark']) {
		const page = await open(b, { width, theme, path: '/?tab=job' });
		if (zonderRaster) {
			await page.route('**/api/job/layers', async (route) => {
				const antwoord = await route.fetch();
				const data = await antwoord.json();
				data.engine = { raster: false };
				for (const laag of data.layers ?? []) {
					if (laag.type === 'op raster') laag.burns = false;
				}
				await route.fulfill({ response: antwoord, json: data });
			});
		}
		// Het herstelvenster van een vorige sessie legt een backdrop over alles.
		const later = page.getByRole('button', { name: /later/i });
		if (await later.count()) await later.first().click().catch(() => {});
		await page.waitForTimeout(400);

		// Op tablet en telefoon kan het rechterpaneel ingeklapt zijn.
		const paneel = page.locator('.panel-toggle, button[aria-label*="paneel"]');
		if (await paneel.count()) {
			const open2 = await page.locator('.preflight, .section').count();
			if (!open2) await paneel.first().click().catch(() => {});
		}
		await page.waitForTimeout(300);

		// De pre-flight zit achter "Start job" (bovenbalk) of "Job starten" (in
		// het paneel). Op de telefoon bestaat hij niet: die kan niets starten.
		// De knop in het paneel bestaat op tablet wel maar is verborgen (gat J9:
		// de bediening woont daar in de bovenbalk), dus die van de balk eerst.
		for (const kiezer of ['button[title="De pre-flight openen"]', 'button.dubbel.primary']) {
			const knop = page.locator(kiezer);
			if (await knop.count()) {
				await knop.first().click({ timeout: 4000 }).catch(() => {});
				await page.waitForSelector('.preflight', { timeout: 4000 }).catch(() => {});
			}
			if (await page.locator('.preflight').count()) break;
		}
		// De schatting komt na het overzicht; wachten tot de klok een tijd toont.
		await page.waitForTimeout(2500);

		const pf = page.locator('.preflight');
		if (await pf.count()) {
			await pf.first().scrollIntoViewIfNeeded().catch(() => {});
			await page.waitForTimeout(200);
			await pf.first().screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-preflight.png` }).catch(() => {});
		}
		await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-vol.png`, fullPage: false });

		const meting = await page.evaluate(() => {
			const lees = (sel) =>
				[...document.querySelectorAll(sel)].map((n) => {
					const s = getComputedStyle(n);
					const r = n.getBoundingClientRect();
					return {
						sel,
						tekst: (n.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 110),
						y: +r.y.toFixed(1),
						balk: s.borderLeftColor,
						balkbreedte: s.borderLeftWidth,
						bg: s.backgroundColor,
						kleur: s.color
					};
				});
			const chips = [...document.querySelectorAll('.pf-layers .chip')].map((n) => {
				const r = n.getBoundingClientRect();
				return {
					tekst: n.textContent.trim(),
					w: +r.width.toFixed(1),
					h: +r.height.toFixed(1),
					ariaHidden: n.getAttribute('aria-hidden'),
					label: n.getAttribute('aria-label'),
					titel: n.getAttribute('title'),
					bg: getComputedStyle(n).backgroundColor,
					kleur: getComputedStyle(n).color
				};
			});
			return {
				notifications: [
					...lees('.pf-buitenbed'),
					...lees('.melding.buiten'),
					...lees('.melding.buitenbed'),
					...lees('.pf-geenraster'),
					...lees('.pf-warn'),
					...lees('.pf-mismatch li')
				].sort((a, b) => a.y - b.y),
				chips,
				tijd: document.querySelector('.pf-time .v')?.textContent.trim() ?? null,
				rijen: [...document.querySelectorAll('.pf-layers tbody tr')].map((r) =>
					[...r.children].map((c) => c.textContent.trim()).join(' | ')
				)
			};
		});
		metingen.push({ naam, width, theme, ...meting, fouten: page.problems });
		await page.context().close();
	}
}
await b.close();
console.log(JSON.stringify(metingen, null, 1));
