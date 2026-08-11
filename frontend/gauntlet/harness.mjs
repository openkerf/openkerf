/**
 * Gereedschap voor de gauntlet.
 *
 * Bevindingen moeten bewijs hebben, dus meten we in de browser in plaats van
 * te kijken: afmetingen, berekende stijlen en tijden. Screenshots zijn het
 * archief, de metingen zijn het argument.
 */
import { chromium } from 'playwright';

export const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8090';
export const WIDTHS = { desktop: 1440, tablet: 1024, phone: 390 };

export async function browser() {
	return chromium.launch();
}

/**
 * Schone lei voor een criticus.
 *
 * Zonder dit staat het herstelvenster van een vorige meting over het scherm en
 * meet je door een modaal venster heen — dat kostte me een ronde voordat ik het
 * doorhad.
 */
export async function reset() {
	await fetch(`${BASE}/api/design/autosave`, { method: 'DELETE' }).catch(() => {});
	await fetch(`${BASE}/api/design/clear`, { method: 'POST' }).catch(() => {});
}

export async function open(b, { width = 1440, theme = 'light', path = '/' } = {}) {
	const context = await b.newContext({
		viewport: { width, height: width === 390 ? 844 : 900 },
		deviceScaleFactor: 1,
		colorScheme: theme === 'dark' ? 'dark' : 'light'
	});
	const page = await context.newPage();
	// Het thema vóór het tekenen zetten. Achteraf omschakelen betekent meten
	// tijdens de overgang, en dan lees je halverwege gemengde kleuren — dat
	// leverde "contrastfouten" op die na een seconde vanzelf weg waren.
	if (theme === 'dark') {
		await page.addInitScript(() => {
			// Een initscript draait al vóórdat <html> bestaat; dan is
			// documentElement nog null en gooit setAttribute.
			const zet = () => document.documentElement?.setAttribute('data-theme', 'dark');
			zet();
			document.addEventListener('DOMContentLoaded', zet);
		});
	}
	const problems = [];
	page.on('console', (m) => {
		if (m.type() === 'error') problems.push(m.text().slice(0, 160));
	});
	page.on('pageerror', (e) => problems.push(`pageerror: ${String(e).slice(0, 160)}`));
	await page.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 30000 });
	// Niet op networkidle wachten: de statusverbinding blijft open, dus die
	// toestand komt nooit. Wachten tot de app zelf getekend heeft.
	await page.waitForSelector('.statusbar, .setup', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(700);
	page.problems = problems;
	return page;
}

/** Alle zichtbare elementen met hun doos en een paar stijlen. */
export async function survey(page, selector = '*') {
	return page.$$eval(selector, (nodes) =>
		nodes
			.filter((n) => n.getBoundingClientRect().width > 0)
			.map((n) => {
				const r = n.getBoundingClientRect();
				const s = getComputedStyle(n);
				return {
					tag: n.tagName.toLowerCase(),
					cls: n.className?.baseVal ?? String(n.className ?? ''),
					text: (n.textContent ?? '').trim().slice(0, 40),
					x: +r.x.toFixed(2),
					y: +r.y.toFixed(2),
					w: +r.width.toFixed(2),
					h: +r.height.toFixed(2),
					font: s.fontFamily,
					size: s.fontSize,
					radius: s.borderRadius,
					color: s.color,
					bg: s.backgroundColor,
					variant: s.fontVariantNumeric
				};
			})
	);
}

export function report(name, findings) {
	const order = { blocker: 0, major: 1, minor: 2, nit: 3 };
	findings.sort((a, b) => order[a.severity] - order[b.severity]);
	const tally = { blocker: 0, major: 0, minor: 0, nit: 0 };
	for (const f of findings) tally[f.severity]++;
	console.log(`\n### ${name}`);
	console.log(
		`blocker ${tally.blocker} | major ${tally.major} | minor ${tally.minor} | nit ${tally.nit}`
	);
	for (const f of findings) {
		console.log(`[${f.severity}] ${f.what}`);
		console.log(`    bewijs: ${f.evidence}`);
	}
	return tally;
}
