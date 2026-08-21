import { chromium } from 'playwright';
const BASE = process.env.OK_BASE;
const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/testraster';
const ronde = process.argv[2] ?? 'r5';
const hoeken = [
  { x: 14/66, y: 14/66 }, { x: 52/66, y: 14/66 },
  { x: (52+1.8)/66, y: 52/66 }, { x: (14+1.8)/66, y: 52/66 }
];
const b = await chromium.launch();
for (const [naam, width] of [['desktop',1440],['tablet',1024]]) {
for (const theme of ['light','dark']) {
  const ctx = await b.newContext({ viewport:{width,height:900}, deviceScaleFactor:1, colorScheme: theme });
  const page = await ctx.newPage();
  await page.addInitScript(([h, t]) => {
    localStorage.setItem('openkerf.raster.uitlijning.1', JSON.stringify(h));
    if (t === 'dark') {
      const set = () => document.documentElement?.setAttribute('data-theme','dark');
      set(); document.addEventListener('DOMContentLoaded', set);
    }
  }, [hoeken, theme]);
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.statusbar', { timeout: 20000 }).catch(()=>{});
  await page.waitForTimeout(900);
  const later = page.getByRole('button', { name: /later/i });
  if (await later.count()) await later.first().click().catch(()=>{});
  const knop = page.locator('button[title="Testraster"]');
  if (!(await knop.first().isVisible().catch(()=>false))) {
    await page.locator('button[title="Meer gereedschap"]').first().click().catch(()=>{});
    await page.waitForTimeout(300);
  }
  await knop.first().click();
  await page.waitForTimeout(1000);
  const picker = page.locator('select.picker');
  await picker.first().selectOption({ index: await picker.locator('option',{hasText:'met foto'}).first().evaluate(o=>o.index) });
  await page.waitForTimeout(800);
  await page.locator('.podium').first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  const cel = page.locator('.podium svg polygon').nth(3);
  await cel.hover(); await page.waitForTimeout(150);
  await cel.click(); await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/${ronde}-${naam}-${theme}-uitgelijnd-gekozen.png` });
  await ctx.close();
}}
await b.close();
console.log('klaar');
