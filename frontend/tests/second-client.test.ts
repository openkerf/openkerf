/**
 * Another program on the same controller is said on screen, not suffered.
 *
 * Run: `node --test frontend/tests/second-client.test.ts`
 *
 * Measured on a KH-5030 on 11 October: with a second program polling the controller,
 * ~40 % of our reads were acknowledged and never answered, while the line read
 * "connected" throughout. The server now adds `connection.warning`
 * (`api/openkerf_api/ruida/monitor.py`, `SecondClient`); this guards that the field
 * reaches a sentence, in the reader's language, and that the status bar renders it.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import * as api from '../src/lib/api.ts';
import type { Device } from '../src/lib/api.ts';
import { bindLanguage } from '../src/lib/i18n/core.ts';

const here = dirname(fileURLToPath(import.meta.url));

const WARNING = {
	code: 'ruida.secondClient',
	message:
		"Another program seems to be talking to this Ruida: 8 of the last 20 status questions were acknowledged but not answered. Close the other program — two programs on one controller lose each other's answers.",
	unanswered: 8,
	asked: 20,
	ack_ms: 1250
};

function device(connection: Device['connection']): Device {
	return {
		label: 'Ruida', path: 'ruida', active: true, laser_status: 'idle', paused: false,
		bed: { width_mm: 500, height_mm: 300 },
		position: { native: [0, 0], mm: [0, 0], state: ['idle', 'idle'] },
		spooler: { present: true, idle: true, queue_length: 0, jobs: [] },
		connection
	} as Device;
}

test('no warning, no sentence', () => {
	assert.equal(api.connectionWarning(device({ state: 'connected', detail: null }), true), null);
	assert.equal(api.connectionWarning(null, true), null);
});

test('a second client is said in English, numbers through Intl', () => {
	bindLanguage(() => 'en');
	const said = api.connectionWarning(
		device({ state: 'connected', detail: null, held_ms: 0, warning: WARNING }), true);
	assert.ok(said);
	assert.equal(said.title, 'Another program seems to be talking to this laser');
	assert.match(said.body, /^8 of the last 20 status questions were acknowledged/);
	assert.match(said.ack ?? '', /1,250 ms/);
});

test('and in Dutch', () => {
	bindLanguage(() => 'nl');
	try {
		const said = api.connectionWarning(
			device({ state: 'connected', detail: null, warning: WARNING }), true);
		assert.ok(said);
		assert.match(said.body, /^Van de laatste 20 statusvragen zijn er 8 bevestigd/);
		assert.match(said.ack ?? '', /1\.250 ms/);
	} finally {
		bindLanguage(() => 'en');
	}
});

test('an unknown code keeps the server sentence; a line that is down says nothing extra', () => {
	const other = { code: 'ruida.somethingNew', message: 'Something new happened.' };
	assert.deepEqual(
		api.connectionWarning(device({ state: 'connected', detail: null, warning: other }), true),
		{ title: null, body: 'Something new happened.', ack: null });
	assert.equal(
		api.connectionWarning(device({ state: 'disconnected', detail: null, warning: WARNING }), true),
		null);
	assert.equal(
		api.connectionWarning(device({ state: 'connected', detail: null, warning: WARNING }), false),
		null);
});

test('the status bar renders it', () => {
	const bar = readFileSync(join(here, '..', 'src', 'lib', 'components', 'StatusBar.svelte'), 'utf8');
	assert.match(bar, /connectionWarning\(device, connected\)/);
	assert.match(bar, /\{waarschuwing\.body\}/);
	assert.match(bar, /status\.machine\.connectedShared/);
});
