/**
 * Punt 3: in de lettertypekiezer staat de naam in het interfacelettertype en
 * het voorbeeld in de letter zelf.
 *
 * Stonden ze allebei in de letter, dan is een font zonder leesbaar latijns
 * alfabet (Aurebesh, Apple Braille, een symbolenset) niet meer te vinden: je
 * leest de naam niet en het voorbeeld ook niet.
 *
 * Meet de bérékende font-family van beide spans, niet de opmaakregel — dat is
 * het enige dat zegt wat er werkelijk op het scherm staat.
 *
 * Gebruik: node gauntlet/fc-fontkeuze.mjs [voor|na]
 */
import { mkdirSync } from 'node:fs';
import { browser, open, BASE } from './harness.mjs';

const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/fc-fontkeuze';
mkdirSync(OUT, { recursive: true });
const ronde = process.argv[2] ?? 'na';

const b = await browser();
const page = await open(b, { width: 1440 });

// Laat een vorige zitting werk achter, dan ligt het herstelvenster erover en
// vangt de backdrop elke klik op. Deze meting liep daardoor alleen op een
// schone lei; nu ook erna.
const later = await page.$('button:has-text("Later")');
if (later) {
	await later.click();
	await page.waitForTimeout(400);
}

// Het tekstgereedschap opent het tekstvenster met de kiezer erin.
await page.locator('button[title^="Tekst"], .tool[title^="Tekst"]').first().click();
await page.waitForTimeout(300);
await page.locator('.canvas').first().click({ position: { x: 220, y: 180 }, force: true });
await page.waitForTimeout(700);

await page.locator('input[placeholder="Zoek een lettertype…"]').fill('aurebesh');
await page.waitForTimeout(900);

// Niet de eerste rij: dat is "Standaard", en die heeft geen voorbeeld.
const rij = page.locator('.fonts .font').filter({ hasText: 'Aurebesh' }).first();
const meting = await rij.evaluate((el) => {
	const naam = el.querySelector('.naam');
	const proef = el.querySelector('.proef');
	return {
		naam: naam?.textContent?.trim(),
		naamFont: naam ? getComputedStyle(naam).fontFamily : null,
		proefTekst: proef?.textContent?.trim(),
		proefFont: proef ? getComputedStyle(proef).fontFamily : null
	};
});

await page.locator('.fonts').first().screenshot({ path: `${OUT}/${ronde}-lijst.png` });
console.log(JSON.stringify(meting, null, 1));

// De eerste familie in de rij is degene die daadwerkelijk tekent; staat
// `ok-preview-*` vooraan, dan staat de naam in het gekozen lettertype.
const naamIsInterface = !/^ok-preview-/.test((meting.naamFont ?? '').trim());
const proefIsHetFont = /ok-preview-/.test(meting.proefFont ?? '');
console.log('naam in interfacelettertype:', naamIsInterface);
console.log('voorbeeld in het gekozen lettertype:', proefIsHetFont);
if (page.problems.length) console.log('console:', page.problems.slice(0, 5));
await b.close();
if (!(naamIsInterface && proefIsHetFont)) {
	console.log('FAAL');
	process.exit(1);
}
console.log('GOED');
