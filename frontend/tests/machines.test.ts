/**
 * Eenheidstests voor de soort-indeling van de machinecatalogus.
 *
 * Draaien: `node --test frontend/tests/` — Node strippt de types zelf, en
 * `machines.svelte.ts` heeft geen runtime-imports en geen runes, dus er is geen
 * bundelstap voor nodig.
 *
 * Waarom dit bestand bestaat: de indeling liep per *familie*, en MeerK40t's
 * familie "K-Series CO2-Laser" bevat naast de Nano-borden ook `ruida-beta`, de
 * enige Ruida in de hele catalogus. Daardoor toonde de soort "CO2 met Ruida of
 * Newly" eenendertig Newly's en nul Ruida's — precies de machine waar OpenKerf
 * zelf voor bedoeld is.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { kindOfMachine, KINDS } from '../src/lib/machines.svelte.ts';

/** De catalogus zoals `/api/machines/catalog` hem op 0.9.9040 teruggeeft. */
const CATALOGUS = [
	{ family: 'K-Series CO2-Laser', key: 'm2-nano', provider: 'provider/device/lhystudios' },
	{ family: 'K-Series CO2-Laser', key: 'm3-nano', provider: 'provider/device/lhystudios' },
	{ family: 'K-Series CO2-Laser', key: 'grbl-dlc32-k40-400', provider: 'provider/device/grbl' },
	{ family: 'K-Series CO2-Laser', key: 'grbl-k40', provider: 'provider/device/grbl' },
	{ family: 'K-Series CO2-Laser', key: 'ruida-beta', provider: 'provider/device/ruida' },
	{ family: 'Longer Diode-Laser', key: 'grbl-longer-ray5', provider: 'provider/device/grbl' },
	{ family: 'Ortur Diode-Laser', key: 'grbl-ortur', provider: 'provider/device/grbl' },
	{ family: 'Generic', key: 'grbl-fluidnc', provider: 'provider/device/grbl' },
	{ family: 'Generic', key: 'grbl-diode', provider: 'provider/device/grbl' },
	{ family: 'Generic Diode-Laser', key: 'grbl-generic', provider: 'provider/device/grbl' },
	{ family: 'Generic Fibre-Laser', key: 'balor-fiber', provider: 'provider/device/balor' },
	{ family: 'Generic Fibre-Laser', key: 'balor-fiber-mopa', provider: 'provider/device/balor' },
	{ family: 'Generic CO2-Laser', key: 'balor-co2', provider: 'provider/device/balor' },
	{ family: 'Generic CO2-Laser', key: 'moshi-co2', provider: 'provider/device/moshi' },
	{ family: 'Generic UV-Laser', key: 'balor-uv', provider: 'provider/device/balor' },
	{ family: 'Newly CO2-Laser', key: 'g3v8-amc', provider: 'provider/device/newly' },
	{ family: 'Newly CO2-Laser', key: 'g3v8-rabbit', provider: 'provider/device/newly' }
];

test('de enige Ruida in de catalogus staat onder "CO2 met Ruida of Newly"', () => {
	const ruida = CATALOGUS.find((m) => m.key === 'ruida-beta')!;
	assert.equal(kindOfMachine(ruida), 'co2-ruida');
});

test('de soort die Ruida belooft levert ook minstens één Ruida op', () => {
	const inSoort = CATALOGUS.filter((m) => kindOfMachine(m) === 'co2-ruida');
	assert.ok(
		inSoort.some((m) => m.provider === 'provider/device/ruida'),
		`geen enkele Ruida in de soort co2-ruida: ${inSoort.map((m) => m.key).join(', ')}`
	);
});

test('de Nano-borden en de GRBL-K40 blijven onder K40', () => {
	for (const key of ['m2-nano', 'm3-nano', 'grbl-k40', 'grbl-dlc32-k40-400']) {
		const m = CATALOGUS.find((x) => x.key === key)!;
		assert.equal(kindOfMachine(m), 'co2-k40', key);
	}
});

test('GRBL buiten een K40-kast blijft diode, Balor blijft galvo, Newly en Moshi blijven CO2', () => {
	assert.equal(kindOfMachine(CATALOGUS.find((m) => m.key === 'grbl-ortur')!), 'diode');
	assert.equal(kindOfMachine(CATALOGUS.find((m) => m.key === 'grbl-fluidnc')!), 'diode');
	assert.equal(kindOfMachine(CATALOGUS.find((m) => m.key === 'balor-uv')!), 'galvo');
	assert.equal(kindOfMachine(CATALOGUS.find((m) => m.key === 'balor-co2')!), 'galvo');
	assert.equal(kindOfMachine(CATALOGUS.find((m) => m.key === 'g3v8-amc')!), 'co2-ruida');
	assert.equal(kindOfMachine(CATALOGUS.find((m) => m.key === 'moshi-co2')!), 'co2-ruida');
});

test('geen enkele machine valt buiten de vier soorten, en elke soort is gevuld', () => {
	const ids = new Set(KINDS.map((k) => k.id));
	const gevuld = new Set<string>();
	for (const m of CATALOGUS) {
		const soort = kindOfMachine(m);
		assert.ok(ids.has(soort), `${m.key} kreeg onbekende soort ${soort}`);
		gevuld.add(soort);
	}
	assert.deepEqual([...ids].filter((id) => !gevuld.has(id)), []);
});

test('een onbekende provider uit een latere upstream valt terug op de naam', () => {
	assert.equal(
		kindOfMachine({ family: 'Something CO2-Laser', key: 'iets', provider: 'provider/device/xyz' }),
		'co2-ruida'
	);
	assert.equal(kindOfMachine({ family: 'Onbekend', key: 'iets', provider: null }), 'diode');
});
