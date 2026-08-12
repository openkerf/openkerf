/**
 * De harde eis: sta ik op het scherm dat ik denk te meten?
 *
 * Twee manieren waarop een meting er geslaagd uitziet terwijl ze niets zegt.
 * (1) Een verse installatie zonder machine opent op het welkomstscherm; wie dan
 * "het werkgebied" meet, meet een guard. (2) `frontend/build` is gedeeld tussen
 * de agents in deze wave, en twee builds door elkaar hebben al een index.html
 * opgeleverd die naar een chunk verwees die niet bestond — dan is de pagina
 * blanco en levert elke kleurmeting nette getallen over niets.
 *
 * Vandaar deze poort. Hij faalt luid: een meting op het verkeerde scherm mag er
 * niet uitzien als een meting.
 */
export class GeenScherm extends Error {}

/**
 * @param page       de playwright-pagina
 * @param verwacht   css-selector die alléén op het bedoelde scherm bestaat
 * @param waar       naam voor de foutmelding
 */
export async function eisScherm(page, verwacht, waar) {
	const bevinding = await page.evaluate((sel) => {
		const tekst = document.body.innerText.trim();
		return {
			gevonden: !!document.querySelector(sel),
			tekens: tekst.length,
			eersteRegel: tekst.split('\n')[0]?.slice(0, 60) ?? '',
			welkom: !!document.querySelector('.welkom') || /nog geen machine|welkom bij openkerf/i.test(tekst),
			kinderen: document.body.children.length
		};
	}, verwacht);

	if (bevinding.tekens < 20 || bevinding.kinderen === 0) {
		throw new GeenScherm(
			`${waar}: de pagina is leeg (${bevinding.tekens} tekens, ${bevinding.kinderen} kinderen in body). ` +
				'Waarschijnlijk een halve build of een server die nog niet klaar was — niet meten.'
		);
	}
	if (bevinding.welkom && !verwacht.includes('welkom')) {
		throw new GeenScherm(
			`${waar}: dit is het welkomstscherm, niet het bedoelde scherm. Richt eerst een machine in ` +
				'(POST /api/machines + /activate) voordat je meet.'
		);
	}
	if (!bevinding.gevonden) {
		throw new GeenScherm(
			`${waar}: "${verwacht}" staat niet op de pagina. Eerste regel: "${bevinding.eersteRegel}".`
		);
	}
	return bevinding;
}

/** Alle bouwstenen waar index.html naar wijst, bestaan ook echt. */
export async function eisHeleBuild(page, base) {
	const kapot = await page.evaluate(async () => {
		const uit = [];
		for (const el of document.querySelectorAll('script[src], link[href]')) {
			const url = el.src || el.href;
			if (!url.includes('/_app/')) continue;
			const r = await fetch(url, { method: 'HEAD' }).catch(() => null);
			if (!r || !r.ok) uit.push(`${url} → ${r ? r.status : 'geen antwoord'}`);
		}
		return uit;
	});
	if (kapot.length) {
		throw new GeenScherm(`De build is niet heel: ${kapot.join(' | ')}. Bouw opnieuw naar je eigen map.`);
	}
	return true;
}
