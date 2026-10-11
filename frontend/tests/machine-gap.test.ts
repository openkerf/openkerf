import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as api from '../src/lib/api.ts';
import type { Device, Job } from '../src/lib/api.ts';

function device(over: Partial<Device> = {}): Device {
  return {
    label: 'Ruida', path: 'ruida', active: true, laser_status: 'idle', paused: false,
    bed: { width_mm: 500, height_mm: 300 },
    position: { native: [0, 0], mm: [0, 0], state: ['idle', 'idle'] },
    spooler: { present: true, idle: true, queue_length: 0, jobs: [] },
    connection: { state: 'connected', detail: null, held_ms: 0 }, ...over
  };
}

for (const held_ms of [0, 4000, 60000]) {
  test(`a disconnected controller is reported immediately at ${held_ms} ms`, () => {
    const d = device({ connection: { state: 'disconnected', detail: null, held_ms } });
    assert.equal(api.machineState(d, true), 'unplugged');
    assert.equal(api.machineState({ ...d, paused: true }, true), 'unplugged');
    assert.equal(api.machineState({ ...d, spooler: { ...d.spooler, idle: false } }, true), 'unplugged');
  });
}

test('unknown connectivity is never Ready, including with a local job', () => {
  const d = device({ connection: { state: 'unknown', detail: null } });
  assert.equal(api.machineState(d, true), 'unknown');
  assert.equal(api.machineState({ ...d, laser_status: 'active' }, true), 'unknown');
  assert.equal(api.machineState(device({ connection: undefined }), true), 'unknown');
});

test('server loss and connected machine activity remain distinct', () => {
  assert.equal(api.machineState(device(), false), 'offline');
  assert.equal(api.machineState(null, true), 'offline');
  assert.equal(api.machineState(device(), true), 'ready');
  assert.equal(api.machineState(device({ paused: true }), true), 'paused');
  assert.equal(api.machineState(device({ laser_status: 'active' }), true), 'busy');
});

test('job phase and stop availability survive controller loss', () => {
  const job = { running: true, paused: true, progress: 0.5 } as Job;
  const d = device({ paused: true, connection: { state: 'disconnected', detail: null } });
  assert.equal(api.machineState(d, true), 'unplugged');
  const phase = api.jobPhase(d, job, false);
  assert.equal(phase, 'paused');
  assert.equal(api.transportAllowed('stop', { able: { stop: true, pause: true, resume: true }, phase, blocked: false }), true);
});

test('driver-confirmed pause remains a job state even when disconnected', () => {
  const job = { running: true, paused: false, progress: 0.5 } as Job;
  for (const pause of [{ paused: true }, { laser_status: 'pause' }, { laser_status: 'paused' }]) {
    const d = device({ ...pause, connection: { state: 'disconnected', detail: null } });
    assert.equal(api.machineState(d, true), 'unplugged');
    assert.equal(api.jobPhase(d, job, false), 'paused');
  }
});

/**
 * A finished job and the machine chip agree.
 *
 * The engine leaves a finished job in the queue at progress 0.998 (CLAUDE.md, "A job
 * never reaches 100%"). `isStalled` read that as started-but-standing-still, so the top
 * bar said "Paused" beside a job card saying "Done 100%" — and without that, a job in the
 * queue would have made the chip say "Busy". Both now read `isFinished`.
 */
test('a finished job that lingers in the queue reads as done and ready, not paused', () => {
  const done = { running: false, progress: 0.998, elapsed_seconds: 151 } as Job;
  const d = device({ spooler: { present: true, idle: false, queue_length: 1, jobs: [done] } });
  assert.equal(api.isFinished(done), true);
  assert.equal(api.isStalled(done), false);
  assert.equal(api.jobPhase(d, done, false), 'done');
  assert.equal(api.machineState(d, true), 'ready');
  // A job standing still half-way is still a pause.
  const half = { running: false, progress: 0.42, elapsed_seconds: 60 } as Job;
  assert.equal(api.isStalled(half), true);
});

test('progress is live only while the controller is connected', () => {
  assert.equal(api.progressIsLive(device(), true), true);
  assert.equal(api.progressIsLive(device({ connection: { state: 'unknown', detail: null } }), true), false);
  assert.equal(api.progressIsLive(device(), false), false);
  // A driver that never reports its link is not a lost link.
  assert.equal(api.progressIsLive(device({ connection: undefined }), true), true);
});
