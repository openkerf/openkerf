/**
 * The screenshot set for the multilingual round: every screen in both languages.
 *
 *   node gauntlet/i-shots.mjs en
 *   node gauntlet/i-shots.mjs nl
 *
 * Why both and not just the new one: English is usually shorter than Dutch, but
 * not always ("Show frame" is longer than "Kader"), and a label that fits in one
 * language and clips in the other is exactly the failure this round has to catch.
 * The overflow measurement in `i-overflow.mjs` does the counting; these are for
 * looking.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const language = process.argv[2] ?? 'en';
const only = process.argv[3] ?? null;
const OUT = `/Users/Jelle.Tigchelaar/git/openkerf/screenshots/i18n/${language}`;
mkdirSync(OUT, { recursive: true });

async function ids() {
	const design = await (await fetch(`${BASE}/api/design`)).json();
	return design.elements.map((e) => e.id);
}
const ELS = await ids();

const browser = await chromium.launch();

async function open(path = '/') {
	const context = await browser.newContext({
		viewport: { width: 1440, height: 900 },
		deviceScaleFactor: 1,
		colorScheme: 'light'
	});
	// The language is a stored choice, so it is set before the app boots — no
	// switching mid-render, which would photograph a half-translated screen.
	await context.addInitScript(
		(code) => window.localStorage.setItem('openkerf.language', code),
		language
	);
	const page = await context.newPage();
	const problems = [];
	page.on('console', (m) => m.type() === 'error' && problems.push(m.text().slice(0, 160)));
	page.on('pageerror', (e) => problems.push('pageerror: ' + String(e).slice(0, 160)));
	await page.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 30000 });
	await page.waitForSelector('.statusbar, .setup', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(900);
	const later = page.getByRole('button', { name: /^(Later|Not now)$/ });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(300);
	page.problems = problems;
	return page;
}

// The tool rail is the way into most of these windows, and its buttons carry a
// translated title. So they are found by a pattern that covers both languages, or
// by position where the position is what is stable: the library is the last button
// in the rail, in either language.
const RAIL = '.rail button:not([disabled])';

const SCREENS = [
	['01-canvas', '/?tab=design', null],
	['02-selection', `/?tab=design&select=${ELS.slice(0, 3).join(',')}`, null],
	['03-layers', '/?tab=layers', null],
	['04-job', '/?tab=job', null],
	[
		'05-object-menu',
		`/?tab=design&select=${ELS.slice(0, 3).join(',')}`,
		async (page) => {
			const box = await page.locator('.grab').first().boundingBox();
			if (box)
				await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2, { button: 'right' });
			await page.waitForTimeout(400);
		}
	],
	[
		'06-canvas-menu',
		'/?tab=design',
		async (page) => {
			await page.mouse.click(700, 600, { button: 'right' });
			await page.waitForTimeout(400);
		}
	],
	[
		'07-library',
		'/',
		async (page) => {
			await page.locator(RAIL).last().click().catch(() => {});
			await page.waitForTimeout(1400);
		}
	],
	[
		'08-testgrid',
		'/',
		async (page) => {
			await page
				.locator(RAIL, { has: undefined })
				.filter({ hasNot: page.locator('nothing') })
				.nth(-1);
			await page
				.locator(`${RAIL}[title*="est"]`)
				.first()
				.click()
				.catch(() => {});
			await page.waitForTimeout(1400);
		}
	],
	[
		'09-generators',
		'/',
		async (page) => {
			await page
				.locator(`${RAIL}[title*="enerator"]`)
				.first()
				.click()
				.catch(() => {});
			await page.waitForTimeout(900);
		}
	],
	[
		'10-text',
		'/',
		async (page) => {
			await page
				.locator(`${RAIL}[title*="ext"], ${RAIL}[title*="ekst"]`)
				.first()
				.click()
				.catch(() => {});
			await page.mouse.click(600, 420);
			await page.waitForTimeout(900);
		}
	],
	['11-setup', '/setup', null],
	[
		'12-language',
		'/?tab=design',
		async (page) => {
			await page.locator('.language').first().click().catch(() => {});
			await page.waitForTimeout(400);
		}
	]
];

const log = [];
for (const [name, path, step] of SCREENS) {
	if (only && !name.includes(only)) continue;
	const page = await open(path);
	if (step) await step(page);
	await page.waitForTimeout(500);
	await page.screenshot({ path: `${OUT}/${name}.png` });
	const panel = page.locator('.panel-scroll').first();
	if (await panel.count())
		await panel.screenshot({ path: `${OUT}/${name}-panel.png` }).catch(() => {});
	log.push({ name, problems: page.problems.length });
	if (page.problems.length) console.log('  !', name, page.problems.slice(0, 2));
	await page.context().close();
}
console.table(log);
await browser.close();
