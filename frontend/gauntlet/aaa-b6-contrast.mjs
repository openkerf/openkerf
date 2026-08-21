/**
 * Contrastmeting op de detectiestaten van stap 1 (besluit B6).
 *
 * De auditor komt uit `aaa-donker-wizard.mjs` — die stapelt de hele
 * voorouderketen op elkaar in plaats van `backgroundColor` af te lezen, wat de
 * enige manier is om een badge met een doorzichtige waas eerlijk te meten. Hier
 * hergebruikt in plaats van overgeschreven: twee auditors die uit elkaar lopen
 * is erger dan één die je uit een bestand moet vissen.
 */
import { readFileSync } from 'node:fs';
import { browser, open } from './harness.mjs';

const bron = readFileSync(new URL('./aaa-donker-wizard.mjs', import.meta.url), 'utf8');
// De bron is een template literal; rauw ingelezen staan de backslashes er nog
// dubbel in, en dan sneuvelt de eerste reguliere expressie.
const AUDIT = bron
	.slice(bron.indexOf('const AUDIT = `') + 15, bron.indexOf('}`;\n') + 1)
	.replace(/\\\\/g, '\\');

const VONDSTEN = {
	candidates: [
		{
			id: 'udp:192.168.1.55', transport: 'netwerk', title: 'Ruida-besturing op het netwerk',
			where: '192.168.1.55', detail: 'antwoordde op poort 50200', kind: 'co2-ruida',
			confidence: 'zeker', why: 'Dit adres antwoordde op de ask die de Ruida-driver ook stelt.',
			suggestions: [{ key: 'ruida-beta', label: 'Ruida', family: 'K-Series CO2-Laser' }],
			settings: { interface: 'udp', address: '192.168.1.55' }
		},
		{
			id: 'serial:/dev/cu.usbserial-1420', transport: 'serieel', title: 'CH340-seriële poort',
			where: '/dev/cu.usbserial-1420', detail: 'USB2.0-Serial', kind: 'diode',
			confidence: 'onzeker', why: 'De CH340 zit op vrijwel elk GRBL-diodeframe.',
			suggestions: [
				{ key: 'grbl-generic', label: 'GRBL (generiek)', family: 'Generic' },
				{ key: 'grbl-fluidnc', label: 'FluidNC', family: 'Generic' }
			],
			settings: { serial_port: '/dev/cu.usbserial-1420' }
		}
	],
	searched: ['USB', 'seriële poorten', 'netwerk 192.168.1.0/24'],
	notes: [],
	duration_ms: 2410
};

const LEEG = {
	candidates: [],
	searched: ['USB', 'seriële poorten', 'netwerk 10.0.0.0/24'],
	notes: ['Op 10.0.0.0/24 antwoordde niets op poort 50200. Staat de machine aan?'],
	duration_ms: 2010
};

const b = await browser();
let totaal = 0;
const krapste = [];

for (const breedte of [1440, 390]) {
	for (const thema of ['light', 'dark']) {
		for (const [naam, stub, wacht] of [
			['gevonden', VONDSTEN, '.vondst'],
			['leeg', LEEG, '.niets']
		]) {
			const page = await open(b, { width: breedte, theme: thema, path: '/setup/kind' });
			await page.route('**/api/machines/scan*', (r) => r.fulfill({ json: stub }));
			await page.getByRole('button', { name: 'Machines zoeken' }).click();
			await page.waitForSelector(wacht, { timeout: 10000 });
			await page.waitForTimeout(300);

			const eerste = await page.evaluate(`(${AUDIT})()`);
			const slecht = eerste.fouten;
			let krapst = eerste.laagste;
			for (const el of await page.$$('a, button')) {
				if (!(await el.isVisible())) continue;
				await el.hover({ force: true }).catch(() => {});
				await page.waitForTimeout(50);
				const raak = await page.evaluate(`(${AUDIT})()`);
				if (raak.laagste.r < krapst.r) krapst = { ...raak.laagste, hover: true };
				for (const x of raak.fouten)
					if (!slecht.some((s) => s.t === x.t)) slecht.push({ ...x, hover: true });
			}
			if (slecht.length) {
				totaal += slecht.length;
				console.log(`\n${breedte} ${thema} ${naam}`);
				for (const x of slecht)
					console.log(
						`  [${x.r} < ${x.eis}]${x.hover ? ' (hover)' : ''} "${x.t}" ${x.px}px` +
							`  fg=${x.fg} bg=${x.bg}  .${x.cls}`
					);
			}
			krapste.push({ naam, breedte, thema, ...krapst });
			await page.context().close();
		}
	}
}
await b.close();

console.log(totaal === 0 ? '\ndetectie: alles haalt zijn eis' : `\ndetectie: ${totaal} bevindingen`);
console.log('\nkrapste geslaagde meting per staat:');
for (const k of krapste)
	console.log(`  ${k.breedte} ${k.thema} ${k.naam}: ${k.r} (eis ${k.eis}) "${k.t}"`);
