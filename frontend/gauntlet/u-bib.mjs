/** De bibliotheek: overzicht, één materiaal gekozen, en het rijmenu. */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.env.OK_BASE ?? 'http://localhost:8090';
const ronde = process.argv[2] ?? 'na';
const OUT = `/Users/Jelle.Tigchelaar/git/openkerf/screenshots/usability/${ronde}`;
mkdirSync(OUT, { recursive: true });
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
const page = await ctx.newPage();
const fouten = [];
page.on('pageerror', (e) => fouten.push(String(e).slice(0, 140)));
page.on('console', (m) => m.type() === 'error' && fouten.push(m.text().slice(0, 140)));
await page.goto(BASE + '/?tab=layers', { waitUntil: 'domcontentloaded' });
await page.waitForSelector('.statusbar').catch(() => {});
await page.waitForTimeout(900);
const later = page.getByRole('button', { name: /^Later$/ });
if (await later.count()) await later.first().click().catch(() => {});
await page.click('button[title="Materiaalbibliotheek"]');
await page.waitForTimeout(900);
await page.screenshot({ path: `${OUT}/30-bib-overzicht.png` });

// Een materiaal met meer diktes kiezen: dan verschijnen de diktechips.
await page.getByRole('button', { name: /Berkentriplex/ }).first().click();
await page.waitForTimeout(600);
await page.screenshot({ path: `${OUT}/31-bib-materiaal.png` });

// Het menu op een instelling.
const meer = page.locator('.preset .meer').first();
await meer.click();
await page.waitForTimeout(450);
await page.screenshot({ path: `${OUT}/32-bib-rijmenu.png` });
await page.keyboard.press('Escape');
await page.waitForTimeout(250);

// Herkomst open.
await page.locator('.preset .meer').first().click();
await page.waitForTimeout(350);
const herk = page.getByRole('menuitemcheckbox', { name: /Herkomst/ });
if (await herk.count()) { await herk.first().click(); await page.waitForTimeout(600); }
await page.screenshot({ path: `${OUT}/33-bib-herkomst.png` });
console.log('fouten:', fouten.slice(0, 5));
await b.close();
