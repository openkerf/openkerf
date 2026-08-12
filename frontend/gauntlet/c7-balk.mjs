/**
 * Criticus 7 — de balkwacht.
 *
 * De bovenbalk is twee keer gebroken door twee verschillende agents die er een
 * chip bij zetten: eerst op 1440, daarna op 768. Beide keren viel er een knop
 * buiten beeld en waarschuwde niets. De reden dat alle andere metingen het
 * misten: de balk heeft `overflow-x: auto`, dus hij schuift *intern* en het
 * document loopt nooit over. Wie op `document.scrollWidth` meet, ziet niets.
 *
 * En dit is niet zomaar een balk. Het is het enige oppervlak waar de noodrem
 * altijd hoort te staan, en tegelijk de plek waar iedere nieuwe functie zijn
 * knop bij zet. Daarom drie eisen, waarvan de laatste de zwaarste is:
 *
 *   1. de balk verbergt niets achter interne scroll;
 *   2. de laatste zichtbare knop eindigt binnen het venster;
 *   3. Stop staat in beeld en is volledig aanklikbaar — op elke breedte.
 *
 * Voorstel voor deze meting kwam van de tablet-agent, die zijn eigen reparatie
 * "verzacht het maar dekt het niet" noemde. Hij had gelijk.
 */
import { browser, open, report } from './harness.mjs';

const BREEDTES = [768, 850, 950, 1024, 1199, 1440, 1600];
/**
 * Met `--zelftest` hangt er één brede knop bij in de balk. Die moet gevonden
 * worden; gebeurt dat niet, dan is deze meter stuk en zegt zijn groene uitslag
 * niets. Dat is de les uit ronde 1, nu in de meter zelf gebouwd in plaats van
 * in een aparte test die je kunt vergeten te draaien.
 */
const ZELFTEST = process.argv.includes('--zelftest');
const findings = [];
const b = await browser();

for (const theme of ['light', 'dark']) {
	for (const width of BREEDTES) {
		const page = await open(b, { width, theme });
		await page.waitForTimeout(400);
		const later = await page.$('button:has-text("Later")');
		if (later) {
			await later.click();
			await page.waitForTimeout(250);
		}

		if (ZELFTEST) {
			await page.evaluate(() => {
				const balk = document.querySelector('header');
				const knop = document.createElement('button');
				knop.className = 'btn';
				knop.textContent = 'Een nieuwe functie met een lange naam';
				knop.style.flex = '0 0 auto';
				knop.style.whiteSpace = 'nowrap';
				balk.appendChild(knop);
			});
			await page.waitForTimeout(200);
		}

		const meting = await page.evaluate((vensterBreedte) => {
			const balk = document.querySelector('header');
			if (!balk) return null;
			const zichtbaar = [...balk.querySelectorAll('button, a.btn, label.btn')].filter(
				(n) => n.offsetParent !== null && n.getBoundingClientRect().width > 0
			);
			const laatste = zichtbaar[zichtbaar.length - 1];
			const stop = zichtbaar.find((n) => /^stop/i.test((n.textContent || '').trim()));
			const doos = (n) => {
				const r = n.getBoundingClientRect();
				return { links: Math.round(r.left), rechts: Math.round(r.right) };
			};
			return {
				verborgen: balk.scrollWidth - balk.clientWidth,
				venster: vensterBreedte,
				laatste: laatste
					? { naam: (laatste.textContent || '').trim().slice(0, 16) || '(icoon)', ...doos(laatste) }
					: null,
				stop: stop ? doos(stop) : null,
				aantal: zichtbaar.length
			};
		}, width);

		if (!meting) {
			findings.push({ severity: 'major', what: 'Geen bovenbalk gevonden', evidence: `${width}px/${theme}` });
			await page.context().close();
			continue;
		}

		console.log(
			`${width}/${theme}: ${meting.aantal} knoppen, verborgen ${meting.verborgen}px, ` +
				`laatste "${meting.laatste?.naam}" eindigt op ${meting.laatste?.rechts}`
		);

		if (meting.verborgen > 0) {
			findings.push({
				severity: 'major',
				what: 'De bovenbalk verbergt knoppen achter interne scroll',
				evidence: `${meting.verborgen}px buiten beeld op ${width}px/${theme} — het document loopt niet over, dus geen andere meting ziet dit`
			});
		}
		if (meting.laatste && meting.laatste.rechts > width + 1) {
			findings.push({
				severity: 'major',
				what: 'De laatste knop in de bovenbalk valt buiten het venster',
				evidence: `"${meting.laatste.naam}" eindigt op ${meting.laatste.rechts} bij een venster van ${width} (${theme})`
			});
		}
		// De noodrem is geen knop als de rest: hij moet er altijd helemaal staan.
		if (!meting.stop) {
			findings.push({
				severity: 'blocker',
				what: 'Geen stopknop in de bovenbalk',
				evidence: `${width}px/${theme}`
			});
		} else if (meting.stop.links < 0 || meting.stop.rechts > width + 1) {
			findings.push({
				severity: 'blocker',
				what: 'De stopknop valt gedeeltelijk buiten het venster',
				evidence: `Stop loopt van ${meting.stop.links} tot ${meting.stop.rechts} bij een venster van ${width} (${theme}) — de noodrem moet op elke breedte volledig aanklikbaar zijn`
			});
		}
		await page.context().close();
	}
}

if (ZELFTEST) {
	const gevonden = findings.some((f) => f.what.includes('interne scroll'));
	console.log(
		gevonden
			? 'zelftest ok: de afgedwongen overloop is gevonden'
			: 'ZELFTEST MISLUKT: een brede knop erbij bleef onopgemerkt — deze meter is stuk'
	);
	process.exitCode = gevonden ? 0 : 1;
} else {
	report('Criticus 7 — balkwacht', findings);
}
await b.close();
