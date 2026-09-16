import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type WebSocketRoute } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';

test('Job starts quiet; machine setup unfolds without issuing commands', async (t) => {
  if (!await fetch(BASE).then(r => r.ok).catch(() => false)) return noServer(t, BASE);
  const browser = await chromium.launch();
  try {
    const snapshot = await (await fetch(`${BASE}/api/status`)).json();
    for (const language of ['en', 'nl']) for (const [width, height] of [[1440, 900], [1366, 768], [1024, 768]]) {
      const page = await browser.newPage({ viewport: { width, height } });
      await page.addInitScript((language) => {
        localStorage.setItem('openkerf.token', 'ui-review');
        localStorage.setItem('openkerf.language', language);
      }, language);
      let socket: WebSocketRoute;
      await page.routeWebSocket('**/api/ws', ws => {
        socket = ws;
        ws.send(JSON.stringify({ type: 'snapshot', data: snapshot }));
      });
      await page.route('**/api/capabilities', async route => {
        const response = await route.fetch();
        const body = await response.json();
        body.adjust = { power: true, speed: true };
        await route.fulfill({ response, json: body });
      });
      await page.route('**/api/job/adjust', route => route.fulfill({ json: { power: 0.5, speed: null } }));
      const moves: string[] = [];
      await page.route('**/api/machine/**', async route => {
        if (route.request().method() !== 'GET') {
          moves.push(route.request().url());
          await route.abort();
        } else await route.continue();
      });
      await page.goto(`${BASE}/?tab=job`);
      const explore = page.getByRole('button', { name: language === 'en' ? 'Look around without a machine' : 'Rondkijken zonder machine', exact: true });
      await explore.or(page.locator('details.machinevouw')).waitFor({ state: 'visible' });
      if (await explore.isVisible()) await explore.click();
      const machine = page.locator('details.machinevouw');
      await machine.waitFor({ state: 'visible' });
      assert.equal(await machine.evaluate(el => (el as HTMLDetailsElement).open), false);
      await page.locator('.adjust-status').waitFor({ state: 'visible' });
      assert.match(await page.locator('.adjust-status').innerText(), /50%/);
      assert.equal(await page.locator('.adjust-status > div').count(), 1, 'unread speed is not an override');
      const start = page.locator('.pf-split > button').first();
      await start.waitFor({ state: 'visible' });
      assert.ok(await start.evaluate(el => {
        const r = el.getBoundingClientRect();
        const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return hit === el || el.contains(hit);
      }), 'the start button must not be covered');
      await machine.locator(':scope > summary').focus();
      await page.keyboard.press('Enter');
      await page.locator('.pad').waitFor({ state: 'visible' });
      const folds = machine.locator('details.machine-group');
      await machine.locator('details.origin:not(.printcut)').waitFor({ state: 'visible' });
      assert.ok(await folds.count() >= 3);
      assert.equal(await folds.locator(':scope > summary').count(), await folds.count());
      const origin = machine.locator('details.origin:not(.printcut)');
      assert.equal(await origin.evaluate(el => (el as HTMLDetailsElement).open), false);
      await origin.locator(':scope > summary').click();
      assert.equal(await origin.evaluate(el => (el as HTMLDetailsElement).open), true);
      const overflow = await page.locator('.panel').evaluate(el => el.scrollWidth > el.clientWidth);
      assert.equal(overflow, false);
      const active = structuredClone(snapshot);
      active.devices[0].spooler.jobs = [{ label: 'UI test', running: true, progress: 0.2, steps_done: 2, steps_total: 10, loops: 1, loops_executed: 0, elapsed_seconds: 2, estimate_seconds: 10 }];
      active.devices[0].spooler.idle = false;
      socket!.send(JSON.stringify({ type: 'snapshot', data: active }));
      await page.waitForFunction(() => !(document.querySelector('.machinevouw') as HTMLDetailsElement).open);
      assert.ok(await page.locator('.now .btn.danger').isVisible(), 'stop stays visible during work');
      socket!.send(JSON.stringify({ type: 'snapshot', data: snapshot }));
      await page.locator('.preflight').waitFor({ state: 'visible' });
      assert.equal(await machine.evaluate(el => (el as HTMLDetailsElement).open), false);
      assert.deepEqual(moves, [], 'opening setup must never move or configure the machine');
      await page.close();
    }
  } finally { await browser.close(); }
});
