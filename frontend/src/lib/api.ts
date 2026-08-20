import { t, type MessageKey } from './i18n/core.ts';
/** Types mirroring the openkerf-api snapshot (api/openkerf_api/status.py). */

import type { TileRun } from './tiling.svelte';

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
	 * Staat deze job stil omdat er op Pauze gedrukt is?
	 *
	 * Komt van `driver.paused` en niet uit `status`: dat veld kent maar vier
	 * waarden en "pause" zit er niet bij (meerk40t/core/laserjob.py:66). Zie
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
 * Hangt er echt een machine aan? "unknown" is een eerlijk antwoord voor
 * families waar de engine er geen bron voor heeft; het is géén reden om
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
	/** Pauzeknop ingedrukt? `null` als deze driver het niet vertelt. */
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
	/** Wat dít apparaat kan bewegen. Verschilt per machine: een Ruida kent
	 *  scherpstellen, een K40-bord niet. */
	motion?: {
		home: boolean;
		physical_home: boolean;
		unlock: boolean;
		lock: boolean;
		move: boolean;
		jog: boolean;
		focus: boolean;
	};
	/** Kan deze driver snelheid en vermogen bijstellen terwijl een job loopt
	 *  (gat J11)? Alleen grbl heeft daar realtime overrides voor; op een Ruida
	 *  staat dit op false en horen die knoppen er niet te zijn. */
	adjust?: {
		power: boolean;
		speed: boolean;
	};
	/** Kan deze machine verbinden en verbreken? Ruida en de USB-families wel,
	 *  grbl niet — die opent zijn verbinding zelf zodra er werk naartoe gaat. */
	connection?: {
		connect: boolean;
		disconnect: boolean;
	};
	auth_required: boolean;
};

