import { t, type MessageKey } from './i18n/core.ts';
/** Types mirroring the openkerf-api snapshot (api/openkerf_api/status.py). */

import type { TileRun } from './tiling.svelte';
import type { SeriesState } from './series.svelte';

export type Position = {
	native: [number, number] | null;
	mm: [number, number] | null;
	state: unknown[] | null;
};

export type Job = {
	label: string;
	type: string;
	status: string | null;
	priority: number | null;
	running: boolean | null;
	/**
	 * Is this job standing still because Pause was pressed?
	 *
	 * It comes from `driver.paused` and not from `status`: that field knows only four
	 * values and "pause" is not among them (meerk40t/core/laserjob.py:66). See
	 * `StatusReader.paused` in api/openkerf_api/status.py.
	 */
	paused?: boolean | null;
	steps_done: number | null;
	steps_total: number | null;
	progress: number | null;
	loops_executed: number | null;
	loops: number | null;
	elapsed_seconds: number | null;
	estimate_seconds: number | null;
};

export type Spooler = {
	present: boolean;
	idle: boolean | null;
	queue_length: number;
	jobs: Job[];
};

export type Bed = { width_mm: number | null; height_mm: number | null };

/**
 * Is a machine really attached? "unknown" is an honest answer for families where
 * the engine has no source for it; it is *not* a reason to
 * "verbonden" te tonen.
 */
export type Connection = {
	state: 'connected' | 'disconnected' | 'unknown';
	detail: string | null;
};

export type Device = {
	label: string | null;
	path: string | null;
	active: boolean;
	laser_status: string | null;
	/** Pause pressed? `null` when this driver does not say. */
	paused?: boolean | null;
	connection?: Connection;
	bed: Bed;
	position: Position;
	spooler: Spooler;
};

export type Capabilities = {
	actions: {
		start: boolean;
		pause: boolean;
		resume: boolean;
		stop: boolean;
		clear_queue: boolean;
		load: boolean;
	};
	/** What *this* device can move. It differs per machine: a Ruida knows focusing,
	 *  a K40 board does not. */
	motion?: {
		home: boolean;
		physical_home: boolean;
		unlock: boolean;
		lock: boolean;
		move: boolean;
		jog: boolean;
		focus: boolean;
	};
	/** Can this driver adjust speed and power while a job is running (gap J11)? Only
	 *  grbl has realtime overrides for it; on a Ruida this is false and those buttons
	 *  should not be there. */
	adjust?: {
		power: boolean;
		speed: boolean;
	};
	/** Can this machine connect and disconnect? Ruida and the USB families can, grbl
	 *  cannot — it opens its connection itself as soon as work goes to it. */
	connection?: {
		connect: boolean;
		disconnect: boolean;
	};
	auth_required: boolean;
};

export type Snapshot = {
	kernel: { name: string | null; version: string | null };
	devices: Device[];
	/** The running tile run, or nothing. See `$lib/tiling.svelte` (`TileRun`). */
	tiling?: TileRun | null;
	/**
	 * The series, or nothing at all when no list is attached.
	 *
	 * `_series_state()` in `api/openkerf_api/server.py`, beside the tile run and for
	 * the same reason: the top bar, the canvas, the context panel and the run block in
	 * the Job panel all read the live socket, and four requests for one fact drift
	 * apart. The rows themselves are deliberately not in here — a thousand rows down
	 * every socket a few times a minute for a number that fits in a word — so a surface
	 * that needs them calls `GET /api/series` (`SeriesStore.load`).
	 *
	 * A type import, like `TileRun` above: it is erased at compile time, so `api.ts`
	 * stays free of runes and `node --test` can still reach it.
	 */
	series?: SeriesState | null;
};

export type SignalEvent = {
	type: 'signal';
	code: string;
	origin: string | null;
	args: unknown[];
	time: number;
};

export type SnapshotEvent = { type: 'snapshot'; data: Snapshot };
/**
 * The first message on every fresh socket: who the server is.
 *
 * `instance` is new on every start of the server process. If it changes between two
 * connections, the engine has restarted and everything the page is holding belongs
 * to a different life (gap E2).
 */
export type HelloEvent = { type: 'hello'; instance: string };
export type ApiEvent = SignalEvent | SnapshotEvent | HelloEvent;

/**
 * Machine state as the UI shows it — doubly encoded, never colour alone.
 *
 * `offline` and `unplugged` are two different disasters and ask for two different
 * actions. `offline`: the app cannot reach the OpenKerf server — restart the server,
 * or you are on the wrong address. `unplugged`: the server is running fine, but no
 * machine is attached — check the cable or switch it on. One word for both sends
 * half the people to the
 * verkeerde kabel.
 */
