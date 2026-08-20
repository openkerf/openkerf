/**
 * Zaaigoed voor de usability-ronde: een ontwerp met genoeg inhoud dat de
 * schermen niet leeg zijn, plus een bibliotheek met een paar materialen.
 * Alleen desktop, alleen licht thema — zie GAUNTLET-USABILITY.md.
 */
const BASE = process.env.OK_BASE ?? 'http://localhost:8090';

async function post(path, body) {
	const r = await fetch(BASE + path, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!r.ok) console.error('faalt', path, r.status, (await r.text()).slice(0, 200));
	return r.ok ? r.json().catch(() => null) : null;
}

await fetch(BASE + '/api/design/autosave', { method: 'DELETE' }).catch(() => {});
await post('/api/project/new', {});

await post('/api/design/elements', { type: 'rect', x_mm: 20, y_mm: 20, width_mm: 60, height_mm: 40 });
await post('/api/design/elements', { type: 'circle', cx_mm: 150, cy_mm: 60, r_mm: 25 });
await post('/api/design/elements', { type: 'rect', x_mm: 30, y_mm: 90, width_mm: 35, height_mm: 35 });
await post('/api/design/generate/qrcode', { text: 'openkerf', size_mm: 30, x_mm: 220, y_mm: 30 });
await post('/api/design/elements', { type: 'text', x_mm: 25, y_mm: 150, text: 'OpenKerf', height_mm: 12 });

// Materialen met presets, zodat de bibliotheek er echt uitziet.
const MAT = [
	['Berkentriplex', [['snijden', 3, 12, 65, 'testraster'], ['graveren-vector', 3, 250, 20, 'geextrapoleerd'], ['snijden', 6, 7, 85, 'testraster']]],
	['Populier multiplex', [['snijden', 4, 10, 70, 'handmatig']]],
	['Acrylaat helder', [['snijden', 3, 14, 60, 'testraster'], ['graveren-raster', 3, 300, 25, 'handmatig']]],
	['MDF', [['snijden', 3, 11, 68, 'testraster'], ['snijden', 6, 6, 90, 'geextrapoleerd'], ['graveren-vector', 3, 220, 22, 'handmatig']]],
	['Leer plantaardig', [['graveren-raster', 2, 400, 15, 'testraster']]],
	['Karton grijs', [['snijden', 2, 25, 40, 'handmatig']]],
	['Kurk', [['snijden', 3, 18, 50, 'handmatig']]],
	['Bamboe', [['graveren-vector', 3, 200, 35, 'testraster']]]
];
for (const [naam, presets] of MAT) {
	const m = await post('/api/library/materials', { name: naam });
	if (!m) continue;
	for (const [op, dikte, snelheid, vermogen, bron] of presets) {
		await post('/api/library/presets', {
			material_id: m.id, operation: op, thickness_mm: dikte,
			speed_mm_s: snelheid, power_percent: vermogen, source: bron
		});
	}
}
console.log('gezaaid');
