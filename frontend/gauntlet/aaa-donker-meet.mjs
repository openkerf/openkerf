/**
 * Meten in plaats van kijken: hoe verhouden de themawaarden zich echt?
 *
 * Drie shouldAsk. (1) Halen tekst en rand hun contrast in beide thema's?
 * (2) Zijn aangrenzende vlakken (bed/canvas, kaart/paneel) in donker even goed
 * te onderscheiden als in licht? (3) Blijven de tien laagkleuren los van elkaar
 * én los van het bed?
 */
import { browser, open, reset } from './harness.mjs';

function ontleed(s) {
	const m = String(s).match(/rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+))?/);
	if (!m) return null;
	return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]];
}
function L([r, g, b]) {
	const k = [r, g, b].map((v) => {
		const s = v / 255;
		return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * k[0] + 0.7152 * k[1] + 0.0722 * k[2];
}
function ratio(a, b) {
	const [x, y] = [L(a), L(b)].sort((p, q) => q - p);
	return (x + 0.05) / (y + 0.05);
}
function over(fg, bg) {
	const a = fg[3];
	return [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a));
}

const KLEUREN = [
	'--surface-0', '--surface-1', '--surface-2', '--canvas-bg', '--bed', '--line',
	'--text-1', '--text-2', '--accent', '--accent-ink', '--danger', '--danger-solid',
	'--warn', '--warn-solid', '--ok', '--on-color', '--void',
	'--layer-1', '--layer-2', '--layer-3', '--layer-4', '--layer-5',
	'--layer-6', '--layer-7', '--layer-8', '--layer-9', '--layer-10',
	'--mat-hout', '--mat-acryl', '--mat-leer', '--mat-karton', '--mat-metaal',
	'--lift-1', '--lift-2', '--shadow-float', '--scrim'
];

const b = await browser();
const uit = {};
for (const thema of ['light', 'dark']) {
	await reset();
	const page = await open(b, { width: 1440, theme: thema, path: '/?tab=job' });
	const later = await page.$('button:has-text("Later")');
	if (later) await later.click();
	uit[thema] = await page.evaluate((namen) => {
		const s = getComputedStyle(document.documentElement);
		const o = {};
		for (const n of namen) o[n] = s.getPropertyValue(n).trim();
		// Ook echt gerenderde waarden ophalen van een paar sleutelelementen.
		const meet = (sel, props) => {
			const el = document.querySelector(sel);
			if (!el) return null;
			const c = getComputedStyle(el);
			const r = {};
			for (const p of props) r[p] = c.getPropertyValue(p);
			return r;
		};
		o['@body'] = meet('body', ['background-color', 'color']);
		o['@paneel'] = meet('.panel, aside, .side', ['background-color']);
		return o;
	}, KLEUREN);
	await page.context().close();
}
await b.close();

const naarRgb = (v) => {
	const h = v.match(/^#([0-9a-f]{6})$/i);
	if (h) return [0, 2, 4].map((i) => parseInt(h[1].slice(i, i + 2), 16)).concat(1);
	return ontleed(v);
};

console.log('token'.padEnd(16), 'licht'.padEnd(24), 'donker');
for (const n of KLEUREN) {
	console.log(n.padEnd(16), String(uit.light[n]).slice(0, 23).padEnd(24), uit.dark[n]);
}

console.log('\n== contrast per thema ==');
const paren = [
	['--text-1', '--surface-0'], ['--text-1', '--surface-1'], ['--text-2', '--surface-0'],
	['--text-2', '--surface-1'], ['--accent', '--surface-1'], ['--accent-ink', '--accent'],
	['--danger', '--surface-1'], ['--on-color', '--danger-solid'], ['--warn', '--surface-1'],
	['--ok', '--surface-1'], ['--line', '--surface-0'], ['--line', '--surface-1'],
	['--surface-1', '--surface-0'], ['--surface-2', '--surface-1'],
	['--bed', '--canvas-bg'], ['--text-1', '--bed']
];
for (const [a, c] of paren) {
	const r = {};
	for (const t of ['light', 'dark']) r[t] = ratio(naarRgb(uit[t][a]), naarRgb(uit[t][c]));
	const vlag = Math.abs(r.light - r.dark) > 0.6 || Math.min(r.light, r.dark) < 3 ? '  <<<' : '';
	console.log(
		`${a} op ${c}`.padEnd(34),
		`licht ${r.light.toFixed(2)}`.padEnd(14),
		`donker ${r.dark.toFixed(2)}` + vlag
	);
}

console.log('\n== laagkleuren tegen het bed ==');
for (let i = 1; i <= 10; i++) {
	const k = `--layer-${i}`;
	const r = {};
	for (const t of ['light', 'dark']) r[t] = ratio(naarRgb(uit[t][k]), naarRgb(uit[t]['--bed']));
	console.log(
		k.padEnd(12), uit.dark[k].padEnd(9),
		`licht ${r.light.toFixed(2)}`.padEnd(14),
		`donker ${r.dark.toFixed(2)}` + (r.dark < 3 || r.light < 3 ? '  <<<' : '')
	);
}

console.log('\n== onderling verschil tussen laagkleuren (min over alle paren) ==');
for (const t of ['light', 'dark']) {
	let min = 99, paar = '';
	for (let i = 1; i <= 10; i++)
		for (let j = i + 1; j <= 10; j++) {
			const r = ratio(naarRgb(uit[t][`--layer-${i}`]), naarRgb(uit[t][`--layer-${j}`]));
			if (r < min) { min = r; paar = `${i}/${j}`; }
		}
	console.log(t.padEnd(8), `laagste ${min.toFixed(2)} bij lagen ${paar}`);
}

console.log('\n== nummer in het kleurvakje (wit op de laagkleur) ==');
for (let i = 1; i <= 10; i++) {
	const wit = ratio([255, 255, 255, 1], naarRgb(uit.dark[`--layer-${i}`]));
	const zwart = ratio([0, 0, 0, 1], naarRgb(uit.dark[`--layer-${i}`]));
	console.log(`--layer-${i}`.padEnd(12), `wit ${wit.toFixed(2)}`.padEnd(11), `zwart ${zwart.toFixed(2)}`,
		wit < 4.5 && zwart < 4.5 ? '  <<< geen van beide haalt AA' : '');
}

console.log('\n== materiaalkleuren met witte bandtekst (72% zwarte sluier eronder) ==');
for (const m of ['--mat-hout', '--mat-acryl', '--mat-leer', '--mat-karton', '--mat-metaal']) {
	for (const t of ['light', 'dark']) {
		const grond = naarRgb(uit[t][m]);
		const sluier = over([0, 0, 0, 0.72], grond);
		console.log(`${m} ${t}`.padEnd(24), `wit op sluier ${ratio([255, 255, 255, 1], sluier).toFixed(2)}`);
	}
}
