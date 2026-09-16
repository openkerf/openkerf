export const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8092';

export async function assertScratch(base = BASE) {
  const url = new URL(base);
  if (!['127.0.0.1', 'localhost'].includes(url.hostname) || url.port !== '8092' || url.protocol !== 'http:') {
    throw new Error('Gauntlet requires the localhost:8092 scratch server');
  }
  const response = await globalThis.fetch(`${url.origin}/api/gauntlet`, {redirect: 'error'});
  const marker = response.ok ? await response.json() : null;
  if (marker?.marker !== 'openkerf-gauntlet-v1' || marker.isolated !== true || marker.hardware !== false) {
    throw new Error('Refusing server without the isolated, hardware-free gauntlet marker');
  }
}

export async function scratchFetch(url, options = {}) {
  await assertScratch(url);
  const response = await globalThis.fetch(url, {...options, redirect: 'error'});
  if (!response.ok) throw new Error(`${options.method ?? 'GET'} ${url}: ${response.status} ${(await response.text()).slice(0, 160)}`);
  return response;
}