export type MachineState = 'offline' | 'unplugged' | 'ready' | 'busy' | 'paused' | 'alarm';

/**
 * What the machine is doing.
 *
 * `laser_status` on its own is not a trustworthy source: MeerK40t's Ruida driver sets
 * that field nowhere (verified with a grep over `meerk40t/ruida/`), so on our target
 * machine it stays "idle" forever. A green "Ready" above a burning laser is exactly
 * the failure you must not make here, which is why a running job in the spooler
 * counts just as heavily.
 */
export function machineState(device: Device | null, connected: boolean): MachineState {
	if (!connected || !device) return 'offline';
	// currentJob and not runningJob: a paused Lihuiyu job has `running === false` and
	// therefore fell out of sight — pause and all.
	const job = currentJob(device);
	if (device.laser_status === 'pause' || device.laser_status === 'paused') return 'paused';
	// The driver itself, and that is the only hard source (see `StatusReader.paused`).
	// It counts without a job too: a machine that is paused does not start the next
	// piece of work, and then "Ready" is a promise that does not come true.
	if (device.paused === true) return 'paused';
	// The drivers do not signal a pause back (FEATURE-GAPS P3), so a job that has run
	// and now stands still is the only evidence we get. Without this the bar said
	// "Busy" next to a button labelled "Resume".
	if (isStalled(job)) return 'paused';
	if (device.laser_status === 'active') return 'busy';
	if (job || device.spooler.idle === false) return 'busy';
	// Only here, and not earlier: a machine that is burning is connected by
	// definition, and a driver that does not report its connection must not write off a
	// running job as "not connected". But a quiet machine without a cable is *not*
	// "Ready" — that was a green dot above a dead port.
	if (device.connection?.state === 'disconnected') return 'unplugged';
	return 'ready';
}

export function runningJob(device: Device | null): Job | null {
	return device?.spooler.jobs.find((job) => job.running) ?? null;
}

/**
 * Is this job paused?
 *
 * `status` used to be the only source here, and that could never work:
 * `LaserJob.status` returns Running, Queued, Waiting or Disabled and never anything
 * with "pause" in it (meerk40t/core/laserjob.py:66). Measured consequence on a
 * running job: after a press on Pause everything stayed as it was — the same pause
 * button, no resume button, a green "Busy" — while the driver was very much paused.
 * The API now sends that flag along as `paused`; the status field stays for the case
 * where a driver does eventually write it.
 */
export function isPaused(job: Job | null): boolean {
	if (job?.paused === true) return true;
	return (job?.status ?? '').toLowerCase().includes('pause');
}

/**
 * The job the controls are about.
 *
 * `running` on its own is too narrow: Lihuiyu sets that flag to `false` on pause,
 * after which the job disappeared from sight — including the button to resume it,
 * and with "Start job" active again on top of a job that was merely standing still. A
 * paused job is still your job, so it counts here.
 *
 * Three sources, in descending certainty: it is running / it says itself that it is
 * paused / the spooler reports it is not empty (some drivers do not report a pause
 * back at all — see FEATURE-GAPS P3).
 */
export function currentJob(device: Device | null): Job | null {
	const jobs = device?.spooler.jobs ?? [];
	return (
		jobs.find((job) => job.running) ??
		jobs.find((job) => isPaused(job)) ??
		(device?.spooler.idle === false ? (jobs[0] ?? null) : null)
	);
}

/**
 * Is there work that is not making progress? That is something other than "no
 * job": the
 * the difference between resuming and starting again hangs off it.
 *
 * Not just looking at the status field: pausing sets `running` to `false` on
 * Lihuiyu without reporting anything else, and the drivers do not signal a pause back
 * anyway (FEATURE-GAPS P3). A job that exists but is not running is standing still —
 * which is what you want to see on screen.
 *
 * **This is the only definition** (gap J8). PhoneView had a variant of its own —
 * `Boolean(job) && (!running || machineState === 'paused')` — that dropped the
 * requirement "there was progress already". Consequence: a freshly spooled job is not
 * running yet and was shown there as "Paused" for one poll round, while the rest of
 * the app simply saw it in the queue. Two screens side by side saying something
 * anders zeggen over dezelfde job.
 *
 * Whoever also wants the device side (`laser_status === "pause"`, so a machine that
 * pauses itself without the job reporting anything) does not take this function but
 * `machineState(device, connected) === 'paused'`. That one already calls this below,
 * so it stays one source.
 */
