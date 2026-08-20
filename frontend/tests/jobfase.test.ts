/**
 * De fase van de job: één afleiding voor alle oppervlakken.
 *
 * Draaien: `node --test frontend/tests/jobfase.test.ts`
 *
 * Waarom hier een test op staat. Vóór deze ronde las elk oppervlak zijn eigen
 * veld om te bepalen of er werk onderweg was — de bovenbalk de machinetoestand,
 * het Job-paneel `job.running`, de spoolerkaart `job.status`. Gemeten met een
 * job die gespoold was maar nog niet opgepakt (`status: "Waiting"`,
 * `running: false`, `progress: 0`): de bovenbalk zette starten uit en het paneel
 * liet het aan staan. Eén tik daar spoolde een tweede job bovenop de eerste.
 *
 * Dit pint de gevallen vast waar die vier velden elkaar tegenspreken.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const hier = dirname(fileURLToPath(import.meta.url));
const werk = join(hier, '.jobfase-tmp');

async function laad() {
	const ts = (await import('typescript')).default;
	mkdirSync(werk, { recursive: true });
	const bron = readFileSync(join(hier, '..', 'src', 'lib', 'api.ts'), 'utf8');
	const { outputText } = ts.transpileModule(bron, {
		compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
	});
	const pad = join(werk, 'api.mjs');
	writeFileSync(pad, outputText);
	return pad;
}

const mod = await import(await laad());
rmSync(werk, { recursive: true, force: true });

function job(over: Record<string, unknown> = {}) {
	return {
		label: 'Vel 1',
		type: 'LaserJob',
		status: 'Waiting',
		priority: 0,
		running: false,
		paused: false,
		steps_done: 0,
		steps_total: 287,
		progress: 0,
		loops_executed: 0,
		loops: 1,
		elapsed_seconds: 0,
		estimate_seconds: 298,
		...over
	};
}

const geenApparaat = null;

test('zonder job hangt de fase aan het bed', () => {
	assert.equal(mod.jobFase(geenApparaat, null, true), 'niets');
	assert.equal(mod.jobFase(geenApparaat, null, false), 'klaar-om-te-starten');
});

test('gespoold maar niet opgepakt is "in de wachtrij", niet "gepauzeerd"', () => {
	// Dit is het geval waar de oppervlakken op uit elkaar liepen: `running` is
	// onwaar, `progress` nul, en tóch is er werk onderweg.
	const fase = mod.jobFase(geenApparaat, job(), false);
	assert.equal(fase, 'in-de-wachtrij');
	assert.equal(mod.jobBezig(fase), true, 'er is werk onderweg, dus starten mag niet');
});

test('een lopende job brandt', () => {
	const fase = mod.jobFase(geenApparaat, job({ running: true, status: 'Running', progress: 0.4 }), false);
	assert.equal(fase, 'brandt');
	assert.equal(mod.jobBezig(fase), true);
});

test('een job die begonnen is en stilstaat, is gepauzeerd', () => {
	// `running` gaat bij Lihuiyu op false zodra je pauzeert, zonder dat het
	// statusveld het meldt. Begonnen + stil = pauze; nog niets gedaan = wachtrij.
	const fase = mod.jobFase(geenApparaat, job({ progress: 0.3, elapsed_seconds: 12 }), false);
	assert.equal(fase, 'gepauzeerd');
});

test('de pauzevlag van de driver is genoeg', () => {
	assert.equal(mod.jobFase(geenApparaat, job({ paused: true }), false), 'gepauzeerd');
});

test('vrijwel op honderd procent en stil betekent klaar', () => {
	// `calc_steps` telt één stap meer dan `execute` uitvoert, dus de voortgang
	// haalt 0,998 en de job blijft als "Waiting" in de wachtrij staan. Dat lezen
	// als "staat stil" is precies het bericht dat je niet wil onder werk dat af is.
	const fase = mod.jobFase(geenApparaat, job({ progress: 0.998, steps_done: 286, elapsed_seconds: 240 }), false);
	assert.equal(fase, 'klaar');
	assert.equal(mod.jobBezig(fase), false, 'een afgeronde job mag de machine niet blokkeren');
});

test('elke fase heeft een kop en een uitleg, en die zeggen iets', () => {
	for (const fase of [
		'niets',
		'klaar-om-te-starten',
		'in-de-wachtrij',
		'brandt',
		'gepauzeerd',
		'klaar'
	]) {
		const tekst = mod.FASE[fase];
		assert.ok(tekst, `${fase} heeft geen tekst`);
		assert.ok(tekst.kop.length > 3, `${fase}: kop te kort`);
		assert.ok(tekst.uitleg.length > 20, `${fase}: uitleg zegt niets`);
		assert.ok(!/^[a-z]/.test(tekst.kop), `${fase}: kop begint met een kleine letter`);
	}
});

test('"in de wachtrij" legt uit dat het niet hangt', () => {
	// De hele reden dat deze fase een eigen naam heeft: "Waiting" is voor een
	// gebruiker niet te onderscheiden van "hij doet niets meer".
	assert.match(mod.FASE['in-de-wachtrij'].uitleg, /nog niet opgepakt/);
	assert.match(mod.FASE['in-de-wachtrij'].uitleg, /verbinding/);
});

test('"klaar" zegt waarom de job in de wachtrij blijft staan', () => {
	assert.match(mod.FASE.klaar.uitleg, /wachtrij/);
});

test('Waiting wordt niet als Engels doorgegeven', () => {
	// Deze viel door alle takken van `jobStatusLabel` heen en kwam ongefilterd op
	// het scherm — het enige Engelse woord in de Job-tab.
	assert.equal(mod.jobStatusLabel(job({ status: 'Waiting' })), 'In wachtrij');
	assert.equal(mod.jobStatusLabel(job({ status: 'Queued' })), 'In wachtrij');
	assert.equal(mod.jobStatusLabel(job({ status: 'Running', running: true })), 'Bezig');
	assert.equal(mod.jobStatusLabel(job({ status: 'Paused' })), 'Gepauzeerd');
});
