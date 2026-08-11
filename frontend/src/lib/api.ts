/** Types mirroring the openkerf-api snapshot (api/openkerf_api/status.py). */

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
	auth_required: boolean;
};

export type Snapshot = {
	kernel: { name: string | null; version: string | null };
	devices: Device[];
};

export type SignalEvent = {
	type: 'signal';
	code: string;
	origin: string | null;
	args: unknown[];
	time: number;
};

export type SnapshotEvent = { type: 'snapshot'; data: Snapshot };
export type ApiEvent = SignalEvent | SnapshotEvent;

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

/** Is deze job gepauzeerd? De engine schrijft dat in het statusveld. */
export function isPaused(job: Job | null): boolean {
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
 * Hoe lang nog. Dat is het enige getal dat iemand naast een draaiende machine
 * echt wil weten; verstreken en totaal zijn er om het te kunnen narekenen.
 */
export function remainingSeconds(job: Job | null): number | null {
	if (!job) return null;
	const total = job.estimate_seconds;
	if (total === null || total === undefined || Number.isNaN(total)) return null;
	// De voortgang van de engine is nauwkeuriger dan de klok zodra een job
	// sneller of trager loopt dan geschat.
	if (job.progress !== null && job.progress > 0.02) {
		const elapsed = job.elapsed_seconds ?? 0;
		return Math.max(0, elapsed / job.progress - elapsed);
	}
	return Math.max(0, total - (job.elapsed_seconds ?? 0));
}

/** De engine spreekt Engels; deze app niet. */
export function jobStatusLabel(job: Job): string {
	const raw = (job.status ?? '').toLowerCase();
	if (raw.includes('pause')) return 'Gepauzeerd';
	if (raw.includes('run')) return 'Bezig';
	if (raw.includes('queue')) return 'In wachtrij';
	if (raw.includes('complete') || raw.includes('done')) return 'Klaar';
	if (job.running) return 'Bezig';
	return job.status ? job.status : 'In wachtrij';
}

export const STATE_LABEL: Record<MachineState, string> = {
	offline: 'Offline',
	unplugged: 'Niet verbonden',
	ready: 'Gereed',
	busy: 'Bezig',
	paused: 'Pauze',
	alarm: 'Alarm'
};

/**
 * Wat je nu kunt doen, per toestand. Een status die alleen zegt dát het mis is,
 * laat je met een dood scherm zitten; dit is de zin die eronder hoort.
 */
export const STATE_HINT: Partial<Record<MachineState, string>> = {
	offline: 'De OpenKerf-server reageert niet. Draait hij nog?',
	unplugged: 'Er hangt geen machine aan. Controleer kabel en aan/uit.'
};

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
