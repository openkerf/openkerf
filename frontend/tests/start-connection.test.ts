/** Run with node --test frontend/tests/start-connection.test.ts. No server or hardware. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { compileModule } from 'svelte/compiler';
import ts from 'typescript';
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));

test('Controller reads the current device at each start and never sends while disconnected', async () => {
	const work = join(here, '.start-connection-tmp');
	mkdirSync(work, { recursive: true });
	const source = readFileSync(join(here, '../src/lib/control.svelte.ts'), 'utf8')
		.replace("from './i18n/core.ts'", "from '../../src/lib/i18n/core.ts'")
		.replace("from './api'", "from '../../src/lib/api.ts'")
		.replace("import { connection } from './connection.svelte';", 'const connection = { online: true };');
	const plain = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
	const compiled = compileModule(plain, { generate: 'server', filename: 'control.svelte.js' });
	const file = join(work, 'control.js');
	writeFileSync(file, compiled.js.code);
	const originalFetch = globalThis.fetch;
	try {
		const { Controller } = await import(file);
		let state = 'disconnected';
		const control = new Controller(() => ({ connection: { state } }));
		let requests = 0;
		globalThis.fetch = async (path) => {
			assert.equal(path, '/api/job/start');
			requests++;
			return new Response('{}', { status: 200 });
		};
		assert.equal(await control.start(), false);
		assert.equal(requests, 0);
		assert.ok(control.error);
		state = 'unknown';
		assert.notEqual(await control.start(), false);
		assert.equal(requests, 1);
		state = 'connected';
		assert.notEqual(await control.start(), false);
		assert.equal(requests, 2);
		state = 'disconnected';
		assert.equal(await control.start(), false);
		assert.equal(requests, 2);
	} finally {
		globalThis.fetch = originalFetch;
		rmSync(work, { recursive: true, force: true });
	}
});
