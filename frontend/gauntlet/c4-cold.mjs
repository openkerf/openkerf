/**
 * Criticus 4 — de koude blik.
 *
 * Wat ziet iemand die de app nooit eerder zag? Lege bibliotheek, geen machine.
 * Systeemtaal in de interface is een major: de gebruiker praat geen protocol.
 */
import { browser, open, report, reset } from './harness.mjs';

await reset();
const b = await browser();
const findings = [];
const page = await open(b, { width: 1440 });
await page.screenshot({ path: 'gauntlet/shots/koud-start.png' });

// --- systeemtaal in zichtbare tekst
// Een HTTP-foutcode in beeld is systeemtaal; een bedmaat van 406 mm en een
// snelheid van 400 mm/s zijn dat niet. Op drie losse cijfers zoeken vindt het
// verschil niet — deze meter meldde "bed 610 x 406 mm" als lek. Daarom alleen
// nog codes die als code gepresenteerd worden.
const words = ['WebSocket', 'API', 'HTTP\\s*[45][0-9][0-9]', 'status\\s*[45][0-9][0-9]',
	'HTTP', 'null', 'undefined',
	'JSON', 'endpoint', 'token', 'fetch', 'timeout', 'exception', 'traceback', 'localhost',
	'127.0.0.1', 'uri', 'URI', 'svg-node', 'DOM'];
const jargon = await page.evaluate((patterns) => {
	const found = [];
	const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
	let node;
	while ((node = walker.nextNode())) {
		const text = node.textContent.trim();
		if (!text || text.length > 200) continue;
		const el = node.parentElement;
		if (!el || !el.getBoundingClientRect().width) continue;
		for (const p of patterns) {
			if (new RegExp(`\\b${p}\\b`).test(text)) {
				found.push(`"${text.slice(0, 60)}" (${p})`);
				break;
			}
		}
	}
	return [...new Set(found)].slice(0, 10);
}, words);
if (jargon.length) {
	findings.push({ severity: 'major', what: `${jargon.length} plekken met systeemtaal in beeld`,
		evidence: jargon.join(' | ') });
}

// --- de lege staat: uitnodiging of muur?
const empty = await page.evaluate(() => {
	const panel = document.querySelector('.panel-scroll');
	const canvas = document.querySelector('.canvas');
	return {
		panelText: panel?.textContent.replace(/\s+/g, ' ').trim().slice(0, 300) ?? '',
		calls: [...document.querySelectorAll('button, a')]
			.filter((n) => n.getBoundingClientRect().width > 0 && !n.disabled)
			.map((n) => (n.textContent ?? '').replace(/\s+/g, ' ').trim() || n.getAttribute('aria-label') || '')
			.filter(Boolean)
			.slice(0, 30)
	};
});
console.log('actieve knoppen bij start:', empty.calls.length);
console.log('paneeltekst:', empty.panelText.slice(0, 160));

// Is er een zichtbare eerste stap?
const hasGuide = /begin|start|eerste|kies|maak|teken|voeg|laden|machine/i.test(empty.panelText);
if (!hasGuide) {
	findings.push({ severity: 'major', what: 'De lege staat wijst geen eerste stap aan',
		evidence: `rechterpaneel bevat: "${empty.panelText.slice(0, 120)}"` });
}

// --- foutmeldingen: zeggen ze wat je eraan doet?
// Alleen gevallen die écht misgaan. Een aanroep die gewoon slaagt is geen
// foutmelding, en die meenemen levert bevindingen op die er niet zijn.
const cases = [
	['adres buiten de bronnen', '/api/clipart/insert',
		{ method: 'POST', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ url: 'https://voorbeeld.nl/x.svg' }) }],
	['vel dat niet bestaat', '/api/sheets/bestaat-niet/activate', { method: 'POST' }],
	['lettertype buiten de mappen', '/api/design/fonts/import',
		{ method: 'POST', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ file: '/tmp/nep.otf' }) }],
	['doos die niet past', '/api/design/generate/box',
		{ method: 'POST', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ width_mm: 2000, depth_mm: 900, height_mm: 600, thickness_mm: 6, finger_mm: 20 }) }],
	['leeg zoeken', '/api/clipart/search?q=a', {}]
];
for (const [naam, url, init] of cases) {
	const out = await page.evaluate(async ([u, i]) => {
		const r = await fetch(u, i);
		const body = await r.json().catch(() => ({}));
		return { status: r.status, detail: String(body.detail ?? '') };
	}, [url, init]);
	if (out.status < 400) continue;
	const remedy = /kies|probeer|start|controleer|set |installeer|maak |gebruik|herstart|ask|eerst|laat |snijd|geef/i.test(out.detail);
	if (!remedy) {
		findings.push({ severity: 'major', what: `Melding "${naam}" zegt niet wat je eraan doet`,
			evidence: `${out.status}: ${out.detail.slice(0, 150)}` });
	} else {
		console.log(`melding ${naam}: ok`);
	}
}

// --- een lege job starten hoort geweigerd te worden, niet "gelukt" te melden
const emptyStart = await page.evaluate(async () => {
	await fetch('/api/design/clear', { method: 'POST' });
	const r = await fetch('/api/job/start', { method: 'POST' });
	const body = await r.json().catch(() => ({}));
	return { status: r.status, detail: JSON.stringify(body).slice(0, 160) };
});
if (emptyStart.status < 400) {
	findings.push({ severity: 'major', what: 'Een lege job meldt "gelukt"',
		evidence: `${emptyStart.status}: ${emptyStart.detail}` });
} else {
	console.log('lege job: netjes geweigerd');
}

// --- ontwikkelaarstaal in de vaste panelen
const dev = await page.evaluate(() => {
	const bad = [];
	for (const h of document.querySelectorAll('.section-title')) {
		const t = h.textContent.trim();
		if (/engine|signaal|signalen|socket|debug|payload/i.test(t)) bad.push(t);
	}
	return bad;
});
if (dev.length) {
	findings.push({ severity: 'major', what: 'Ontwikkelaarstaal in een paneelkop',
		evidence: dev.join(' | ') });
}

// --- de tekst bij verlies van connection: protocoltaal of mensentaal?
const offline = await page.evaluate(() => {
	const bar = document.querySelector('.statusbar');
	return bar ? bar.textContent.replace(/\s+/g, ' ').trim() : '';
});
if (/websocket|api|socket|http/i.test(offline)) {
	findings.push({ severity: 'major', what: 'De statusbalk praat protocoltaal',
		evidence: offline.slice(0, 120) });
} else {
	console.log('statusbalk:', offline.slice(0, 90));
}

report('Criticus 4 — koude blik', findings);
await b.close();
