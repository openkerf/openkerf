/**
 * Wat elke start-, pauze- en stopknop zegt, in elke jobtoestand.
 *
 * Drie oppervlakken bieden dezelfde handelingen aan (bovenbalk, statusbalk,
 * Job-paneel). Dit leest per toestand af of ze het met elkaar eens zijn — want
 * een startknop die op de ene plek kan en op de andere niet, is erger dan een
 * knop die overal uit staat.
 */
import { chromium } from 'playwright';

const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const post = (p) =>
	fetch(BASE + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
const page = await ctx.newPage();

async function lees(toestand) {
	await page.goto(BASE + '/?tab=job', { waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.statusbar').catch(() => {});
	await page.waitForTimeout(1400);
	const later = page.getByRole('button', { name: /^Later$/ });
	if (await later.count()) await later.first().click().catch(() => {});
	await page.waitForTimeout(400);
	const stand = async (waar, naam) => {
		const l = page.locator(waar).getByRole('button', { name: naam });
		if (!(await l.count())) return '—';
		return (await l.first().isDisabled()) ? 'uit' : 'aan';
	};
	return {
		toestand,
		'start·balk': await stand('.topbar', /start/i),
		'start·paneel': await stand('.panel', /^Job starten/),
		'pauze·balk': await stand('.topbar', /pauze|hervat/i),
		'pauze·paneel': await stand('.panel', /^Pauze$|^Hervatten$/),
		'stop·balk': await stand('.topbar', /^Stop$/),
		'stop·paneel': await stand('.panel', /^Stop$/),
		'pauze·statusbalk': await stand('.statusbar', /^Pauze$|^Hervatten$/),
		'stop·statusbalk': await stand('.statusbar', /^Stop$/),
		voortgang: (await page.locator('.statusbar').first().textContent())?.slice(0, 40).trim()
	};
}

const rijen = [];
await post('/api/job/stop');
await post('/api/spooler/clear');
await new Promise((r) => setTimeout(r, 900));
rijen.push(await lees('stil'));

await post('/api/job/start');
await new Promise((r) => setTimeout(r, 2200));
rijen.push(await lees('loopt'));

await post('/api/job/pause');
await new Promise((r) => setTimeout(r, 1200));
rijen.push(await lees('pauze'));

await post('/api/job/stop');
await post('/api/spooler/clear');
console.table(rijen);
await b.close();
