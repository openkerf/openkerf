/** De wachtregel: onzichtbaar op een snelle server, aanwezig op een trage. */
import { chromium } from 'playwright';
const BASE='http://127.0.0.1:8107';
const OUT='/Users/Jelle.Tigchelaar/git/openkerf/screenshots/aaa/eerste-start';
const b = await chromium.launch();

async function proef(vertraging, naam, thema='light') {
  const ctx = await b.newContext({ viewport:{width:1440,height:900}, colorScheme:thema, deviceScaleFactor:1 });
  const page = await ctx.newPage();
  if (thema==='dark') await page.addInitScript(()=>{const z=()=>document.documentElement?.setAttribute('data-theme','dark');z();document.addEventListener('DOMContentLoaded',z);});
  await page.route('**/api/machines', async (r) => {
    await new Promise((k)=>setTimeout(k, vertraging));
    return r.continue();
  });
  await page.goto(BASE+'/', { waitUntil:'domcontentloaded' });
  // Op het moment dat een mens zou kijken: 250 ms (snel) en 900 ms (traag).
  await page.waitForTimeout(vertraging > 500 ? 900 : 250);
  const zicht = await page.evaluate(() => {
    const n = document.querySelector('.wachten');
    if (!n) return { aanwezig:false };
    return { aanwezig:true, opacity:+getComputedStyle(n).opacity, tekst:n.textContent.trim() };
  });
  await page.screenshot({ path:`${OUT}/r11-${naam}-${thema}.png` });
  console.log(naam, thema, JSON.stringify(zicht));
  await ctx.close();
}

await proef(60,  'snel-geen-wachtregel');
await proef(2500,'traag-wachtregel');
await proef(2500,'traag-wachtregel','dark');
await b.close();
