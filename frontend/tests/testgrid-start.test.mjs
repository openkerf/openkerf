import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import { machineDisconnected } from '../src/lib/api.ts';

test('test-grid start rechecks the live connection after its estimate', async () => {
  const source = readFileSync(new URL('../src/lib/components/TestGrid.svelte', import.meta.url), 'utf8');
  const handler = source.match(/async function machineActie\([\s\S]*?\n\t}\n/)?.[0];
  assert.ok(handler);
  const plain = ts.transpileModule(handler, {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText;
  let state = 'connected', posts = 0;
  const fixture = new Function('machineDisconnected', 'fetch', 'tegenhouder', 'device', `
    const t = (key) => key;
    let naarMachine = null, machineError = null;
    ${plain}
    return {run: machineActie, error: () => machineError};
  `)(machineDisconnected, async () => { posts++; return new Response('{}'); },
    async () => { state = 'disconnected'; return null; },
    {get connection() { return {state}; }});
  await fixture.run('/api/job/start', 'start', 'start-ready');
  assert.equal(posts, 0);
  assert.equal(fixture.error(), 'job.notResponding');
  await fixture.run('/api/machine/frame', 'frame', 'frame-ready');
  assert.equal(posts, 1, 'the burn guard does not change other machine actions');
});
