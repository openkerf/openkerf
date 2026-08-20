/**
 * De handelingenlijst: één bron voor het menu, de actiebalk en het toetsenbord.
 *
 * Draaien: `node --test frontend/tests/acties.test.ts`
 *
 * Wat hier vastgepind wordt is niet de opmaak maar de belofte die het bestand
 * doet: dat de drie oppervlakken niet uit elkaar kunnen lopen, dat een
 * uitgeschakelde regel altijd zégt waarom, en dat de sneltoetsen die de browser
 * afpakt er niet in staan. Dat laatste is de valstrik: ⌘0 en ⌘− zijn in Chrome
 * niet af te vangen, dus een sneltoets die daarop wijst laat de pagina
 * verschalen in plaats van het bed.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const hier = dirname(fileURLToPath(import.meta.url));
const werk = join(hier, '.acties-tmp');

// `acties.ts` is TypeScript; node --test leest dat niet. De officiële compiler
// staat al in de devDependencies, dus laten we die de types eruit halen — zelf
// regexen op TypeScript is een bron van tests die falen op hun eigen parser in
// plaats van op de code.
async function laad() {
	const ts = (await import('typescript')).default;
	mkdirSync(werk, { recursive: true });
	const bron = readFileSync(join(hier, '..', 'src', 'lib', 'acties.ts'), 'utf8');
	const { outputText } = ts.transpileModule(bron, {
		compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
	});
	const pad = join(werk, 'acties.mjs');
	writeFileSync(pad, outputText);
	return pad;
}

const mod = await import(await laad());
rmSync(werk, { recursive: true, force: true });

const NIETS = () => {};
const HANDELINGEN = new Proxy(
	{},
	{
		get: () => NIETS
	}
);

function context(over: Record<string, unknown> = {}) {
	return {
		aantal: 1,
		inGroep: false,
		isAfbeelding: false,
		isTekst: false,
		isBijgesneden: false,
		gevuld: false,
		klembord: 0,
		bezig: false,
		mag: true,
		lagen: [],
		vellen: [],
		vastklikken: true,
		laagnummers: true,
		leeg: false,
		teSplitsen: { vormen: 0, stukken: 0 },
		...over
	};
}

/** Alle regels van een menu, submenu's inbegrepen. */
function regels(menu: any[]): any[] {
	const uit: any[] = [];
	for (const groep of menu)
		for (const item of groep.items) {
			if (item === 'scheiding') continue;
			uit.push(item);
			if (item.items) uit.push(...item.items);
		}
	return uit;
}

test('de sneltoetsen laten de zoom van de browser met rust', () => {
	// ⌘0, ⌘+ en ⌘− zijn in Chrome niet af te vangen. Een sneltoets die daarop
	// wijst, verschaalt de pagina in plaats van het bed.
	const onafvangbaar = ['mod+0', 'mod+=', 'mod+-', 'mod+shift+0'];
	for (const combo of Object.values<string>(mod.TOETSEN))
		assert.ok(
			!onafvangbaar.includes(combo),
			`${combo} is een sneltoets van de browser zelf en hoort hier niet te staan`
		);
});

test('elke sneltoets is uniek, behalve waar dat expres is', () => {
	const gezien = new Map();
	// Twee toetsen voor één handeling mag: ⌘⇧G en ⌘U doen beide "groep opheffen",
	// en de zoomtoetsen hebben hun oude variant erbij.
	const mag = new Set(['groepOpheffen2', 'zoomAllesOud', 'zoomSelectieOud', 'zoomSelectieLightburn']);
	for (const [naam, combo] of Object.entries(mod.TOETSEN)) {
		if (mag.has(naam)) continue;
		assert.ok(!gezien.has(combo), `${combo} zit op zowel ${gezien.get(combo)} als ${naam}`);
		gezien.set(combo, naam);
	}
});

test('een toetsaanslag wordt gelezen als de combo die in de tabel staat', () => {
	const lees = (over: Record<string, unknown>) =>
		mod.comboVan({ metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, key: 'a', ...over });
	assert.equal(lees({ metaKey: true, key: 'c' }), 'mod+c');
	assert.equal(lees({ ctrlKey: true, key: 'C' }), 'mod+c');
	assert.equal(lees({ metaKey: true, shiftKey: true, key: 'z' }), 'mod+shift+z');
	assert.equal(lees({ key: 'Backspace' }), 'delete');
	// Shift+1 geeft "!" op een US-indeling; beide moeten dezelfde combo geven,
	// anders werkt de sneltoets op de ene toetsenindeling en op de andere niet.
	assert.equal(lees({ shiftKey: true, key: '!' }), 'shift+1');
	assert.equal(lees({ shiftKey: true, key: '1' }), 'shift+1');
});

