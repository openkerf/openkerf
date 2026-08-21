/**
 * Notifications — decision B3: reporting yes, intervening no.
 *
 * Two things, and the difference between them matters:
 *
 * 1. A **browser notification** when the job is done or stops making progress.
 *    That one exists precisely for the moment you are *not* looking: another
 *    tab, phone in your pocket. As long as you have to keep watching, a monitor
 *    is half a monitor.
 * 2. An **alarm** inside the app itself, for what the engine tells us about the
 *    connection to the machine.
 *
 * What emphatically does not happen here: inferring something we do not
 * measure. We see no flame, no smoke and no temperature — the camera hangs off
 * the computer, not off the machine. Every statement below comes from a signal
 * the engine emits itself, and the text says where it came from. Nothing is
 * ever acted on automatically either: this file sends not a single command to
 * the laser.
 */

import { currentJob, formatDuration, type Device, type SignalEvent } from './api';
import { locale, t, type MessageKey } from './i18n/core.ts';

export type NotifyPermission = 'unsupported' | 'default' | 'granted' | 'denied';

const ON_KEY = 'openkerf.notifications';
const ASKED_KEY = 'openkerf.notifications.asked';

/** What the browser makes of it, in plain words. Shown, not logged. */
export function permissionText(permission: NotifyPermission): string {
	return t(`notify.permission.${permission}` as never);
}

export class Notifications {
	permission = $state<NotifyPermission>('unsupported');
	/**
	 * The user's preference, separate from what the browser thinks.
	 *
	 * Two distinct things: "I do not want this" is not the same as "the browser
	 * does not allow it", and they need a different answer on screen.
	 */
	on = $state(true);
	/** Has the question ever been put? If not, the prompt card may appear. */
	asked = $state(false);
	/** The last notification we sent — evidence on the settings card. */
	last = $state<{ title: string; body: string; time: number; shown: boolean } | null>(null);
	failure = $state<string | null>(null);

	constructor() {
		if (typeof window === 'undefined') return;
		this.read();
		this.on = localStorage.getItem(ON_KEY) !== 'off';
		// If the browser already has an answer, the question has been put — even if
		// that happened in an earlier session or in another tab.
		this.asked = localStorage.getItem(ASKED_KEY) === 'yes' || this.permission !== 'default';
	}

	/** The browser can change behind our back (site settings); read it again. */
	read() {
		if (typeof window === 'undefined' || !('Notification' in window)) {
			this.permission = 'unsupported';
			return;
		}
		this.permission = Notification.permission as NotifyPermission;
	}

	/** Do we actually send anything? Both have to say yes. */
	get active() {
		return this.on && this.permission === 'granted';
	}

	/**
	 * May the prompt card come on screen?
	 *
	 * Only when the browser knows nothing yet *and* we have not asked before. A
	 * permission request without a reason gets refused, and a refused permission
	 * does not come back — so we ask at the moment there is something to report,
	 * not when the app loads.
	 */
	get shouldAsk() {
		return this.permission === 'default' && !this.asked;
	}

	/** "Not now." No second attempt to ask; the settings card stays the way back. */
	notNow() {
		this.asked = true;
		if (typeof localStorage !== 'undefined') localStorage.setItem(ASKED_KEY, 'yes');
	}

	set(on: boolean) {
		this.on = on;
		if (typeof localStorage !== 'undefined') localStorage.setItem(ON_KEY, on ? 'on' : 'off');
	}

	/**
	 * Put the permission question. Only call this from a real click: Safari
	 * demands a fresh user gesture and refuses the request otherwise.
	 */
	async ask(): Promise<NotifyPermission> {
		this.notNow();
		this.failure = null;
		if (typeof window === 'undefined' || !('Notification' in window)) {
			this.permission = 'unsupported';
			return this.permission;
		}
		try {
			this.permission = (await Notification.requestPermission()) as NotifyPermission;
		} catch {
			// Older Safari only knows the callback form and throws here.
			this.read();
		}
		if (this.permission === 'granted') this.set(true);
		return this.permission;
	}

