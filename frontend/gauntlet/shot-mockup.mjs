import { chromium } from 'playwright';
const [bestand, uit, breedte] = process.argv.slice(2);
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: Number(breedte), height: 900 } });
await p.goto('file://' + bestand, { waitUntil: 'networkidle' });
await p.screenshot({ path: uit, fullPage: true });
await b.close();
