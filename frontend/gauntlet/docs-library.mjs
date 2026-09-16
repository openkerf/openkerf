import { scratchFetch as fetch } from './scratch.mjs';
/**
 * The library the handbook's pictures are of.
 *
 *   OK_SCRATCH_LIBRARY=1 OK_BASE=http://127.0.0.1:8092 node gauntlet/docs-library.mjs
 *
 * Until now the library screenshots were taken against whoever ran the script: the
 * pictures in `docs/images` show twenty materials with names like "Testmateriaal
 * 204350" and a board burned on a real KH-5030. That was never written down, and it
 * came out the moment the words in the app changed and the pictures had to be taken
 * again — on a scratch library the same command gives an empty window with the starter
 * offer over it, which is a different screen from the one the page describes.
 *
 * So this writes the library those pages are about. It is deliberately a script of its
 * own and not a step inside `docs-shots.mjs`: filling a library is a write, taking a
 * picture is not, and the two should not be able to happen by accident together.
 *
 * ## It cannot touch a real library
 *
 * Three locks:
 *
 * 1. `OK_SCRATCH_LIBRARY=1` has to be set. Same flag the board shots use.
 * 2. The library it finds has to be *empty*. A library with materials in it is
 *    somebody's, and this refuses rather than adding twenty of its own.
 * 3. Every request verifies the hardware-free scratch server marker.
 *
 * Start `scratch_server.py` and point `OK_BASE` at localhost:8092.
 * A separate library path alone does not isolate the machine configuration.
 */
const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8092';
const TOKEN = process.env.OK_TOKEN ?? '';

if (process.env.OK_SCRATCH_LIBRARY !== '1') {
	console.error(
		'Refusing to write a library without OK_SCRATCH_LIBRARY=1.\n' +
			'Start the isolated gauntlet/scratch_server.py server.'
	);
	process.exit(1);
}