test('een uitgeschakelde regel zegt altijd waarom', () => {
	for (const ctx of [
		context({ aantal: 0 }),
		context({ aantal: 1 }),
		context({ mag: false }),
		context({ bezig: true }),
		context({ aantal: 3, inGroep: true })
	])
		for (const regel of [
			...regels(mod.objectMenu(ctx, HANDELINGEN)),
			...regels(mod.canvasMenu(ctx, HANDELINGEN, null))
		])
			if ('uit' in regel && regel.uit !== undefined)
				assert.ok(
					typeof regel.uit === 'string' && regel.uit.length > 3,
					`"${regel.label}" staat uit zonder reden`
				);
});

test('zonder selectie kan er niets op een vorm gebeuren', () => {
	const menu = mod.objectMenu(context({ aantal: 0 }), HANDELINGEN);
	for (const regel of regels(menu))
		assert.ok(regel.uit, `"${regel.label}" is bruikbaar zonder dat er iets gekozen is`);
});

test('groeperen vraagt twee vormen, verdelen drie', () => {
	const een = mod.objectMenu(context({ aantal: 1 }), HANDELINGEN);
	const twee = mod.objectMenu(context({ aantal: 2 }), HANDELINGEN);
	const drie = mod.objectMenu(context({ aantal: 3 }), HANDELINGEN);
	const zoek = (menu: any[], id: string) => regels(menu).find((r) => r.id === id);

	assert.ok(zoek(een, 'groeperen').uit, 'groeperen kan met één vorm');
	assert.ok(!zoek(twee, 'groeperen').uit, 'groeperen kan niet met twee vormen');
	assert.ok(zoek(twee, 'uitlijn-spaceh').uit, 'verdelen kan al met twee vormen');
	assert.ok(!zoek(drie, 'uitlijn-spaceh').uit, 'verdelen kan niet met drie vormen');
	assert.ok(!zoek(twee, 'uitlijn-left').uit, 'uitlijnen kan niet met twee vormen');
});

test('groep opheffen kan alleen als de selectie in een groep zit', () => {
	const zoek = (ctx: Record<string, unknown>) =>
		regels(mod.objectMenu(ctx, HANDELINGEN)).find((r) => r.id === 'groepOpheffen');
	assert.ok(zoek(context({ aantal: 2 })).uit);
	assert.ok(!zoek(context({ aantal: 2, inGroep: true })).uit);
});

test('plakken kan niet met een leeg klembord, en zegt dat ook', () => {
	const leeg = regels(mod.canvasMenu(context(), HANDELINGEN, null)).find(
		(r) => r.id === 'plakken-hier'
	);
	assert.match(leeg.uit, /klembord/i);
	const vol = regels(mod.canvasMenu(context({ klembord: 2 }), HANDELINGEN, null)).find(
		(r) => r.id === 'plakken-hier'
	);
	assert.equal(vol.uit, undefined);
});

test('"plakken hier" heet alleen zo als er een plek bij zit', () => {
	const ctx = context({ klembord: 1 });
	const metPunt = regels(mod.canvasMenu(ctx, HANDELINGEN, { x: 10, y: 10 })).find(
		(r) => r.id === 'plakken-hier'
	);
	const zonder = regels(mod.canvasMenu(ctx, HANDELINGEN, null)).find(
		(r) => r.id === 'plakken-hier'
	);
	assert.equal(metPunt.label, 'Plakken hier');
	assert.equal(zonder.label, 'Plakken');
});

test('splitsen belooft het aantal dat er werkelijk uitkomt', () => {
	const zoek = (ctx: Record<string, unknown>) => regels(mod.objectMenu(ctx, HANDELINGEN)).find((r) => r.id === 'pad-split');
	const niets = zoek(context({ teSplitsen: { vormen: 0, stukken: 0 } }));
	assert.ok(niets.uit, 'splitsen staat aan terwijl er niets te splitsen is');
	const wel = zoek(context({ teSplitsen: { vormen: 1, stukken: 7 } }));
	assert.equal(wel.uit, undefined);
	assert.match(wel.label, /7/);
});

test('de vulknop zegt wat hij gaat doen, niet wat hij is', () => {
	const zoek = (ctx: Record<string, unknown>) => regels(mod.objectMenu(ctx, HANDELINGEN)).find((r) => r.id === 'vullen');
	assert.match(zoek(context({ gevuld: false })).label, /^Vullen/);
	assert.match(zoek(context({ gevuld: true })).label, /weghalen/i);
});

