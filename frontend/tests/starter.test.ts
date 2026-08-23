/**
 * The offer of starting points: the one sum, and the two questions behind it.
 *
 * Run: `node --test frontend/tests/starter.test.ts`
 *
 * Three things are pinned here, and each one has a measurement behind it rather than
 * an opinion.
 *
 * **`offerState`.** Two surfaces make this offer — the top of the material library and
 * the last step of setup — and one function decides what they show, in the pattern
 * `actions.ts` and `jobPhase` set. It is worth a table because the interesting cases
 * are the ones that look alike: a machine with settings that were never burned is not
 * a machine with no settings, and neither is a machine somebody waved the card away
 * on. Measured on the author's own library, the active laser has three settings and a
 * phantom profile beside it carries twenty-six; a state machine that counts the wrong
 * ones makes a bare machine look supplied.
 *
 * **The laser kind.** `laserKindFor` is a deliberate second copy of `KIND_BY_SOURCE`
 * and `KIND_BY_FAMILY` in `api/openkerf_api/matching.py`: the engine layer derives the
 * kind from MeerK40t's registry but exposes no route that says so, and the wizard has
 * to *prefill* the field before anything is written. A second copy is only safe if
 * something notices it drifting, so the last test in this file reads the Python and
 * compares the two tables character by character. Without it, a rename upstream would
 * quietly tell a diode owner they have a CO2 tube — which is exactly what the column
 * default `'co2-glass'` does today on all seven of the author's live profiles.
 *
 * **The routes the wizard walks to.** `/setup/settings` sent the reader to
 * `/setup/ready` when they pressed Save and finish, and that route has never existed:
 * the layout registers `/setup/done`. So the last step of the wizard was a 404, and
 * with it went the sheet question, the route to a first cut, and the offer this whole
 * round is about.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { offerState, type StarterCoverage, type StarterOffer } from '../src/lib/library.svelte.ts';
import {
	KIND_BY_FAMILY,
	KIND_BY_SOURCE,
	laserKindFor,
	laserKindOfMachine
} from '../src/lib/machines.svelte.ts';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');

/** The six counts of `matching.coverage`, with everything at nothing by default. */
function coverage(over: Partial<StarterCoverage> = {}): StarterCoverage {
	return {
		mine: 0,
		mine_measured: 0,
		materials_covered: 0,
		materials_known: 20,
		unattached: 0,
		unattached_grids: 0,
		...over
	};
}

/** An offer as `GET /api/library/starter` hands it back. */
function offer(machine: Record<string, unknown> | null, over: Partial<StarterOffer> = {}) {
	return {
		machine: machine as StarterOffer['machine'],
		state: 'nothing',
		needed: true,
		coverage: coverage(),
		...over
	} as StarterOffer;
}

const described = {
	id: 5,
	name: 'KH-5030',
	laser_type: 'co2-glass',
	power_watt: 80,
	starter_state: ''
};

test('a machine nobody has described is asked, and not offered a fetch', () => {
	// The live shape: `power_watt: null` on the profile the engine is actually on. The
	// old client showed it all 26 rows of an 80 W catalogue, because the match skipped
	// the whole test whenever either side was silent.
	const view = offerState(offer({ ...described, power_watt: null }));
	assert.equal(view.state, 'askMachine');
	assert.equal(view.needsWatt, true);
	assert.equal(view.needsKind, false);
	assert.equal(view.canFetch, false, 'a bare fetch on a machine nobody described');
});

test('a machine of an unknown kind is asked as well', () => {
	const view = offerState(offer({ ...described, laser_type: 'unknown' }));
	assert.equal(view.state, 'askMachine');
	assert.equal(view.needsKind, true);
	assert.equal(view.canFetch, false);
});

test('"I am not sure what my tube is" is an answer and not a dead end', () => {
	// The escape hatch: no wattage, but the reader said so out loud. Then the match is
	// on the kind alone, the fetch is allowed, and every row has to say which promise
	// it is making.
	const view = offerState(
		offer({ ...described, power_watt: null, starter_state: 'power_unknown' })
	);
	assert.equal(view.state, 'nothing');
	assert.equal(view.canFetch, true);
	assert.equal(view.powerUnknown, true);
	assert.equal(view.needsWatt, false);
});

test('a described machine with nothing on it gets the offer', () => {
	const view = offerState(offer(described));
	assert.equal(view.state, 'nothing');
	assert.equal(view.needed, true);
	assert.equal(view.canFetch, true);
	assert.equal(view.suggestTestGrid, false);
});

test('settings that were never burned ask for a board, not for another catalogue', () => {
	// The answer to "everything I have came out of a catalogue" is not more catalogue.
	const view = offerState(
		offer(described, { coverage: coverage({ mine: 26, materials_covered: 14 }) })
	);
	assert.equal(view.state, 'unburned');
	assert.equal(view.suggestTestGrid, true);
});

