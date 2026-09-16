import assert from 'node:assert/strict';
import test from 'node:test';
import { scratchFetch } from './scratch.mjs';

test('refuses real port and invalid marker before any mutation', async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options?.method ?? 'GET']);
    return Response.json({ marker: 'wrong' });
  };
  await assert.rejects(scratchFetch('http://127.0.0.1:8080/api/project/new', {method: 'POST'}));
  assert.equal(calls.length, 0);
  await assert.rejects(scratchFetch('http://127.0.0.1:8092/api/project/new', {method: 'POST'}));
  assert.deepEqual(calls.map(c => c[1]), ['GET']);
  calls.length = 0;
  globalThis.fetch = async (url, options) => {
    calls.push([url, options?.method ?? 'GET']);
    return options?.method === 'POST' ? new Response('failure', { status: 500 }) :
      Response.json({marker: 'openkerf-gauntlet-v1', isolated: true, hardware: false});
  };
  await assert.rejects(scratchFetch('http://localhost:8092/api/project/new', {method: 'POST'}), /500/);
  assert.deepEqual(calls.map(c => c[1]), ['GET', 'POST']);
});
