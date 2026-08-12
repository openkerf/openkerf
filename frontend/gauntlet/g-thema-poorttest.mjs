// Bewijst dat de poort echt dichtgaat: drie nepsituaties, drie luide fouten.
import { chromium } from 'playwright';
import { eisScherm, eisHeleBuild, GeenScherm } from '/Users/Jelle.Tigchelaar/git/openkerf/frontend/gauntlet/g-thema-guard.mjs';
const BASE = process.env.OK_BASE;
let mislukt = 0;
const b = await chromium.launch();
/**
 * @param moetFalen  true = de poort hoort dicht te gaan; false = hij hoort door te laten.
 */
async function proef(naam, moetFalen, bouw, roep) {
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await bouw(page);
  let gefaald = null;
  try { await roep(page); } catch (e) { gefaald = e; }
  const goed = moetFalen ? gefaald instanceof GeenScherm : gefaald === null;
  console.log(' ', goed ? 'GOED  ' : 'FOUT  ', naam.padEnd(32),
    gefaald ? '→ ' + String(gefaald.message).slice(0, 88) : '→ doorgelaten, zoals het hoort');
  if (!goed) mislukt++;
  await ctx.close();
}
await proef('blanco pagina', true, async (p) => { await p.setContent('<body></body>'); }, (p) => eisScherm(p, '.topbar', 'nep'));
await proef('welkomstscherm', true, async (p) => { await p.setContent('<body><div class="welkom">Welkom bij OpenKerf — nog geen machine ingesteld, laten we er een toevoegen.</div></body>'); }, (p) => eisScherm(p, '.topbar', 'nep'));
await proef('kapotte build', true, async (p) => {
  await p.goto(BASE + '/');
  await p.evaluate(() => { const s = document.createElement('script'); s.src = '/_app/immutable/chunks/bestaat-niet.js'; document.head.append(s); });
}, (p) => eisHeleBuild(p));
await proef('echt scherm (moet dóórlaten)', false, async (p) => {
  await p.goto(BASE + '/'); await p.waitForSelector('.topbar', { timeout: 20000 }).catch(()=>{}); await p.waitForTimeout(800);
}, async (p) => { await eisScherm(p, '.topbar', 'echt'); await eisHeleBuild(p); });
await b.close();
console.log(mislukt ? `\n${mislukt} proef(en) mislukt — de poort doet niet wat hij belooft.` : '\nDe poort doet wat hij belooft: drie nepsituaties geblokkeerd, het echte scherm doorgelaten.');
process.exit(mislukt ? 1 : 0);