export type Snapshot = {
	kernel: { name: string | null; version: string | null };
	devices: Device[];
	/** De lopende tegelreeks, of niets. Zie `$lib/tiling.svelte` (`TileRun`). */
	tiling?: TileRun | null;
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
 * Het eerste bericht op elke verse socket: wie de server is.
 *
 * `instance` is nieuw bij elke start van het serverproces. Verandert hij
 * tussen twee verbindingen, dan is de engine herstart en is alles wat de
 * pagina vasthoudt van een ander leven (gat E2).
 */
export type HelloEvent = { type: 'hello'; instance: string };
export type ApiEvent = SignalEvent | SnapshotEvent | HelloEvent;

/**
 * Machine state as the UI shows it — dubbel gecodeerd, nooit alleen kleur.
 *
 * `offline` en `unplugged` zijn twee verschillende rampen en vragen om twee
 * verschillende handelingen. `offline`: de app kan de OpenKerf-server niet
 * bereiken — herstart de server, of je zit op het verkeerde adres. `unplugged`:
 * de server draait prima, maar er hangt geen machine aan — controleer de kabel
 * of zet hem aan. Eén woord voor allebei stuurt de helft van de mensen naar de
 * verkeerde kabel.
 */
export type MachineState = 'offline' | 'unplugged' | 'ready' | 'busy' | 'paused' | 'alarm';

/**
 * Wat de machine aan het doen is.
 *
 * `laser_status` alléén is geen betrouwbare bron: de Ruida-driver van MeerK40t
 * zet dat veld nergens (geverifieerd met een grep over `meerk40t/ruida/`), dus
 * op onze doelmachine blijft het eeuwig "idle". Een groene "Gereed" boven een
 * brandende laser is precies de fout die je hier niet mag maken, daarom telt
 * een lopende job in de spooler net zo hard mee.
 */
export function machineState(device: Device | null, connected: boolean): MachineState {
	if (!connected || !device) return 'offline';
	// currentJob en niet runningJob: een gepauzeerde Lihuiyu-job heeft
	// `running === false` en viel daardoor buiten beeld — inclusief zijn pauze.
	const job = currentJob(device);
	if (device.laser_status === 'pause' || device.laser_status === 'paused') return 'paused';
	// De driver zelf, en dat is de enige harde bron (zie `StatusReader.paused`).
	// Ook zonder job telt hij: een machine die op pauze staat begint niet aan
	// het volgende werk, en dan is "Gereed" een belofte die niet uitkomt.
	if (device.paused === true) return 'paused';
	// De drivers seinen een pauze niet terug (FEATURE-GAPS P3), dus een job die
	// al gelopen heeft en nu stilstaat is het enige bewijs dat we krijgen.
	// Zonder dit zei de balk "Bezig" naast een knop met "Hervatten" erop.
	if (isStalled(job)) return 'paused';
	if (device.laser_status === 'active') return 'busy';
	if (job || device.spooler.idle === false) return 'busy';
	// Pas hier, en niet eerder: een machine die brandt is per definitie
	// verbonden, en een driver die zijn verbinding niet meldt mag een lopende
	// job niet als "niet verbonden" wegzetten. Maar een stille machine zonder
	// kabel is géén "Gereed" — dat was een groene stip boven een dode poort.
	if (device.connection?.state === 'disconnected') return 'unplugged';
	return 'ready';
}

export function runningJob(device: Device | null): Job | null {
	return device?.spooler.jobs.find((job) => job.running) ?? null;
}

/**
 * Is deze job gepauzeerd?
 *
 * `status` stond hier als enige bron, en dat kón nooit werken: `LaserJob.status`
 * geeft Running, Queued, Waiting of Disabled terug en nooit iets met "pause"
 * erin (meerk40t/core/laserjob.py:66). Gemeten gevolg op een lopende job: na
 * een druk op Pauze bleef alles staan zoals het stond — dezelfde pauzeknop,
 * geen hervatknop, een groen "Bezig" — terwijl de driver wel degelijk
 * gepauzeerd was. De API levert die vlag nu mee als `paused`; het statusveld
 * blijft staan voor het geval een driver het ooit wél schrijft.
 */
export function isPaused(job: Job | null): boolean {
	if (job?.paused === true) return true;
	return (job?.status ?? '').toLowerCase().includes('pause');
}

/**
 * De job waar de bediening over gaat.
 *
 * `running` alleen is te smal: Lihuiyu zet dat vlaggetje bij pauzeren op
 * `false`, waarna de job uit beeld verdween — inclusief de knop om hem te
 * hervatten, en met "Job starten" weer actief bovenop een job die alleen maar
 * stilstond. Een gepauzeerde job is nog steeds jouw job, dus die telt hier mee.
 *
 * Drie bronnen, in aflopende zekerheid: hij loopt / hij zegt zelf gepauzeerd te
 * zijn / de spooler meldt dat hij niet leeg is (sommige drivers melden een
 * pauze helemaal niet terug — zie FEATURE-GAPS P3).
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
 * Ligt er werk dat niet vooruitkomt? Dat is iets anders dan "geen job": het
 * verschil tussen hervatten en opnieuw starten hangt eraan.
 *
 * Niet alleen op het statusveld kijken: pauzeren zet bij Lihuiyu `running` op
 * `false` zonder verder iets te melden, en de drivers seinen een pauze sowieso
 * niet terug (FEATURE-GAPS P3). Een job die er wel is maar niet loopt, staat
 * stil — dat is wat je op het scherm wil zien.
 *
 * **Dit is de enige definitie** (gat J8). PhoneView had een eigen variant —
 * `Boolean(job) && (!running || machineState === 'paused')` — die de eis "er
 * was al voortgang" liet vallen. Gevolg: een vers gespoolde job loopt nog niet
 * en werd daar één pollronde lang als "Pauze" getoond, terwijl de rest van de
 * app hem gewoon in de wachtrij zag staan. Twee schermen naast elkaar die iets
 * anders zeggen over dezelfde job.
 *
 * Wie ook de device-kant wil meenemen (`laser_status === "pause"`, dus een
 * machine die zelf pauzeert zonder dat de job iets meldt) neemt niet deze
 * functie maar `machineState(device, connected) === 'paused'`. Die roept dit
 * hieronder al aan, dus dat blijft één bron.
 */
export function isStalled(job: Job | null): boolean {
	if (!job) return false;
	if (isPaused(job)) return true;
	if (job.running) return false;
	// Begonnen maar staat stil = pauze. Nog niets gedaan = hij wacht nog op zijn
	// beurt. Zonder dat onderscheid sprong de bovenbalk vlak na het starten één
	// pollronde lang op "Pauze", omdat een net gespoolde job ook niet loopt.
	return (job.elapsed_seconds ?? 0) > 0 || (job.progress ?? 0) > 0;
}

/**
 * Vanaf hoeveel voortgang we de gemeten snelheid boven het model geloven.
 *
 * Onder deze grens is de projectie ruis — één trage eerste beweging maakt er
 * dan uren van. Erboven weet de klok het beter dan welk model ook.
 */
const GEMETEN_VANAF = 0.1;

/**
 * Hoe lang deze job in totaal duurt, uit één bron.
 *
 * Hier zat gat B1. De statusbalk zette "nog 0:00" naast "van 13:45:04" en die
 * twee kwamen uit verschillende werelden: het resterende was de klok
 * (verstreken ÷ voortgang), het totaal was het brandmodel van de engine
 * (`LaserJob._estimate`, opgeteld uit de cutcode). Zolang die twee ver uit
 * elkaar liggen leest het paar als onzin — 100 % klaar, nog dertien uur te
 * gaan.
 *
 * Dus: zodra er genoeg voortgang is om te meten, is de gemeten projectie het
 * totaal én de bron van het restant. Daarvóór is het model dat allebei. Er zit
 * één sprong in, op het moment dat we van gokken naar meten gaan; dat is de
 * eerlijke plek voor een sprong.
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
	// "Waiting" is wat de engine een gespoolde job noemt die de machine nog niet
	// heeft opgepakt. Die viel door alle takken heen en kwam ongefilterd op het
	// scherm — het enige Engelse woord in de Job-tab, precies op de plek waar je
	// wil weten of er iets stuk is.
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