export function isStalled(job: Job | null): boolean {
	if (!job) return false;
	if (isPaused(job)) return true;
	if (job.running) return false;
	// Started but standing still = paused. Nothing done yet = waiting its turn.
	// Without that distinction the top bar jumped to "Paused" for one poll round just
	// after starting, because a freshly spooled job is not running either.
	return (job.elapsed_seconds ?? 0) > 0 || (job.progress ?? 0) > 0;
}

/**
 * From what progress we believe the measured speed over the model.
 *
 * Below this bound the projection is noise — one slow first movement turns it into
 * hours. Above it the clock knows better than any model.
 */
const GEMETEN_VANAF = 0.1;

/**
 * How long this job takes in total, from one source.
 *
 * This was gap B1. The status bar put "0:00 left" next to "of 13:45:04" and those two
 * came from different worlds: the remaining time was the clock (elapsed ÷ progress),
 * the total was the engine's burn model (`LaserJob._estimate`, added up from the
 * cutcode). As long as those two are far apart the pair reads as nonsense — 100 %
 * done, thirteen hours
 * gaan.
 *
 * So: as soon as there is enough progress to measure, the measured projection is the
 * total *and* the source of the remainder. Before that the model is both. There is one
 * jump in it, at the moment we go from guessing to measuring; that is the honest place
 * for a jump.
 */
export function totalSeconds(job: Job | null): number | null {
	if (!job) return null;
	const elapsed = job.elapsed_seconds ?? 0;
	if (job.progress !== null && job.progress >= GEMETEN_VANAF && elapsed > 0) {
		return elapsed / job.progress;
	}
	const model = job.estimate_seconds;
	if (model === null || model === undefined || Number.isNaN(model)) return null;
	return model;
}

/**
 * How much longer. That is the only number someone standing next to a running
 * machine really wants; elapsed and total are there to check the sum.
 */
export function remainingSeconds(job: Job | null): number | null {
	const total = totalSeconds(job);
	if (total === null) return null;
	return Math.max(0, total - (job?.elapsed_seconds ?? 0));
}

/**
 * The name of a job, in human language.
 *
 * The engine calls a nameless job `Spooler:3 items` (spoolers.py:612 — the class
 * name plus the length of the command list). That is an internal tally, not a
 * name, and it appeared in three places: the Job panel, the status bar and the
 * phone view. Each of those needed its own detour; hence the wording lives here,
 * once.
 *
 * `openkerf_api.commands.start_job` now gives a job we spool a real name, so this
 * catches what comes from elsewhere: the console, a restored session, a plugin.
 */
export function jobLabel(job: Job | null): string {
	const raw = (job?.label ?? '').trim();
	const anonymous = /^\w+:(\d+)\s+items?$/.exec(raw);
	if (anonymous) return t('job.label.operations', { n: Number(anonymous[1]) });
	const movement = tupleLabel(raw);
	if (movement) return movement;
	return raw || t('job.label.unnamed');
}

/**
 * A movement job carries no name but its first instruction.
 *
 * Show frame spools a single movement, and the engine uses the repr of the Python
 * tuple as its label. So the Job panel and the phone view showed literally
 * `('move_abs', 114.7544mm, 80.0mm)` under a moving head. What it says is true —
 * it really is the command that is running — but it is the engine's language, and
 * it does not belong on screen.
 *
 * Deliberately no "Show frame" in this table: the same `move_abs` also comes from
 * jogging and from "go to a point", and inventing a name that is sometimes wrong
 * is exactly the kind of label this round is hunting for.
 */
const MOVEMENT: Record<string, MessageKey> = {
	move_abs: 'job.move.head',
	move_rel: 'job.move.head',
	home: 'job.move.home',
	physical_home: 'job.move.home',
	rapid_mode: 'job.move.head',
	set_origin: 'job.move.setOrigin'
};

function tupleLabel(raw: string): string | null {
	const tuple = /^\(\s*'([a-z_]+)'\s*(?:,\s*([^)]*?))?,?\s*\)$/.exec(raw);
	if (!tuple) return null;
	const name = t(MOVEMENT[tuple[1]] ?? 'job.move.unknown');
	const args = (tuple[2] ?? '')
		.split(',')
		.map((part) => part.trim())
		.filter(Boolean);
	// Two numbers are a point on the bed; that is the only argument that says
	// anything to someone standing at the machine.
	const point = args.filter((a) => /^-?[\d.]+\s*mm$/.test(a));
	if (point.length === 2) return t('job.move.to', { what: name, x: point[0], y: point[1] });
	return name;
}

