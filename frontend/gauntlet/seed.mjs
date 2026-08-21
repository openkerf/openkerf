/**
 * A design with something in it, for looking at screens that are not empty.
 *
 *   node gauntlet/seed.mjs
 *
 * Four layers with names and values of their own, work in every one of them, one
 * layer that does not burn along and one with passes — the states the list and
 * the job panel have to be able to show. Pure API, so no browser and no
 * selectors: this keeps working when the interface moves.
 */
const BASE = process.env.OK_BASE ?? 'http://localhost:8090';

async function post(path, body) {
	const r = await fetch(BASE + path, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});
	if (!r.ok) console.error('failed', path, r.status, (await r.text()).slice(0, 160));
	return r.ok ? r.json().catch(() => null) : null;
}
async function patch(path, body) {
	const r = await fetch(BASE + path, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!r.ok) console.error('patch failed', path, r.status);
}

await fetch(BASE + '/api/job/stop', { method: 'POST' }).catch(() => {});
await fetch(BASE + '/api/spooler/clear', { method: 'POST' }).catch(() => {});
await fetch(BASE + '/api/design/autosave', { method: 'DELETE' }).catch(() => {});
await post('/api/project/new');

// Four layers with names and values of their own: cut, engrave twice, raster.
const layers = [
	{ type: 'cut', label: 'Outline', speed: 12, power_percent: 65 },
	{ type: 'engrave', label: 'Caption', speed: 250, power_percent: 22 },
	{ type: 'engrave', label: 'Fine lines', speed: 400, power_percent: 15 },
	{ type: 'raster', label: 'Logo area', speed: 300, power_percent: 30 }
];
const ids = [];
for (const layer of layers) {
	const created = await post('/api/design/operations', layer);
	if (created) ids.push(created.id ?? created.operation_id ?? null);
}

// Work, then assigned per layer so that every layer has something to burn.
const shapes = [
	{ type: 'rect', x_mm: 15, y_mm: 15, width_mm: 120, height_mm: 80 },
	{ type: 'circle', cx_mm: 190, cy_mm: 55, r_mm: 30 },
	{ type: 'rect', x_mm: 20, y_mm: 110, width_mm: 40, height_mm: 30 },
	{ type: 'rect', x_mm: 80, y_mm: 110, width_mm: 40, height_mm: 30 },
	{ type: 'text', x_mm: 20, y_mm: 175, text: 'OpenKerf 5030', height_mm: 10 }
];
for (const shape of shapes) await post('/api/design/elements', shape);
await post('/api/design/generate/qrcode', { text: 'openkerf', size_mm: 34, x_mm: 250, y_mm: 120 });

const design = await (await fetch(BASE + '/api/design')).json();
const elements = design.elements.map((e) => e.id);
const ops = design.operations.filter((o) => !o.grid).map((o) => o.id);

async function set(elementIndex, opIndex) {
	const id = elements[elementIndex];
	if (!id || !ops[opIndex]) return;
	// Out of every layer first, then into the intended one: the engine classifies
	// new shapes itself, so without this everything is also still in the layer its
	// colour put it in.
	for (const op of ops) await post('/api/design/unassign', { ids: [id], operation_id: op });
	await post('/api/design/assign', { ids: [id], operation_id: ops[opIndex] });
}
// Rough division: the outline to cut, the text to the caption, the small
// rectangles to the fine lines, the QR to the raster area.
for (const [el, op] of [[0, 0], [1, 0], [2, 2], [3, 2], [4, 1], [5, 3]]) await set(el, op);

// A layer that does not burn along and a layer with passes: two states the list
// has to be able to show.
if (ops[2]) await patch(`/api/design/operations/${encodeURIComponent(ops[2])}`, { output: false });
if (ops[0]) await patch(`/api/design/operations/${encodeURIComponent(ops[0])}`, { passes: 3 });

const after = await (await fetch(BASE + '/api/design')).json();
console.log(
	'seeded:',
	after.elements.length,
	'shapes,',
	after.operations.filter((o) => !o.grid).length,
	'layers'
);
