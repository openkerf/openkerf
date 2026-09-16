import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EditController } from '../src/lib/edits.svelte.ts';

test('stencil preview reports locally while ordinary execution keeps global failures', async () => {
  const oldFetch = globalThis.fetch;
  const oldState = globalThis.$state;
  globalThis.$state = (value) => value;
  globalThis.fetch = async () => new Response(JSON.stringify({detail: 'No islands.'}), {status: 409});
  try {
    const edits = new EditController(() => '');
    edits.error = 'An unrelated error';
    let local;
    assert.equal(await edits.stencil(['shape'], 3, 2, true, (message) => { local = message; }), null);
    assert.equal(local, 'No islands.');
    assert.equal(edits.error, 'An unrelated error');
    await edits.stencil(['shape'], 3, 2);
    assert.equal(edits.error, 'No islands.');
  } finally {
    globalThis.fetch = oldFetch;
    globalThis.$state = oldState;
  }
});

import { readFileSync } from 'node:fs';

test('only the latest stencil preview may change the local result', async () => {
  const page = readFileSync(new URL('../src/routes/+page.svelte', import.meta.url), 'utf8');
  const handler = page.match(/onLook=\{(async \(bridgeMm, perIsland\) => \{[\s\S]*?)\}\n\tonApply=/)?.[1];
  assert.ok(handler, 'the actual preview handler is available to exercise');
  const requests = [];
  const edits = { stencil: (...args) => new Promise((resolve) => {
    args[4](null);
    requests.push({ resolve, report: args[4] });
  }) };
  const fixture = new Function('edits', `
    const design = {selectedIds: ['shape']};
    let stencilPreviewRound = 0, stencilOpen = true, stencilReport = null, stencilError = null;
    return { look: ${handler}, state: () => ({stencilReport, stencilError}), close: () => {stencilOpen = false;} };
  `)(edits);
  const first = fixture.look(3, 2), second = fixture.look(4, 2);
  requests[0].report('Old refusal'); requests[0].resolve(null);
  await first;
  requests[1].resolve({bridges: 2}); await second;
  assert.deepEqual(fixture.state(), {stencilReport: {bridges: 2}, stencilError: null});
  const third = fixture.look(5, 2), fourth = fixture.look(6, 2);
  requests[3].report('Current refusal'); requests[3].resolve(null); await fourth;
  requests[2].resolve({bridges: 99}); await third;
  assert.deepEqual(fixture.state(), {stencilReport: null, stencilError: 'Current refusal'});
  const last = fixture.look(7, 2); fixture.close();
  requests[4].report('Closed'); requests[4].resolve({bridges: 99}); await last;
  assert.deepEqual(fixture.state(), {stencilReport: null, stencilError: null});
});