test('a machine with one measurement of its own is left alone', () => {
	const view = offerState(
		offer(described, {
			coverage: coverage({ mine: 3, mine_measured: 3, materials_covered: 1 })
		})
	);
	assert.equal(view.state, 'none');
	assert.equal(view.needed, false, 'the card came back to a machine that has its own');
});

test('the card never comes back once it has been waved away', () => {
	// Every other reason to speak up is tested against a dismissal, because the card is
	// drawn on every open of the material library. One that returns is a nag.
	for (const over of [
		{ coverage: coverage() },
		{ coverage: coverage({ mine: 26 }) },
		{ coverage: coverage({ mine: 3, mine_measured: 3 }) }
	]) {
		const view = offerState(offer({ ...described, starter_state: 'dismissed' }, over));
		assert.equal(view.needed, false);
		assert.equal(view.state, 'none');
	}
	// And a dismissal outweighs a machine that has not been described either: the
	// wizard is then the place to describe it, not a card somebody put away.
	const bare = offerState(
		offer({ ...described, power_watt: null, starter_state: 'dismissed' })
	);
	assert.equal(bare.needed, false);
});

test('the coverage ratio never decides, so the card cannot become permanent', () => {
	// One of twenty materials covered is true of the author's library and would stay
	// true of it forever. The sentence carries that number; the trigger does not.
	const view = offerState(
		offer(described, {
			coverage: coverage({ mine: 3, mine_measured: 3, materials_covered: 1, materials_known: 20 })
		})
	);
	assert.equal(view.needed, false);
});

test('no machine at all is not a refusal, and no card', () => {
	assert.equal(offerState(null).needed, false);
	assert.equal(offerState(undefined).needed, false);
	assert.equal(offerState(offer(null, { state: 'none', needed: false })).needed, false);
	// `/api/library/active-machine` hands the profile and the offer apart, so a caller
	// may pass a state without a machine block. Then that state is used as it came.
	assert.equal(offerState(offer(null, { state: 'askMachine' })).state, 'askMachine');
	assert.equal(offerState(offer(null, { state: 'wat' })).state, 'none');
});

// ------------------------------------------------------------------ the laser kind

/** Entries of MeerK40t's own `dev_info` registry, as `/api/machines/catalog` gives them. */
const CATALOGUE = [
	{ family: 'K-Series CO2-Laser', key: 'ruida-beta', provider: 'provider/device/ruida', defaults: { source: 'co2' } },
	{ family: 'K-Series CO2-Laser', key: 'm2-nano', provider: 'provider/device/lhystudios', defaults: { source: 'co2' } },
	{ family: 'Newly CO2-Laser', key: 'g3v8-amc', provider: 'provider/device/newly', defaults: { source: 'Older CO2' } },
	{ family: 'Generic Diode-Laser', key: 'grbl-generic', provider: 'provider/device/grbl', defaults: { source: 'generic' } },
	{ family: 'Longer Diode-Laser', key: 'grbl-longer-ray5', provider: 'provider/device/grbl', defaults: { source: 'diode' } },
	{ family: 'Generic Fibre-Laser', key: 'balor-fiber', provider: 'provider/device/balor', defaults: { source: 'fiber' } },
	{ family: 'Generic UV-Laser', key: 'balor-uv', provider: 'provider/device/balor', defaults: { source: 'uv' } },
	{ family: 'Generic CO2-Laser', key: 'moshi-co2', provider: 'provider/device/moshi', defaults: {} },
	{ family: 'Generic', key: 'grbl-fluidnc', provider: 'provider/device/grbl', defaults: { source: 'generic' } }
];

const CATALOG = [{ family: 'all', priority: 0, machines: CATALOGUE as never[] }];

test('the kind comes from the catalogue entry, and a UV laser is not a fibre one', () => {
	const kinds = Object.fromEntries(CATALOGUE.map((e) => [e.key, laserKindFor(e)]));
	assert.deepEqual(kinds, {
		'ruida-beta': 'co2-glass',
		'm2-nano': 'co2-glass',
		'g3v8-amc': 'co2-glass',
		// No usable source, so the family name decides — which is what resolves the two
		// `generic` entries and the source-less moshi.
		'grbl-generic': 'diode',
		'grbl-longer-ray5': 'diode',
		'balor-fiber': 'fiber',
		'balor-uv': 'uv',
		'moshi-co2': 'co2-glass',
		// A FluidNC board drives whatever is bolted to it, and `unknown` says so rather
		// than letting a CO2 setting through onto a diode on the strength of a shrug.
		'grbl-fluidnc': 'unknown'
	});
});

