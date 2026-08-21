/**
 * Live connection to the OpenKerf API.
 *
 * The WebSocket sends a snapshot on connect, then kernel signals, and a full
 * snapshot again every 2 s. Read-only: we send nothing back.
 */

import { currentJob } from './api';
import type { ApiEvent, Device, SignalEvent, Snapshot } from './api';
import { connection } from './connection.svelte';

const RECONNECT_MIN = 500;
const RECONNECT_MAX = 10_000;
const MAX_EVENTS = 25;

/**
 * The trail of the head during a job — gap J3.
 *
 * DESIGN-SYSTEM v2 promised that the contour draws itself on the canvas while the
 * machine cuts it. That promise was never kept, and the reason it cannot simply
 * be done: we know how far a job has got (`steps_done` of `steps_total`) but not
 * in which order the engine works through the shapes. Smearing a percentage over
 * an invented route would produce a drawing that looks right and is not — exactly
 * what you must not do around a machine that is burning.
 *
 * What we *do* know is measured: on every movement the driver signals
 * `driver;position` with the previous and the new position of the head
 * (ruida/driver.py:571, ruida/controller.py:253, and the same line in grbl and
 * lihuiyu). Those points in sequence are not a model but a report: the head has
 * been here.
 *
 * Two limits of honesty the display has to carry:
 * 1. The signal does not say whether the laser was on. Cutting and the jump
 *    towards it look the same in this trail, so it is called a "trail" and not a
 *    "kerf".
 * 2. Between two reports we draw a straight line. On an arc that is the chord,
 *    not the arc.
 *
 * The trail lives here and not in the canvas because the signals arrive here; the
 * canvas reads it as a plain module import, so no prop has to travel through the
 * page.
 */
const TRAIL_MAX = 6000;
/** How often the trail is redrawn. During a grid hundreds of reports arrive per
 *  second; a redraw per report is an unusable canvas. */
const TRAIL_REDRAW_MS = 120;

export class HeadTrail {
	/**
	 * The points as a flat sequence x0,y0,x1,y1,… in scene units — the same unit
	 * as `bounds` in `/api/design`, so dividing by `units_per_mm` gives
	 * millimetres. Raw and not deeply reactive: a proxy around six thousand
	 * numbers costs more than the redraw itself.
	 */
	points = $state.raw<number[]>([]);
	/** Which job this trail belongs to; if it changes, the trail starts over. */
	job = $state<string | null>(null);

	#buffer: number[] = [];
	#timer: ReturnType<typeof setTimeout> | null = null;

	/** A report from the driver: where the head came from and where it is now. */
	push(args: unknown[]) {
		const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
		const x0 = num(args[0]);
		const y0 = num(args[1]);
		const x1 = num(args[2]);
		const y1 = num(args[3]);
		if (x1 === null || y1 === null) return;
		// The first point of a fresh job carries its starting point as well; after
		// that the starting point is the previous end point and would be doubled.
		if (!this.#buffer.length && x0 !== null && y0 !== null) this.#buffer.push(x0, y0);
		this.#buffer.push(x1, y1);
		if (this.#buffer.length > TRAIL_MAX * 2) {
			this.#buffer = this.#buffer.slice(this.#buffer.length - TRAIL_MAX * 2);
		}
		this.#plan();
	}

	#plan() {
		if (this.#timer) return;
		this.#timer = setTimeout(() => {
			this.#timer = null;
			this.points = this.#buffer.slice();
		}, TRAIL_REDRAW_MS);
	}

	/** A new job, or no job at all: yesterday's trail is a misdirection. */
	begin(job: string | null) {
		if (this.job === job) return;
		this.job = job;
		this.#buffer = [];
		if (this.#timer) clearTimeout(this.#timer);
		this.#timer = null;
		this.points = [];
	}
}

/** One trail per page; the canvas reads it directly. */
export const headTrail = new HeadTrail();

export class StatusConnection {
	snapshot = $state<Snapshot | null>(null);
	events = $state<SignalEvent[]>([]);
	connected = $state(false);
	lastUpdate = $state<number | null>(null);
	/** Which server process we have on the line; changes only on a restart. */
	instance = $state<string | null>(null);

	#socket: WebSocket | null = null;
	#retryDelay = RECONNECT_MIN;
	#retryTimer: ReturnType<typeof setTimeout> | null = null;
	#stopped = false;

	get device(): Device | null {
		const devices = this.snapshot?.devices ?? [];
		return devices.find((d) => d.active) ?? devices[0] ?? null;
	}

	/**
	 * The job the controls are about — running *or* standing still.
	 *
	 * This filtered on `running`, and on Lihuiyu that flag goes to `false` as soon
	 * as you pause. Consequence: the job disappeared from the status bar, from the
	 * Job panel and from the phone, there was no button to resume, and "Start job"
	 * became active again on top of work that was merely paused.
	 */
	get activeJob() {
		return currentJob(this.device);
	}

