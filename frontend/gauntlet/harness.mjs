/**
 * Tools for the gauntlet.
 *
 * Findings need evidence, so we measure in the browser instead of looking:
 * sizes, computed styles and times. Screenshots are the archive, the
 * measurements are the argument.
 */
import { chromium } from 'playwright';

export const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8090';
export const WIDTHS = { desktop: 1440, tablet: 1024, phone: 390 };

export async function browser() {
	return chromium.launch();
}

/**
 * A clean slate for a critic.
 *
 * Without this the recovery dialog from a previous measurement lies over the
 * screen and you measure through a modal — that cost me a round before I
 * noticed.
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
	// Set the theme before anything is drawn. Switching afterwards means
	// measuring during the transition, and then you read mixed colours halfway —
	// which produced "contrast faults" that went away by themselves after a
	// second.
	if (theme === 'dark') {
		await page.addInitScript(() => {
			// An init script runs before <html> exists; documentElement is null
			// then and setAttribute throws.
			const set = () => document.documentElement?.setAttribute('data-theme', 'dark');
			set();
			document.addEventListener('DOMContentLoaded', set);
		});
	}
	const problems = [];
	page.on('console', (m) => {
		if (m.type() === 'error') problems.push(m.text().slice(0, 160));
	});
	page.on('pageerror', (e) => problems.push(`pageerror: ${String(e).slice(0, 160)}`));
	await page.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 30000 });
	// Do not wait for networkidle: the status connection stays open, so that
	// state never arrives. Wait until the app itself has drawn.
	await page.waitForSelector('.statusbar, .setup', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(700);
	page.problems = problems;
	return page;
}

/** Every visible element with its box and a few styles. */
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
		console.log(`    evidence: ${f.evidence}`);
	}
	return tally;
}