/** The engine has its own words for a status; the interface has the user's. */
export function jobStatusLabel(job: Job): string {
	const raw = (job.status ?? '').toLowerCase();
	if (raw.includes('pause')) return t('job.status.paused');
	if (raw.includes('run')) return t('job.status.running');
	// "Waiting" is what the engine calls a spooled job the machine has not picked up
	// yet. It fell through every branch and reached the screen unfiltered — the one
	// word in the Job tab that was not in the catalogue, exactly where you want to
	// know whether something is broken.
	if (raw.includes('queue') || raw.includes('wait')) return t('job.status.queued');
	if (raw.includes('complete') || raw.includes('done')) return t('job.status.done');
	if (job.running) return t('job.status.running');
	// An unknown status from the engine is shown as-is: inventing a translation
	// for a word we do not know is worse than showing the engine's own word.
	return job.status ? job.status : t('job.status.queued');
}

// ─── The phase of the job ────────────────────────────────────────────────────
//
// Why this exists. Before this round every surface read its own field to decide
// whether work was under way: the top bar looked at the machine state, the Job
// panel at `job.running`, the spooler card at `job.status`, and the status bar at
// the progress. Measured with a job in the queue of a machine that did not answer
// (`status: "Waiting"`, `running: false`, `progress: 0`): the top bar disabled
// "Start job", the panel left "Start job" enabled, the card said "Waiting" and the
// status bar "0 % — 4:58 left". Four answers to one question, and the most
// dangerous one was in the panel — one tap there spools a second job on top of the
// first.
//
// So: one function decides the phase, and every surface reads it.

export type JobPhase =
	/** There is no work on the bed. */
	| 'nothing'
	/** Work on the bed, nothing under way: this is the moment to start. */
	| 'ready'
	/** Spooled, but the machine has not picked it up yet. */
	| 'queued'
	| 'burning'
	| 'paused'
	/** Practically at 100 % and going nowhere: the engine does not sign it off. */
	| 'done';

/**
 * From what progress a standing-still job reads as done.
 *
 * `LaserJob.calc_steps` counts one step more than `execute` carries out, so the
 * progress reaches 0.998 and not 1, and the job then stays in the queue as
 * "Waiting" (see the upstream list in CLAUDE.md). Without this bound the app reads
 * a finished job as "standing still" — exactly the message you do not want under
 * work that is done. Measured: 576/577 and 584/585 steps.
 */
const DONE = 0.995;

export function jobPhase(device: Device | null, job: Job | null, designEmpty: boolean): JobPhase {
	if (!job) return designEmpty ? 'nothing' : 'ready';
	if (isPaused(job)) return 'paused';
	if (job.running) return 'burning';
	if ((job.progress ?? 0) >= DONE) return 'done';
	// Started but standing still is a pause; nothing done yet is waiting its turn.
	// The same bound as `isStalled`, because two bounds for the same distinction is
	// how the surfaces drifted apart in the first place.
	if (isStalled(job)) return 'paused';
	return 'queued';
}

/** Is there work running that the machine must not be disturbed in? */
export function jobBusy(phase: JobPhase): boolean {
	return phase === 'burning' || phase === 'paused' || phase === 'queued';
}

/**
 * May the app take you away from the work area right now?
 *
 * The stop button and its shortcut hang on the top bar, and the top bar is the work
 * area's. `routes/setup/` has neither: `Stop`, `transport` and `onStop` give zero hits
 * in that whole folder. The machine chip in the top left is a plain link to it, so one
 * click on your own machine name during a job took the stop off the screen — and you
 * only find that out at the moment you need it.
 *
 * The same three phases as `jobBusy`, asked as a different question, so that whoever
 * adds a fourth way out reads one rule instead of writing a second.
 */
export function mayLeaveWorkArea(phase: JobPhase): boolean {
	return !jobBusy(phase);
}

/**
 * What a phase is called, and what it means.
 *
 * The explanation is not decoration: "in the queue" is indistinguishable from
 * "it has hung" for a user, and that difference is exactly what you are looking
 * for at that moment.
 */
export function phaseTitle(phase: JobPhase): string {
	return t(`job.phase.${phase}.title` as never);
}

export function phaseBody(phase: JobPhase): string {
	return t(`job.phase.${phase}.body` as never);
}