test('the catalogue key beats the driver, and an ambiguous driver says nothing', () => {
	assert.equal(laserKindOfMachine(CATALOG, { info: 'balor-uv', provider: null }), 'uv');
	// A machine from before we stamped the key: the driver is all there is, and it is
	// only an answer when every entry that runs it agrees. Balor drives a fibre, a CO2
	// and a UV galvo, so it does not.
	assert.equal(
		laserKindOfMachine(CATALOG, { info: null, provider: 'provider/device/ruida' }),
		'co2-glass'
	);
	assert.equal(
		laserKindOfMachine(CATALOG, { info: null, provider: 'provider/device/balor' }),
		'unknown'
	);
	// GRBL runs a labelled diode, an unlabelled generic and a FluidNC that says
	// nothing, so it cannot answer either.
	assert.equal(
		laserKindOfMachine(CATALOG, { info: null, provider: 'provider/device/grbl' }),
		'unknown'
	);
	assert.equal(laserKindOfMachine(CATALOG, { info: 'nothing-like-it' }), 'unknown');
	assert.equal(laserKindOfMachine([], { info: 'balor-uv' }), 'unknown');
});

test('the interface derives the kind from the same table as the engine layer', () => {
	// The one thing that makes a second copy of a rule safe: something notices when the
	// two drift apart. `matching.py` is the original; this reads it rather than trusting
	// it, so a rename there fails here instead of mislabelling a laser.
	const python = readFileSync(join(root, 'api', 'openkerf_api', 'matching.py'), 'utf8');
	const sources = python.match(/^KIND_BY_SOURCE = \{([\s\S]*?)^\}/m);
	assert.ok(sources, 'KIND_BY_SOURCE is no longer a literal in matching.py');
	const pairs = [...sources[1].matchAll(/"([^"]+)":\s*"([^"]+)"/g)].map((m) => [m[1], m[2]]);
	assert.deepEqual(Object.fromEntries(pairs), KIND_BY_SOURCE);

	const families = python.match(/^KIND_BY_FAMILY = \(([\s\S]*?)^\)/m);
	assert.ok(families, 'KIND_BY_FAMILY is no longer a literal in matching.py');
	const rows = [...families[1].matchAll(/\("([^"]+)",\s*"([^"]+)"\)/g)].map((m) => [m[1], m[2]]);
	assert.deepEqual(rows, KIND_BY_FAMILY);
});

test('the kind is never asked as free text anywhere in the wizard', () => {
	// A field somebody types "80W CO2" into is a field that matches nothing. Every kind
	// on screen comes from the list, so this walks the wizard's own routes for a text
	// input bound to it.
	for (const path of sources(join(here, '..', 'src', 'routes', 'setup'))) {
		const source = readFileSync(path, 'utf8');
		assert.doesNotMatch(
			source,
			/type=['"]text['"][^>]*bind:value=\{laserKind\}/,
			`${path} asks for the laser kind as free text`
		);
	}
});

// ----------------------------------------------------------------- the wizard's routes

function sources(dir: string, found: string[] = []): string[] {
	for (const entry of readdirSync(dir)) {
		const path = join(dir, entry);
		if (statSync(path).isDirectory()) sources(path, found);
		else if (/\.svelte$/.test(entry)) found.push(path);
	}
	return found;
}

test('every step the wizard walks to is a route that exists', () => {
	// Measured before this: `/setup/settings` finished on `goto('/setup/ready')`, and
	// there is no `ready` directory under `routes/setup/`. The last step of setting up a
	// machine was therefore a 404 — for every machine anybody has ever added.
	const routes = join(here, '..', 'src', 'routes', 'setup');
	const known = new Set(
		readdirSync(routes).filter((entry) => statSync(join(routes, entry)).isDirectory())
	);
	const missing: string[] = [];
	for (const path of sources(routes)) {
		const source = readFileSync(path, 'utf8');
		for (const match of source.matchAll(/goto\(\s*[`'"]\/setup\/([a-z-]+)/g)) {
			if (!known.has(match[1])) missing.push(`${path} → /setup/${match[1]}`);
		}
	}
	assert.deepEqual(missing, [], `the wizard walks to routes that do not exist: ${missing}`);
	// And the guard on the guard: the check only means something if it found the gotos.
	assert.ok(known.has('done') && known.has('settings'));
});

test('nothing that measures the app can wave the offer away', () => {
	// Measured: one run of `gauntlet/i-overflow.mjs` turned the active profile's
	// `starter_state` from '' into 'dismissed'. Its opening routine presses whatever
	// button says "Not now", because that is how a notification banner is got out of the
	// way — and this card's own dismissal carries the same two words. So the offer went
	// away from the reader's real library, and the script then measured the place where
	// it had been.
	//
	// The card marks that one button `.away`; every script that clears the screen has to
	// exclude it. A regression here is silent by nature: the measurement still passes,
	// only quieter.
	const card = readFileSync(join(here, '..', 'src', 'lib', 'components', 'StarterOffer.svelte'), 'utf8');
	assert.match(card, /class="btn subtle away"/, 'the dismissal lost the class scripts avoid');
	for (const name of ['i-overflow.mjs', 'i-shots.mjs']) {
		const script = readFileSync(join(here, '..', 'gauntlet', name), 'utf8');
		if (!/Not now/.test(script)) continue;
		assert.match(
			script,
			/button:not\(\.away\)/,
			`${name} presses "Not now" without excluding the offer's own`
		);
	}
});
