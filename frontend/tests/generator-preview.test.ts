/** Real preview request/action functions, no browser, server or machine. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../src/lib/components/Generators.svelte', import.meta.url), 'utf8');
const request = source.slice(source.indexOf('async function haalVoorbeeld('), source.indexOf('\n\tlet timer:'));
const run = source.slice(source.indexOf('async function run('), source.indexOf('\n\tconst n ='));
const blocked = source.match(/let actionBlocked = \$derived\(([\s\S]*?)\);/)![1];

test('invalid preview blocks placement, finishes loading and valid input recovers', async () => {
 let calls = 0;
 let valid = false;
 const context = vm.createContext({
  round: 1, selectedIds: [], previewPending: true, previewError: null, preview: null,
  busy: false, blocked: false, voorbeeldbaar: true, unfinished: false,
  t: (key: string) => key, apiError: () => 'localized refusal',
  fetch: async () => ({ ok: valid, headers: new Headers({ 'X-OpenKerf-Error': 'gen.badBarcode' }), json: async () => valid ? { what: 'barcode' } : { detail: 'raw engine exception' } }),
  onGenerate: async () => { calls++; return {}; }, tab: 'barcode', notice: null, error: null, open: true
 });
 const compiled = ts.transpileModule(request + '\n' + run, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
 vm.runInContext(compiled, context);
 const updateBlocked = () => vm.runInContext('actionBlocked = (' + blocked + ')', context);
 await vm.runInContext('haalVoorbeeld(1, "barcode", {})', context);
 assert.equal(context.previewPending, false);
 assert.equal(context.previewError, 'gen.barcode.invalid');
 assert.equal(updateBlocked(), true);
 await vm.runInContext('run({})', context);
 assert.equal(calls, 0);
 valid = true;
 context.previewPending = true;
 assert.equal(updateBlocked(), true);
 await vm.runInContext('haalVoorbeeld(1, "barcode", {})', context);
 assert.equal(context.previewError, null);
 assert.equal(updateBlocked(), false);
 await vm.runInContext('run({})', context);
 assert.equal(calls, 1);
 // A stale response must not release the latest request's pending state.
 context.round = 2;
 context.previewPending = true;
 await vm.runInContext('haalVoorbeeld(1, "barcode", {})', context);
 assert.equal(context.previewPending, true);
});