	/**
	 * Send one notification.
	 *
	 * `always` is for what cannot wait: normally we keep quiet as long as the tab
	 * is on screen — it is already there, and a pop-up about something you are
	 * looking at is noise. A fault always goes through.
	 */
	async notify(
		title: string,
		body: string,
		tag: string,
		options: { always?: boolean } = {}
	): Promise<boolean> {
		const visible = typeof document !== 'undefined' && document.visibilityState === 'visible';
		const send = this.active && (options.always || !visible);
		this.last = { title, body, time: Date.now(), shown: send };
		if (!send) return false;
		const content: NotificationOptions = {
			body,
			tag,
			icon: '/icon-192.png',
			badge: '/icon-192.png',
			lang: locale(),
			// A fault should stay up until you click it away; "done" may go by itself.
			requireInteraction: Boolean(options.always)
		};
		try {
			// Through the service worker when we can: Android does not allow
			// `new Notification()` from a page and throws a TypeError there.
			if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
				const registration = await navigator.serviceWorker.getRegistration();
				if (registration) {
					await registration.showNotification(title, content);
					return true;
				}
			}
			new Notification(title, content);
			return true;
		} catch {
			this.failure = t('notify.refused');
			return false;
		}
	}

	/** Check for yourself that it works, without waiting for a job. */
	test() {
		return this.notify(t('notify.test.title'), t('notify.test.body'), 'openkerf-test', {
			always: true
		});
	}
}

export type Alarm = {
	/** Unique per fact, so "seen" does not stick to a new alarm. */
	code: string;
	title: string;
	body: string;
	/** What you can do now. Never something we would already have done ourselves. */
	advice: string;
	/** The engine's own line, verbatim. Evidence, not decoration. */
	source?: string;
	since: number;
};

/**
 * What the engine's USB log says when the machine is unreachable.
 *
 * Deliberately a list and *not* a hunt for words like "fail": that same log
 * reports "Kernel detach: Failed." on every normal connection on macOS without
 * anything being wrong. A false alarm on a screen that watches a laser is worse
 * than a late one — after two empty alarms nobody looks at it any more. Hence
 * only the lines that really mean nothing is burning, each with a sentence of
 * its own; the original line stays visible as the source.
 *
 * Source: `meerk40t/lihuiyu/controller.py` and `meerk40t/ch341/` (read, not
 * guessed). If upstream adds a line, this list keeps quiet — that is the safe
 * side of the failure.
 */
const FAULTS: { pattern: RegExp; sentence: MessageKey; advice: MessageKey }[] = [
	{
		pattern: /usb connection did not exist/i,
		sentence: 'fault.usb.none',
		advice: 'fault.usb.none.advice'
	},
	{
		pattern: /connection (to usb )?failed/i,
		sentence: 'fault.usb.failed',
		advice: 'fault.usb.failed.advice'
	},
	{
		pattern: /devices? not found|no ch341 devices detected/i,
		sentence: 'fault.usb.notFound',
		advice: 'fault.usb.notFound.advice'
	},
	{
		pattern: /no backend libusb|driver detected: none/i,
		sentence: 'fault.usb.noDriver',
		advice: 'fault.usb.noDriver.advice'
	},
	{
		pattern: /does not give you permissions/i,
		sentence: 'fault.usb.noPermission',
		advice: 'fault.usb.noPermission.advice'
	},
	{
		pattern: /interface claim: failed/i,
		sentence: 'fault.usb.busy',
		advice: 'fault.usb.busy.advice'
	},
	{
		pattern: /requires serial number confirmation/i,
		sentence: 'fault.usb.serial',
		advice: 'fault.usb.serial.advice'
	}
];

/** And the lines with which it says everything is well again. */
const RECOVERED = /usb connected|device connected|serial number confirmed/i;

/** This long without movement before we call it a stall. */
const STILL_MS = 120_000;

/**
 * The watchdog reads the status and decides when there is something to report.
 *
 * Everything here is derived from what the engine passes on: the spooler, the
 * device's connection status and the signal `pipe;usb_status`. No observation of
 * our own is involved, and no command goes out.
 */
export class Watchdog {
	alarm = $state<Alarm | null>(null);
	/** Clicked away. The alarm stays; only the bar goes. */
	seen = $state(false);

	#ran = false;
	#name = '';
	#duration = 0;
	#position = '';
	#positionSince = 0;
	#stallReported = false;

	#notifications: Notifications;

	constructor(notifications: Notifications) {
		this.#notifications = notifications;
	}

	get show() {
		return this.alarm !== null && !this.seen;
	}

	dismiss() {
		this.seen = true;
	}