async function api(method, path, body) {
	const response = await fetch(BASE + path, {
		method,
		headers: {
			'Content-Type': 'application/json',
			...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {})
		},
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	if (!response.ok) {
		const detail = await response.text();
		throw new Error(`${method} ${path} → ${response.status} ${detail.slice(0, 200)}`);
	}
	return response.status === 204 ? null : response.json().catch(() => null);
}

const existing = await api('GET', '/api/library/materials');
if (existing.length) {
	console.error(
		`Refusing: this library already holds ${existing.length} materials, so it is ` +
			'somebody’s. Start a fresh isolated gauntlet/scratch_server.py server.'
	);
	process.exit(1);
}

/**
 * The machine the whole handbook is about.
 *
 * The scratch dummy has a 500 x 300 bed. Its library profile carries simulated
 * laser type and power so the ordinary material and provenance UI can be reviewed.
 * No physical driver or user's machine profile is needed or activated.
 */
const engineMachines = (await api('GET', '/api/machines')) ?? [];
const active = engineMachines.find((m) => m.active && m.configured);
if (!active) {
	console.error(
		'No configured active simulated machine. Restart gauntlet/scratch_server.py.'
	);
	process.exit(1);
}
// The profile is minted by a read, not by a write — `_active_profile` in the engine
// layer, deliberately, so that opening the library on a fresh install does not file a
// machine nobody chose. So: ask, then the profile exists.
const machine = await api('GET', '/api/library/active-machine');
if (machine.device_path !== active.path) throw new Error('Scratch profile does not match the active machine');
await api('PATCH', `/api/library/machines/${machine.id}`, {
	laser_type: 'co2-glass',
	power_watt: 80
});

/**
 * Twenty materials, because the list in the picture is a list you scroll.
 *
 * The names are the ones a Dutch workshop has lying about, and they are deliberately
 * not translated: a material name is the user's own data, not text for users. Which is
 * also why they are the same in every language's screenshot.
 */
const MATERIALS = [
	'Berkentriplex',
	'Acrylaat (geëxtrudeerd)',
	'Acrylaat (gegoten)',
	'MDF',
	'MDF 8 mm',
	'Multiplex berken',
	'Massief eiken',
	'Populieren triplex',
	'Karton',
	'Papier',
	'Kurk',
	'Leer (plantaardig gelooid)',
	'Vilt 3 mm',
	'Glas',
	'Geanodiseerd aluminium',
	'Roestvast staal',
	'Gekleurd MDF 6 mm',
	'Bamboe',
	'Rubber (lasergeschikt)',
	'Polypropeen'
];

const made = {};
for (const name of MATERIALS) {
	made[name] = await api('POST', '/api/library/materials', { name });
}
console.log(`${MATERIALS.length} materials`);

/**
 * The presets.
 *
 * None of them says "measured on a test grid": that badge is earned below, by picking a
 * square off a board that really exists. A row that claims a measurement with nothing
 * behind it is a state the library calls out in as many words ("no test grid hangs off
 * it"), and a handbook picture of the provenance panel showing that sentence is a
 * picture of a fault.
 *
 * Enough of them, and of enough kinds, that every sentence the library page makes has
 * something to point at: a verified row and a manual one side by side (that is the
 * whole point of the source column), an extrapolated one with its warning, and one
 * that came off somebody else's machine. The counts behind the names in the list are
 * these rows; a material with none is as much part of the picture as one with three.
 */
const PRESETS = [
	{ material: 'Berkentriplex', operation: 'graveren-raster', thickness_mm: 3, speed_mm_s: 350, power_percent: 25, source: 'handmatig', interval_mm: 0.1 },
	{ material: 'Berkentriplex', operation: 'graveren-vector', thickness_mm: 3, speed_mm_s: 220, power_percent: 20, source: 'handmatig' },
	{ material: 'Berkentriplex', operation: 'snijden', thickness_mm: 6, speed_mm_s: 6, power_percent: 80, source: 'geextrapoleerd', passes: 2 },
	{ material: 'Acrylaat (geëxtrudeerd)', operation: 'snijden', thickness_mm: 3, speed_mm_s: 30, power_percent: 80, source: 'handmatig', air_assist: false },
	{ material: 'Acrylaat (geëxtrudeerd)', operation: 'graveren-raster', thickness_mm: 3, speed_mm_s: 400, power_percent: 30, source: 'geimporteerd', interval_mm: 0.08 },
	{ material: 'Acrylaat (geëxtrudeerd)', operation: 'snijden', thickness_mm: 5, speed_mm_s: 18, power_percent: 90, source: 'geextrapoleerd' },
	{ material: 'MDF', operation: 'snijden', thickness_mm: 3, speed_mm_s: 15, power_percent: 80, source: 'handmatig', air_assist: true },
	{ material: 'MDF', operation: 'graveren-raster', thickness_mm: 3, speed_mm_s: 300, power_percent: 35, source: 'geimporteerd', interval_mm: 0.1 },
	{ material: 'MDF 8 mm', operation: 'snijden', thickness_mm: 8, speed_mm_s: 4, power_percent: 95, source: 'geextrapoleerd', passes: 2 },
	{ material: 'Multiplex berken', operation: 'snijden', thickness_mm: 4, speed_mm_s: 10, power_percent: 70, source: 'geimporteerd', unattached: true },
	{ material: 'Karton', operation: 'snijden', thickness_mm: 2, speed_mm_s: 60, power_percent: 25, source: 'handmatig' },
	{ material: 'Leer (plantaardig gelooid)', operation: 'graveren-raster', thickness_mm: 2, speed_mm_s: 500, power_percent: 18, source: 'handmatig', interval_mm: 0.12 },
	{ material: 'Geanodiseerd aluminium', operation: 'markeren', thickness_mm: 1, speed_mm_s: 800, power_percent: 60, source: 'geimporteerd' },
	{ material: 'Kurk', operation: 'snijden', thickness_mm: 3, speed_mm_s: 25, power_percent: 45, source: 'handmatig', unattached: true }
];

// Every row belongs to this machine. A preset with no machine on it is a real state —
// the strip in the picture of the material verbs is about exactly those — but it is the
// exception, and a library where *every* row carries "other kind" is a library nobody
// has. Two rows below are left unattached on purpose, so that strip has something to
// count.
for (const preset of PRESETS) {
	const { material, unattached, ...fields } = preset;
	await api('POST', '/api/library/presets', {
		material_id: made[material].id,
		...(unattached ? {} : { machine_id: machine.id }),
		...fields
	});
}
console.log(`${PRESETS.length} presets over ${new Set(PRESETS.map((p) => p.material)).size} materials`);

/**
 * A board behind one of them.
 *
 * "Where did this number come from" is the question the library exists to answer, so
 * one preset has a real test grid hanging off it. No photograph is attached: that needs
 * a JPEG of a plank somebody burned, and the shots script argues in its own comments
 * why a synthetic one does not belong in `docs/images`. The provenance list is the part
 * of that picture this can honestly seed.
 */
const grid = await api('POST', '/api/library/testgrids', {
	operation: 'snijden',
	material_id: made['Berkentriplex'].id,
	thickness_mm: 3,
	row_axis: 'speed',
	column_axis: 'power',
	speed_min: 8,
	speed_max: 20,
	speed_steps: 4,
	power_min: 40,
	power_max: 90,
	power_steps: 4,
	cell_mm: 8,
	gap_mm: 2,
	origin_x_mm: 40,
	origin_y_mm: 30,
	caption: 'Berkentriplex 3 mm',
	uid: 'DOCS0001'
});
console.log(`test grid #${grid?.id ?? '?'} on Berkentriplex`);

/**
 * And the preset that came off it, made the way a user makes one.
 *
 * Not `POST /api/library/presets` with `source: 'testraster'` on it — that is a row
 * that *claims* it was measured with nothing behind it, and the library says so in as
 * many words: "This preset says it was measured, but no test grid hangs off it." A
 * screenshot of the provenance panel showing that sentence is a picture of a fault.
 * `POST /api/library/testgrids/{id}/presets` picks a square, so the row and the board
 * know about each other, which is what the page is about.
 */
const chosen = await api('POST', `/api/library/testgrids/${grid.id}/presets`, {
	cells: [
		{ row: 2, column: 2 },
		{ row: 3, column: 2 }
	]
});
console.log(`${chosen?.presets?.length ?? 0} presets off that board, verified with it behind them`);

console.log('\nThe library the handbook is about is ready.');
