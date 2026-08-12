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
 * Hoe lang nog. Dat is het enige getal dat iemand naast een draaiende machine
 * echt wil weten; verstreken en totaal zijn er om het te kunnen narekenen.
 */
export function remainingSeconds(job: Job | null): number | null {
	const total = totalSeconds(job);
	if (total === null) return null;
	return Math.max(0, total - (job?.elapsed_seconds ?? 0));
}

/**
 * De naam van een job, in mensentaal.
 *
 * De engine noemt een naamloze job `Spooler:3 items` (spoolers.py:612 — de
 * klassenaam plus de lengte van de opdrachtenlijst). Dat is een interne
 * opsomming, geen naam, en hij stond op drie plekken in beeld: het Job-paneel,
 * de statusbalk en de telefoon. Elk van die drie had zijn eigen omweg nodig;
 * daarom staat de vertaling hier, één keer.
 *
 * `openkerf_api.commands.start_job` geeft een job die wij spoolen inmiddels een
 * echte naam mee, dus dit vangt wat er van elders komt: de console, een
 * herstelde sessie, een plugin.
 */
export function jobLabel(job: Job | null): string {
	const raw = (job?.label ?? '').trim();
	const anoniem = /^\w+:(\d+)\s+items?$/.exec(raw);
	if (anoniem) {
		const n = Number(anoniem[1]);
		return n === 1 ? '1 bewerking' : `${n} bewerkingen`;
	}
	return raw || 'Naamloze job';
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

/**
 * De sneltoetsen voor de twee acties die haast hebben (gat J4).
 *
 * Als tekst, want ze staan op drie plekken in beeld — twee tooltips en de
 * uitleg in het Job-paneel — en drie keer hetzelfde intypen is drie kansen om
 * te gaan afwijken. ⌘ op een Mac, Ctrl elders: het staat op de knop die je
 * werkelijk moet indrukken.
 */
export const STOP_TOETS =
	typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform ?? '')
		? '⌘ + .'
		: 'Ctrl + .';
export const PAUZE_TOETS = 'Pause';

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

/**
 * De drie grootheden van een testraster, en hoe je ze opschrijft.
 *
 * Sinds besluit B12 kiest de gebruiker zélf welke twee op de assen staan; de
 * derde ligt vast. Een samenvatting die "snelheid × vermogen" aanneemt liegt
 * dus bij een intervalraster — dat was het geval op de telefoon, waar
 * "1×3 · 200–200 mm/s" stond bij een raster waarvan het interval de as was.
 *
 * Naam en eenheid staan hier omdat ze op meerdere schermen nodig zijn: de
 * wizard die het raster maakt, en de fotolijst die het terugvindt. Twee kopieën
 * van dezelfde eenheid is twee kansen om te gaan afwijken.
 */
export type GridAxis = 'speed' | 'power' | 'interval';

export const AXIS_LABEL: Record<GridAxis, string> = {
	speed: 'Snelheid',
	power: 'Vermogen',
	interval: 'Interval'
};

export const AXIS_UNIT: Record<GridAxis, string> = {
	speed: 'mm/s',
	power: '%',
	interval: 'mm'
};

/** Wat een rasterrij minimaal moet dragen om samen te vatten. */
export type GridAxes = {
	row_axis?: GridAxis | null;
	column_axis?: GridAxis | null;
	rows?: number | null;
	columns?: number | null;
	speed_steps?: number | null;
	power_steps?: number | null;
} & Partial<Record<`${GridAxis}_min` | `${GridAxis}_max`, number | null>>;

/** Geen "0.10" en geen "5.00": zoveel decimalen als de waarde nodig heeft. */
function kort(value: number): string {
	return String(Number(value.toFixed(3)));
}

/**
 * Het bereik van één as, met eenheid: `5–20 mm/s`, `0.05–0.25 mm`.
 *
 * Staat de grootheid niet op een as, dan is min gelijk aan max en levert dit
 * één waarde in plaats van een bereik van niks naar niks.
 */
export function axisRange(grid: GridAxes, axis: GridAxis): string {
	const min = grid[`${axis}_min`] ?? null;
	const max = grid[`${axis}_max`] ?? null;
	if (min === null && max === null) return '—';
	const eenheid = AXIS_UNIT[axis];
	if (min === null || max === null || min === max) return `${kort((min ?? max) as number)} ${eenheid}`;
	return `${kort(min)}–${kort(max)} ${eenheid}`;
}

/**
 * De matrixmaat, ongeacht welke grootheid waar staat.
 *
 * `rows`/`columns` zijn door de migratie voor oude rasters gevuld uit
 * `speed_steps`/`power_steps`; die val blijft staan voor een server die nog
 * ouder is dan de migratie.
 */
export function gridSize(grid: GridAxes): string {
	const rijen = grid.rows ?? grid.speed_steps ?? 0;
	const kolommen = grid.columns ?? grid.power_steps ?? 0;
	return `${rijen}×${kolommen}`;
}

/**
 * Eén regel die zegt wát dit raster varieert: de maat plus de twee assen.
 *
 * De vaste grootheid staat er niet bij — die staat op het bord gegraveerd, en
 * op een telefoonregel van 240 px is ruimte de schaarste.
 */
export function gridSummary(grid: GridAxes): string {
	const rij = grid.row_axis ?? 'speed';
	const kolom = grid.column_axis ?? 'power';
	return `${gridSize(grid)} · ${axisRange(grid, rij)} · ${axisRange(grid, kolom)}`;
}
