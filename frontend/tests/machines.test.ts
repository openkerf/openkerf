/**
 * Unit tests for the kind classification of the machine catalogue.
 *
 * Run: `node --test frontend/tests/` — Node strips the types itself, and
 * `machines.svelte.ts` has no runtime imports and no runes, so no bundling step
 * is needed for it.
 *
 * Why this file exists: the classification ran per *family*, and MeerK40t's
 * family "K-Series CO2-Laser" holds `ruida-beta` beside the Nano boards — the
 * only Ruida in the whole catalogue. So the kind "CO2 with Ruida or Newly"
 * showed thirty-one Newlys and zero Ruidas — precisely the machine OpenKerf is
 * meant for.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { kindOfMachine, KINDS } from '../src/lib/machines.svelte.ts';

/** The catalogue as `/api/machines/catalog` hands it back on 0.9.9040. */
const CATALOGUE = [
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

test('the only Ruida in the catalogue sits under "CO2 with Ruida or Newly"', () => {
	const ruida = CATALOGUE.find((m) => m.key === 'ruida-beta')!;
	assert.equal(kindOfMachine(ruida), 'co2-ruida');
});

test('the kind that promises Ruida does give at least one Ruida', () => {
	const inKind = CATALOGUE.filter((m) => kindOfMachine(m) === 'co2-ruida');
	assert.ok(
		inKind.some((m) => m.provider === 'provider/device/ruida'),
		`not a single Ruida in the kind co2-ruida: ${inKind.map((m) => m.key).join(', ')}`
	);
});

test('the Nano boards and the GRBL K40 stay under K40', () => {
	for (const key of ['m2-nano', 'm3-nano', 'grbl-k40', 'grbl-dlc32-k40-400']) {
		const m = CATALOGUE.find((x) => x.key === key)!;
		assert.equal(kindOfMachine(m), 'co2-k40', key);
	}
});

test('GRBL outside a K40 case stays diode, Balor stays galvo, Newly and Moshi stay CO2', () => {
	assert.equal(kindOfMachine(CATALOGUE.find((m) => m.key === 'grbl-ortur')!), 'diode');
	assert.equal(kindOfMachine(CATALOGUE.find((m) => m.key === 'grbl-fluidnc')!), 'diode');
	assert.equal(kindOfMachine(CATALOGUE.find((m) => m.key === 'balor-uv')!), 'galvo');
	assert.equal(kindOfMachine(CATALOGUE.find((m) => m.key === 'balor-co2')!), 'galvo');
	assert.equal(kindOfMachine(CATALOGUE.find((m) => m.key === 'g3v8-amc')!), 'co2-ruida');
	assert.equal(kindOfMachine(CATALOGUE.find((m) => m.key === 'moshi-co2')!), 'co2-ruida');
});

test('no machine falls outside the four kinds, and every kind is filled', () => {
	const ids = new Set(KINDS.map((k) => k.id));
	const filled = new Set<string>();
	for (const m of CATALOGUE) {
		const kind = kindOfMachine(m);
		assert.ok(ids.has(kind), `${m.key} got unknown kind ${kind}`);
		filled.add(kind);
	}
	assert.deepEqual([...ids].filter((id) => !filled.has(id)), []);
});

test('an unknown provider from a later upstream falls back on the name', () => {
	assert.equal(
		kindOfMachine({ family: 'Something CO2-Laser', key: 'something', provider: 'provider/device/xyz' }),
		'co2-ruida'
	);
	assert.equal(kindOfMachine({ family: 'Unknown', key: 'something', provider: null }), 'diode');
});
