import { chromium } from 'playwright';
const BASE = 'http://127.0.0.1:8107';
const OUT = '/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/eerste-start';
const b = await chromium.launch();
for (const thema of ['light','dark']) {
  const ctx = await b.newContext({ viewport:{width:1440,height:900}, colorScheme: thema, deviceScaleFactor:1 });
  const page = await ctx.newPage();
  const extern = [], fouten = [];
  // Alles blokkeren wat niet van onze eigen server komt.
  await page.route('**/*', (r) => {
    const u = r.request().url();
    if (u.startsWith(BASE) || u.startsWith('data:') || u.startsWith('blob:')) return r.continue();
    extern.push(u); return r.abort();
  });
  page.on('console', (m) => { if (m.type()==='error') fouten.push(m.text().slice(0,120)); });
  page.on('pageerror', (e) => fouten.push('pageerror: '+String(e).slice(0,120)));
  if (thema==='dark') await page.addInitScript(() => {
    const z=()=>document.documentElement?.setAttribute('data-theme','dark');
    z(); document.addEventListener('DOMContentLoaded',z);
  });
  await page.goto(BASE+'/', { waitUntil:'domcontentloaded' });
  await page.waitForSelector('.kaart', { timeout:15000 });
  await page.waitForTimeout(900);
  const fonts = await page.evaluate(async () => {
    await document.fonts.ready;
    const set = [...document.fonts].map(f => `${f.family} ${f.weight} ${f.status}`);
    const body = getComputedStyle(document.body).fontFamily;
    const mono = document.querySelector('.mono, .nummer');
    return { aantal: set.length, geladen: set.filter(s=>s.endsWith('loaded')).length,
             body: body.split(',')[0], monoEl: mono ? getComputedStyle(mono).fontFamily.split(',')[0] : null };
  });
  await page.screenshot({ path: `${OUT}/r11-offline-welkom-${thema}.png` });
  console.log(thema, JSON.stringify({ extern: extern.length, fouten, ...fonts }));
  await ctx.close();
}
await b.close();