	/**
	 * Which job this is, as a single string.
	 *
	 * Label plus the number of steps, and deliberately *not* the length of the
	 * queue: that counts down as soon as a job ahead of this one finishes, and the
	 * trail would jump to black in the middle of burning.
	 *
	 * The same sheet twice in a row gives two jobs with the same key, but in
	 * between there is briefly no active job — then `null` comes past here and the
	 * trail starts over anyway.
	 */
	#jobKey(): string | null {
		const job = this.activeJob;
		if (!job) return null;
		return `${job.label}|${job.steps_total ?? 0}`;
	}

	connect() {
		this.#stopped = false;
		connection.retryNow = () => this.#now();
		this.#open();
	}

	/**
	 * Try again straight away instead of sitting out the backoff.
	 *
	 * After half a minute we wait ten seconds between attempts. Somebody who has
	 * just restarted the server does not want to stare at a dead screen for ten
	 * seconds, and has information we do not have: they know they restarted it.
	 */
	#now() {
		if (this.#retryTimer) clearTimeout(this.#retryTimer);
		this.#retryTimer = null;
		this.#retryDelay = RECONNECT_MIN;
		this.#countdown(0);
		this.#open();
	}

	close() {
		this.#stopped = true;
		if (this.#retryTimer) clearTimeout(this.#retryTimer);
		this.#retryTimer = null;
		this.#countdown(0);
		this.#socket?.close();
		this.#socket = null;
		this.connected = false;
	}

	#open() {
		if (this.#stopped) return;
		const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
		const socket = new WebSocket(`${protocol}//${location.host}/api/ws`);
		this.#socket = socket;

		socket.onopen = () => {
			this.connected = true;
			connection.online = true;
			connection.since = null;
			this.#countdown(0);
			this.#retryDelay = RECONNECT_MIN;
		};

		socket.onmessage = (message) => {
			let payload: ApiEvent;
			try {
				payload = JSON.parse(message.data);
			} catch {
				return;
			}
			this.lastUpdate = Date.now();
			if (payload.type === 'hello') {
				this.#hello(payload.instance);
			} else if (payload.type === 'snapshot') {
				this.snapshot = payload.data;
				// The trail belongs to one job (gap J3). As soon as another one is in
				// the spooler — or none at all — it starts over, because a line from
				// the previous job across the current work is a lie that looks exactly
				// like progress.
				headTrail.begin(this.#jobKey());
			} else {
				if (payload.code === 'driver;position' && this.activeJob) {
					headTrail.push(payload.args);
				}
				this.events = [payload, ...this.events].slice(0, MAX_EVENTS);
			}
		};

		socket.onclose = () => {
			this.connected = false;
			connection.online = false;
			connection.since ??= Date.now();
			this.#socket = null;
			this.#scheduleReconnect();
		};

		socket.onerror = () => socket.close();
	}

	/**
	 * The server introduces itself (gap E2).
	 *
	 * There was a silent failure here: after a restart the WebSocket reconnected
	 * neatly, the status bar went green again, and the page then imperturbably
	 * showed the design from before the restart — which no longer exists on the
	 * other side. You go on drawing in a document that is gone.
	 *
	 * Same `instance` = the same process, so a network hiccup: the snapshot that
	 * follows immediately restores everything that is live, and there is nothing to
	 * retrieve. A different `instance` means a new engine with an empty tree, and
	 * then there is nothing left to save about the page as it is. We do not reload
	 * of our own accord — that throws away unsaved work without anybody asking —
	 * but we set the flag the app reacts to.
	 */
	#hello(instance: string) {
		if (!instance) return;
		if (this.instance === null) {
			this.instance = instance;
			return;
		}
		if (this.instance !== instance) {
			this.instance = instance;
			connection.restarted = true;
		}
	}

	#scheduleReconnect() {
		if (this.#stopped || this.#retryTimer) return;
		this.#countdown(this.#retryDelay);
		this.#retryTimer = setTimeout(() => {
			this.#retryTimer = null;
			this.#open();
		}, this.#retryDelay);
		this.#retryDelay = Math.min(this.#retryDelay * 2, RECONNECT_MAX);
	}

	/**
	 * The countdown to the next attempt.
	 *
	 * An app that stands still without saying it is doing something looks like an
	 * app that has crashed. One visible number is the difference between "it is
	 * busy" and "it is dead".
	 */
	#countdown(ms: number) {
		if (this.#ticker) clearInterval(this.#ticker);
		this.#ticker = null;
		connection.inSeconds = Math.ceil(ms / 1000);
		if (ms <= 0) return;
		this.#ticker = setInterval(() => {
			connection.inSeconds = Math.max(0, connection.inSeconds - 1);
			if (connection.inSeconds === 0 && this.#ticker) {
				clearInterval(this.#ticker);
				this.#ticker = null;
			}
		}, 1000);
	}

	#ticker: ReturnType<typeof setInterval> | null = null;
}
