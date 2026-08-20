/**
 * Zaaigoed voor de tweede usability-ronde: Lagen en Job.
 *
 * Meer lagen dan de eerste ronde, want "druk" is precies wat er onderzocht
 * wordt — en een ontwerp met werk in elke laag, zodat de Job-tab iets te
 * vertellen heeft.
 */
const BASE = process.env.OK_BASE ?? 'http://localhost:8090';

async function post(pad, body) {
	const r = await fetch(BASE + pad, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});
	if (!r.ok) console.error('faalt', pad, r.status, (await r.text()).slice(0, 160));
	return r.ok ? r.json().catch(() => null) : null;
}
async function patch(pad, body) {
	const r = await fetch(BASE + pad, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!r.ok) console.error('faalt patch', pad, r.status);
}

await fetch(BASE + '/api/job/stop', { method: 'POST' }).catch(() => {});
await fetch(BASE + '/api/spooler/clear', { method: 'POST' }).catch(() => {});
await fetch(BASE + '/api/design/autosave', { method: 'DELETE' }).catch(() => {});
await post('/api/project/new');

// Vier lagen met eigen namen en waarden: snijden, twee keer graveren, rasteren.
const lagen = [
	{ type: 'cut', label: 'Buitenrand', speed: 12, power_percent: 65 },
	{ type: 'engrave', label: 'Opschrift', speed: 250, power_percent: 22 },
	{ type: 'engrave', label: 'Fijne lijnen', speed: 400, power_percent: 15 },
	{ type: 'raster', label: 'Logo vlak', speed: 300, power_percent: 30 }
];
const ids = [];
for (const laag of lagen) {
	const gemaakt = await post('/api/design/operations', laag);
	if (gemaakt) ids.push(gemaakt.id ?? gemaakt.operation_id ?? null);
}

// Werk, en dan per laag toewijzen zodat elke laag iets te branden heeft.
const vormen = [
	{ type: 'rect', x_mm: 15, y_mm: 15, width_mm: 120, height_mm: 80 },
	{ type: 'circle', cx_mm: 190, cy_mm: 55, r_mm: 30 },
	{ type: 'rect', x_mm: 20, y_mm: 110, width_mm: 40, height_mm: 30 },
	{ type: 'rect', x_mm: 80, y_mm: 110, width_mm: 40, height_mm: 30 },
	{ type: 'text', x_mm: 20, y_mm: 175, text: 'OpenKerf 5030', height_mm: 10 }
];
for (const vorm of vormen) await post('/api/design/elements', vorm);
await post('/api/design/generate/qrcode', { text: 'openkerf', size_mm: 34, x_mm: 250, y_mm: 120 });

const ontwerp = await (await fetch(BASE + '/api/design')).json();
const elementen = ontwerp.elements.map((e) => e.id);
const ops = ontwerp.operations.filter((o) => !o.grid).map((o) => o.id);

async function zet(elementIndex, opIndex) {
	const id = elementen[elementIndex];
	if (!id || !ops[opIndex]) return;
	// Eerst uit alle lagen, dan in de bedoelde: de engine classificeert nieuwe
	// vormen zelf, dus zonder dit zit alles ook nog in de laag waar de kleur hem
	// bracht.
	for (const op of ops) await post('/api/design/unassign', { ids: [id], operation_id: op });
	await post('/api/design/assign', { ids: [id], operation_id: ops[opIndex] });
}
// Ruwe verdeling: rand naar snijden, tekst naar opschrift, kleine vlakken naar
// fijne lijnen, de QR naar het rastervlak.
for (const [el, op] of [[0, 0], [1, 0], [2, 2], [3, 2], [4, 1], [5, 3]]) await zet(el, op);

// Een laag die niet meebrandt en een laag met passes: twee toestanden die de
// lijst moet kunnen tonen.
if (ops[2]) await patch(`/api/design/operations/${encodeURIComponent(ops[2])}`, { output: false });
if (ops[0]) await patch(`/api/design/operations/${encodeURIComponent(ops[0])}`, { passes: 3 });

const na = await (await fetch(BASE + '/api/design')).json();
console.log(
	'gezaaid:',
	na.elements.length,
	'vormen,',
	na.operations.filter((o) => !o.grid).length,
	'lagen'
);
