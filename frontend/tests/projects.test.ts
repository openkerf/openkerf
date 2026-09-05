/**
 * Projects on the server: the name rule is the server's rule, and the menu is in order.
 *
 * The name rule lives twice — `projects.svelte.ts:cleanName` and
 * `openkerf_api/projects.py:clean_name` — so the two are run against each other, the
 * way `upload-name.test.ts` does for the machine name. Without a Python the comparison
 * is skipped, not faked.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { cleanName } from '../src/lib/projects.svelte.ts';
import { projectActions, KEYS, type Context, type Handlers } from '../src/lib/actions.ts';

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = join(here, '..', '..');

const NAMES = ['  Kastje groot ', 'a/b', '../etc', '.hidden', 'naïve', 'x'.repeat(80), '   ', 'box_1-2.v3', 'Doos: nr. 1?'];

test('the name rule on the screen', () => {
	assert.equal(cleanName('  Kastje groot '), 'Kastje groot');
	assert.equal(cleanName('a/b'), 'ab');
	assert.equal(cleanName('.hidden'), 'hidden');
	assert.equal(cleanName('x'.repeat(80)).length, 60);
	assert.equal(cleanName('   '), '');
});

test('the screen and the server cut a project name the same way', (t) => {
	const python = join(ROOT, 'meerk40t', '.venv-nogui', 'bin', 'python');
	if (!existsSync(python)) {
		if (process.env.OK_REQUIRE_PYTHON) assert.fail(`no interpreter at ${python} and OK_REQUIRE_PYTHON is set`);
		return t.skip(`no interpreter at ${python}; the first test still holds`);
	}
	const script =
		'import json,sys;sys.path.insert(0,"api");' +
		'from openkerf_api.projects import clean_name;' +
		'print(json.dumps([clean_name(n) for n in json.loads(sys.argv[1])]))';
	const theirs = JSON.parse(execFileSync(python, ['-c', script, JSON.stringify(NAMES)], { cwd: ROOT, encoding: 'utf8' }));
	assert.deepEqual(NAMES.map(cleanName), theirs);
});

const CTX = {
	count: 0, inGroup: false, lockedCount: 0, isImage: false, isText: false, isCropped: false, filled: false,
	bridges: { carries: false, has: false }, clipboard: 0, busy: false, offline: false, may: true,
	layers: [], sheets: [], snap: true, layerNumbers: false, empty: false,
	splittable: { shapes: 0, pieces: 0 }, under: [], columns: [], once: false
} as unknown as Context;
const H = new Proxy({}, { get: () => () => {} }) as Handlers;

test('the project menu is in order and its verbs carry their shortcuts', () => {
	const ids = projectActions(CTX, H).map((a) => a.id);
	assert.deepEqual(ids, ['project.new', 'project.open', 'project.save', 'project.saveAs', 'project.download', 'project.upload']);
	assert.equal(KEYS.open, 'mod+o');
	assert.equal(KEYS.save, 'mod+s');
	assert.equal(KEYS.saveAs, 'mod+shift+s');
});

test('without a token every project verb that writes says why', () => {
	const off = projectActions({ ...CTX, may: false }, H);
	for (const a of off) {
		if (a.id === 'project.download') assert.equal(a.off, undefined, 'downloading only reads');
		else assert.ok(a.off, `${a.id} is silent about the missing token`);
	}
});
