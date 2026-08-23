/**
 * Does the text still fit, in both languages?
 *
 *   node gauntlet/i-overflow.mjs en
 *   node gauntlet/i-overflow.mjs nl
 *
 * Looking at screenshots catches the obvious cases; it does not catch a label that
 * is one pixel too wide and gets an ellipsis, because an ellipsis looks
 * deliberate. So this measures instead: every element that holds text of its own
 * and whose content is wider than its box is reported, with the text in it.
 *
 * Two things are deliberately not failures:
 *
 * - Elements that the design *asks* to clip: the layer name and the job name are
 *   `text-overflow: ellipsis` on purpose, because a name can be any length. They
 *   are listed under `byDesign` so a real regression does not hide in the noise.
 * - A difference of one or two pixels. Sub-pixel text metrics differ per platform
 *   and would make this report unusable.
 *
 * The point of running it per language is the comparison: an element that clips in
 * both is a layout that was already tight, and one that clips only in Dutch is
 * what this round has to fix.
 */
import { chromium } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const language = process.argv[2] ?? 'en';
/** Below this many pixels of overflow it is text metrics, not a layout problem. */
const SLACK = 2;

/** Selectors that clip on purpose, because the content has no known length. */
const BY_DESIGN = [
	'.layer-name',
	// The layer name in the pre-flight table: same rule as the one in the panel —
	// a name has no known length, the cell clips it with an ellipsis and carries the
	// whole thing in its `title`.
	'.pf-name',
	'.current-job',
	'.name',
	'.matname',
	'.title',
	'.machine',
	'.mat',
	// The Series window shows the reader's own spreadsheet: a column name and a cell
	// have no known length at all, and both carry the whole string in their `title`.
	// Without these three a forty-character header makes both language runs dirty on
	// somebody else's file, which is not a fault of the layout.
	'.colname',
	'.cell',
	// What the plate now on the bed engraves, in the run block. Same rule, and the
	// card it sits in is 245 px wide: a long name clips there by design.
	'.seriesRun .engraves'
];

const browser = await chromium.launch();

async function open(path) {
	const context = await browser.newContext({
		viewport: { width: 1440, height: 900 },
		deviceScaleFactor: 1,
		colorScheme: 'light'
	});
	await context.addInitScript(
		(code) => window.localStorage.setItem('openkerf.language', code),
		language
	);
	const page = await context.newPage();
	await page.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 30000 });
	await page.waitForSelector('.statusbar, .setup', { timeout: 20000 }).catch(() => {});
	await page.waitForTimeout(900);
	const later = page.getByRole('button', { name: /^(Later|Not now|Niet nu|Seen|Gezien)$/ });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(300);
	return page;
}

async function measure(page, byDesign) {
	return page.evaluate(
		({ slack, byDesign }) => {
			const out = [];
			for (const el of document.querySelectorAll('body *')) {
				if (!(el instanceof HTMLElement)) continue;
				const style = getComputedStyle(el);
				if (style.display === 'none' || style.visibility === 'hidden') continue;
				// Only elements that hold text of their own: a wrapper is wide because
				// its child is, and reporting both says the same thing twice.
				const own = [...el.childNodes].some(
					(n) => n.nodeType === 3 && (n.textContent ?? '').trim().length > 0
				);
				if (!own) continue;
				// An element of a few pixels wide is not a layout: it is something that is
				// collapsed or measuring itself, and its "overflow" says nothing.
				if (el.clientWidth < 24) continue;
				const overflow = el.scrollWidth - el.clientWidth;
				if (overflow <= slack) continue;
				out.push({
					tag: el.tagName.toLowerCase(),
					cls: el.className?.toString().slice(0, 40) ?? '',
					overflow,
					width: el.clientWidth,
					text: (el.textContent ?? '').trim().slice(0, 60),
					byDesign: byDesign.some((sel) => el.matches(sel))
				});
			}
			return out;
		},
		{ slack: SLACK, byDesign }
	);
}

const IDS = await (async () => {
	const design = await (await fetch(`${BASE}/api/design`)).json();
	return design.elements.map((e) => e.id);
})();

/**
 * Open the Series window, which is where the reader's own spreadsheet is on screen.
 *
 * A dialog has no address of its own, so it needs a hand: this is the only screen in
 * the list that is reached by pressing something. What it shows depends on what the
 * server holds — attach a list with a long column name before running this, or the
 * measurement is about an empty window and says nothing.
 */
async function openSeries(page) {
	const rail = page.locator('button[title^="Series"], button[title^="Serie"]').first();
	if (!(await rail.count())) return;
	await rail.click();
	await page.waitForTimeout(900);
}

const SCREENS = [
	['canvas', '/?tab=design'],
	['selection', `/?tab=design&select=${IDS.slice(0, 3).join(',')}`],
	['layers', '/?tab=layers'],
	['job', '/?tab=job'],
	['series', '/?tab=design', openSeries],
	['setup', '/setup'],
	['setup-kind', '/setup/kind'],
	['setup-model', '/setup/type'],
	['setup-name', '/setup/name?type=ruida'],
	['setup-settings', '/setup/settings?machine=ruida'],
	['setup-done', '/setup/done?machine=ruida']
];

let problems = 0;
for (const [name, path, prepare] of SCREENS) {
	const page = await open(path);
	if (prepare) await prepare(page);
	const found = await measure(page, BY_DESIGN);
	const real = found.filter((f) => !f.byDesign);
	if (found.length !== real.length)
		console.log(
			`${language} · ${name}: ${found.length - real.length} clipped by design (ellipsis)`
		);
	if (real.length) {
		problems += real.length;
		console.log(`\n${language} · ${name}`);
		for (const f of real)
			console.log(`  +${f.overflow}px in ${f.width}px  ${f.tag}.${f.cls}  “${f.text}”`);
	}
	await page.context().close();
}
console.log(`\n${language}: ${problems} element(s) clipped beyond the design's own ellipses`);
await browser.close();