/**
 * The shortcuts for the two actions that are in a hurry (gap J4).
 *
 * As text, because they appear in three places — two tooltips and the
 * explanation in the Job panel — and typing the same thing three times is three
 * chances to drift. ⌘ on a Mac, Ctrl elsewhere: it says the key you actually
 * have to press.
 */
export const STOP_KEY =
	typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform ?? '')
		? '⌘ + .'
		: 'Ctrl + .';
export const PAUSE_KEY = 'Pause';

/**
 * The name of a machine state, in the reader's language.
 *
 * A function and no longer a table: a table is read once at module load, and by
 * then the language may not be settled — and switching language afterwards would
 * not reach it. Everything that a user reads goes through the catalogue.
 */
export function machineStateLabel(state: MachineState): string {
	return t(`machine.state.${state}` as never);
}

/**
 * What you can do about a state, when there is something to do. A status that
 * only says something is wrong leaves you with a dead screen; this is the
 * sentence that belongs underneath it.
 */
export function machineStateHint(state: MachineState): string | undefined {
	if (state === 'offline' || state === 'unplugged' || state === 'alarm')
		return t(`machine.hint.${state}` as never);
	return undefined;
}

export function formatMm(value: number | null | undefined): string {
	if (value === null || value === undefined || Number.isNaN(value)) return '—';
	return value.toFixed(1);
}

export function formatDuration(seconds: number | null | undefined): string {
	if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—';
	const total = Math.max(0, Math.round(seconds));
	const h = Math.floor(total / 3600);
	const m = Math.floor((total % 3600) / 60);
	const s = total % 60;
	const pad = (n: number) => String(n).padStart(2, '0');
	return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/**
 * The three quantities of a test grid, and how they are written down.
 *
 * Since decision B12 the user picks which two go on the axes; the third is fixed.
 * A summary that assumes "speed × power" therefore lies about an interval grid —
 * which is what happened on the phone, where "1×3 · 200–200 mm/s" appeared for a
 * grid whose axis was the interval.
 *
 * Name and unit live here because more than one screen needs them: the wizard
 * that makes the grid, and the photo list that finds it again. Two copies of the
 * same unit is two chances to drift.
 */
export type GridAxis = 'speed' | 'power' | 'interval';

/** The name of an axis, in the reader's language. */
export function axisLabel(axis: GridAxis): string {
	return t(`axis.${axis}` as never);
}

export const AXIS_UNIT: Record<GridAxis, string> = {
	speed: 'mm/s',
	power: '%',
	interval: 'mm'
};

/** The least a grid row has to carry to be summarised. */
export type GridAxes = {
	row_axis?: GridAxis | null;
	column_axis?: GridAxis | null;
	rows?: number | null;
	columns?: number | null;
	speed_steps?: number | null;
	power_steps?: number | null;
} & Partial<Record<`${GridAxis}_min` | `${GridAxis}_max`, number | null>>;

/** No "0.10" and no "5.00": as many decimals as the value needs. */
function short(value: number): string {
	return String(Number(value.toFixed(3)));
}

/**
 * The range of one axis, with its unit: `5–20 mm/s`, `0.05–0.25 mm`.
 *
 * When the quantity is not on an axis, min equals max and this yields a single
 * value instead of a range from nothing to nothing.
 */
export function axisRange(grid: GridAxes, axis: GridAxis): string {
	const min = grid[`${axis}_min`] ?? null;
	const max = grid[`${axis}_max`] ?? null;
	if (min === null && max === null) return '—';
	const unit = AXIS_UNIT[axis];
	if (min === null || max === null || min === max)
		return `${short((min ?? max) as number)} ${unit}`;
	return `${short(min)}–${short(max)} ${unit}`;
}

/**
 * The matrix size, whichever quantity sits where.
 *
 * `rows`/`columns` were filled from `speed_steps`/`power_steps` by the migration
 * for older grids; that fallback stays for a server older than the migration.
 */
export function gridSize(grid: GridAxes): string {
	const rows = grid.rows ?? grid.speed_steps ?? 0;
	const columns = grid.columns ?? grid.power_steps ?? 0;
	return `${rows}×${columns}`;
}

/**
 * One line saying what this grid varies: the size plus the two axes.
 *
 * The fixed quantity is not in it — that is engraved on the board, and on a
 * 240 px phone line space is the scarce thing.
 */
export function gridSummary(grid: GridAxes): string {
	const row = grid.row_axis ?? 'speed';
	const column = grid.column_axis ?? 'power';
	return `${gridSize(grid)} · ${axisRange(grid, row)} · ${axisRange(grid, column)}`;
}