	#set(alarm: Omit<Alarm, 'since'>) {
		// A fault overrules a "done" that is still queued up.
		if (this.#doneTimer) {
			clearTimeout(this.#doneTimer);
			this.#doneTimer = null;
		}
		if (this.alarm?.code === alarm.code) return;
		this.alarm = { ...alarm, since: Date.now() };
		this.seen = false;
		this.#notifications.notify(alarm.title, `${alarm.body} ${alarm.advice}`, 'openkerf-alarm', {
			always: true
		});
	}

	#clear(prefix: string) {
		if (this.alarm?.code.startsWith(prefix)) {
			this.alarm = null;
			this.seen = false;
		}
	}

	/**
	 * The job has started. Called on the press of the button *and* as soon as we
	 * see a running job in the snapshot — a short job is over before the status
	 * ever shows it, and without this that very job would never produce a "done".
	 */
	started() {
		this.#ran = true;
		this.#stallReported = false;
	}

	/** Signals from the engine. Two of them say something here. */
	signal(event: SignalEvent) {
		if (event.code === 'spooler;completed') {
			this.#done();
			return;
		}
		if (event.code !== 'pipe;usb_status') return;
		const line = String(event.args?.[0] ?? '').trim();
		if (!line) return;
		if (RECOVERED.test(line)) {
			this.#clear('usb:');
			return;
		}
		const fault = FAULTS.find((f) => f.pattern.test(line));
		if (!fault) return;
		this.#set({
			code: `usb:${fault.sentence}`,
			title: t('fault.noConnection'),
			body: t(fault.sentence),
			advice: t(fault.advice),
			source: line
		});
	}

	/**
	 * The spooler is empty and there was work: that is "done".
	 *
	 * With a short pause on it, and that is not slowness but ordering. On a
	 * machine that is not on the USB the engine reports `spooler;completed`
	 * *first* and only then that the connection was never there. Without this
	 * pause you get "Job done" and a second later "No connection" — precisely
	 * the wrong order to read on your phone. A fault now overtakes the "done".
	 */
	#done() {
		if (!this.#ran) return;
		this.#ran = false;
		this.#stallReported = false;
		this.#clear('stall');
		if (this.#doneTimer) clearTimeout(this.#doneTimer);
		this.#doneTimer = setTimeout(() => {
			this.#doneTimer = null;
			this.#sendDone();
		}, 2500);
	}

	#doneTimer: ReturnType<typeof setTimeout> | null = null;

	#sendDone() {
		this.#notifications.notify(
			t('notify.job.done'),
			this.#duration > 0
				? t('notify.job.doneBody', { name: this.#name, time: formatDuration(this.#duration) })
				: t('notify.job.endedBody', { name: this.#name }),
			'openkerf-job'
		);
	}

	/**
	 * The snapshot, every two seconds.
	 *
	 * This is where "done" and "not making progress" are detected. The bound for
	 * that last one is deliberately generous: a grid with many small operations
	 * may look idle for a while, and a false alarm on a machine that is burning is
	 * worse than a late report.
	 */
	status(device: Device | null, connected: boolean) {
		if (!connected) {
			if (this.#ran) {
				this.#ran = false;
				// No alarm card (gap B9). This alarm is not about the machine but about
				// *our* server, and that is exactly the subject of the connection card
				// that already sits at the top on every device — including the sentence
				// "stopping is only possible on the machine itself" and a button to try
				// again. Two cards saying the same thing, the lower one taking three
				// lines over it, do not make the upper one more credible.
				//
				// The system notification does stay: that reaches you with the tab in
				// the background or the screen off, and there is no card there.
				this.#notifications.notify(t('notify.lost.title'), t('notify.lost.body'), 'openkerf-alarm', {
					always: true
				});
			}
			return;
		}

		const job = currentJob(device);
		if (!job) {
			// Safety net beside `spooler;completed`: that signal is the fast route,
			// this is the route that still gets there if the signal was lost.
			this.#done();
			return;
		}

		this.#name = jobName(job.label);
		this.#duration = job.elapsed_seconds ?? 0;
		// Only from the moment something has actually happened does it count as
		// "ran"; otherwise a job that merely sat in the queue also reports "done".
		if (job.running || (job.elapsed_seconds ?? 0) > 0 || (job.progress ?? 0) > 0) this.#ran = true;

		const position = `${job.steps_done ?? 0}/${job.progress ?? 0}`;
		const now = Date.now();
		if (position !== this.#position) {
			this.#position = position;
			this.#positionSince = now;
			this.#stallReported = false;
			this.#clear('stall');
			return;
		}
		if (!this.#positionSince) this.#positionSince = now;
		if (!this.#stallReported && job.running && now - this.#positionSince > STILL_MS) {
			this.#stallReported = true;
			this.#set({
				code: 'stall',
				title: t('notify.stalled.title'),
				body: t('notify.stalled.body', {
					minutes: Math.round((now - this.#positionSince) / 60_000),
					percent: Math.round((job.progress ?? 0) * 100)
				}),
				advice: t('notify.stalled.advice')
			});
		}
	}
}

/**
 * The engine calls an unnamed job "Spooler:1 items".
 *
 * That is the queue's internal tally, not a title — and certainly not on a
 * notification you read on your phone (FEATURE-GAPS P4).
 */
export function jobName(label: string | null | undefined): string {
	const text = label ?? '';
	const m = text.match(/^Spooler:\s*(\d+)\s*items?$/i);
	if (!m) return text || t('notify.job.unnamed');
	return t('job.label.operations', { n: Number(m[1]) });
}