test('alleen wat op dit soort vorm van toepassing is, staat in het menu', () => {
	const gewoon = regels(mod.objectMenu(context(), HANDELINGEN)).map((r) => r.id);
	assert.ok(!gewoon.includes('bijsnijden'), 'een rechthoek biedt bijsnijden aan');
	assert.ok(!gewoon.includes('tekst'), 'een rechthoek biedt tekst bewerken aan');

	const beeld = regels(mod.objectMenu(context({ isAfbeelding: true }), HANDELINGEN)).map((r) => r.id);
	assert.ok(beeld.includes('bijsnijden'));
	assert.ok(beeld.includes('vectoriseren'));
	assert.ok(!beeld.includes('bijsnijden-terug'), 'de snede terugnemen kan zonder snede');

	const gesneden = regels(
		mod.objectMenu(context({ isAfbeelding: true, isBijgesneden: true }), HANDELINGEN)
	).map((r) => r.id);
	assert.ok(gesneden.includes('bijsnijden-terug'));

	const tekst = regels(mod.objectMenu(context({ isTekst: true }), HANDELINGEN)).map((r) => r.id);
	assert.ok(tekst.includes('tekst'));
});

test('verwijderen staat onderaan, en is het enige dat rood is', () => {
	const menu = mod.objectMenu(context(), HANDELINGEN);
	const laatste = menu[menu.length - 1].items;
	assert.equal(laatste.length, 1);
	assert.equal(laatste[0].id, 'verwijderen');
	const gevaarlijk = regels(menu).filter((r) => r.gevaar).map((r) => r.id);
	assert.deepEqual(gevaarlijk, ['verwijderen']);
});

test('de actiebalk en het menu delen dezelfde handelingen', () => {
	const ctx = context({ aantal: 3 });
	const balk = [
		...mod.uitlijnActies(ctx, HANDELINGEN),
		...mod.schikActies(ctx, HANDELINGEN)
	].map((a) => a.id);
	const menu = regels(mod.objectMenu(ctx, HANDELINGEN)).map((r) => r.id);
	for (const id of balk)
		assert.ok(menu.includes(id), `${id} staat in de actiebalk maar niet in het menu`);
});

test('een bestaande laag is aan te vinken, en "alleen in" staat eronder', () => {
	const ctx = context({
		lagen: [
			{ id: 'op1', label: 'Snijden', erin: true },
			{ id: 'op2', label: 'Graveren', erin: false }
		]
	});
	const laag = regels(mod.objectMenu(ctx, HANDELINGEN)).find((r) => r.id === 'laag');
	const namen = laag.items.map((i: any) => i.label);
	assert.deepEqual(namen.slice(0, 2), ['Snijden', 'Graveren']);
	assert.equal(laag.items[0].aan, true);
	assert.equal(laag.items[1].aan, false);
	assert.ok(namen.some((n: string) => /Alleen in de snijlaag/.test(n)));
});

test('een laagmenu weigert wat op een rasterlaag niet mag', () => {
	const menu = mod.laagMenu(
		{
			label: 'Snelheid 12',
			aantalVormen: 4,
			meebranden: true,
			zichtbaar: true,
			eerste: true,
			laatste: false,
			selectie: 2,
			erin: false,
			mag: true,
			opSlot: 'Deze laag hoort bij een testraster'
		},
		HANDELINGEN
	);
	const zoek = (id: string) => regels(menu).find((r) => r.id === id);
	assert.match(zoek('laag-weg').uit, /testraster/);
	assert.match(zoek('laag-meebranden').uit, /testraster/);
	// De vormen selecteren mag altijd: dat verandert niets aan de job.
	assert.equal(zoek('laag-selecteer').uit, undefined);
	// Eerste laag kan niet eerder branden, en dat staat erbij.
	assert.match(zoek('laag-omhoog').uit, /eerste/);
});

test('de sneltoets van een regel is dezelfde als in de tabel', () => {
	const menu = mod.objectMenu(context({ aantal: 2, klembord: 1 }), HANDELINGEN);
	const zoek = (id: string) => regels(menu).find((r) => r.id === id);
	assert.equal(zoek('kopieren').toets, mod.toetsLabel(mod.TOETSEN.kopieren));
	assert.equal(zoek('groeperen').toets, mod.toetsLabel(mod.TOETSEN.groeperen));
	assert.equal(zoek('verwijderen').toets, mod.toetsLabel(mod.TOETSEN.verwijderen));
});
