/**
 * Live connection met de OpenKerf API.
 *
 * De WebSocket stuurt een snapshot bij connect, daarna kernel-signalen en elke
 * 2 s opnieuw een volledige snapshot. Read-only: we sturen niets terug.
 */

import { currentJob } from './api';
import type { ApiEvent, Device, SignalEvent, Snapshot } from './api';
import { connection } from './connection.svelte';

const RECONNECT_MIN = 500;
const RECONNECT_MAX = 10_000;
const MAX_EVENTS = 25;

/**
 * Het spoor van de kop tijdens een job — gat J3.
 *
 * DESIGN-SYSTEM v2 beloofde dat de contour zich op het canvas aftekent terwijl
 * de machine hem snijdt. Die belofte is nooit ingelost, en de reden dat het niet
 * zomaar kan: wij weten hoe ver een job is (`steps_done` van `steps_total`) maar
 * niet in welke volgorde de engine de vormen afwerkt. Een percentage over een
 * verzonnen route uitsmeren zou een tekening opleveren die er goed uitziet en
 * niet klopt — precies wat je bij een machine die brandt niet moet doen.
 *
 * Wat we wél weten is gemeten: de driver seint bij elke beweging `driver;position`
 * met de vorige en de nieuwe stand van de kop (ruida/driver.py:571,
 * ruida/controller.py:253, en dezelfde regel bij grbl en lihuiyu). Die punten
 * achter elkaar zijn geen model maar een verslag: hier is de kop geweest.
 *
 * Twee eerlijkheidsgrenzen die de weergave moet dragen:
 * 1. Het signaal zegt niet of de laser aan stond. Snijden en de sprong ernaartoe
 *    zien er in dit spoor hetzelfde uit, dus het heet "spoor" en geen "kerf".
 * 2. Tussen twee notifications trekken we een rechte lijn. Bij een boog is dat de
 *    koorde, niet de boog.
 *
 * Het spoor hangt hier en niet in het canvas omdat de signalen hier binnenkomen;
 * het canvas leest hem als losse module-import, zodat er geen prop door de
 * pagina heen hoeft.
 */
const SPOOR_MAX = 6000;
/** Hoe vaak het spoor opnieuw getekend wordt. Tijdens een raster komen er
 *  honderden notifications per seconde binnen; elke melding een hertekening is een
 *  onbruikbaar canvas. */
const SPOOR_HERTEKEN_MS = 120;

export class Kopspoor {
	/**
	 * De punten als vlakke reeks x0,y0,x1,y1,… in scene-eenheden — dezelfde
	 * eenheid als `bounds` in `/api/design`, dus delen door `units_per_mm` geeft
	 * millimeters. Rauw en niet diep reactief: een proxy om zesduizend getallen
	 * kost meer dan het hertekenen zelf.
	 */
	punten = $state.raw<number[]>([]);
	/** Van welke job dit spoor is; wisselt hij, dan begint het opnieuw. */
	job = $state<string | null>(null);

	#buffer: number[] = [];
	#timer: ReturnType<typeof setTimeout> | null = null;

	/** Een melding van de driver: waar de kop vandaan kwam en waar hij nu is. */
	push(args: unknown[]) {
		const getal = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
		const x0 = getal(args[0]);
		const y0 = getal(args[1]);
		const x1 = getal(args[2]);
		const y1 = getal(args[3]);
		if (x1 === null || y1 === null) return;
		// Het eerste punt van een verse job krijgt ook zijn vertrekpunt mee;
		// daarna is het vertrekpunt het vorige eindpunt en zou het dubbel staan.
		if (!this.#buffer.length && x0 !== null && y0 !== null) this.#buffer.push(x0, y0);
		this.#buffer.push(x1, y1);
		if (this.#buffer.length > SPOOR_MAX * 2) {
			this.#buffer = this.#buffer.slice(this.#buffer.length - SPOOR_MAX * 2);
		}
		this.#plan();
	}

	#plan() {
		if (this.#timer) return;
		this.#timer = setTimeout(() => {
			this.#timer = null;
			this.punten = this.#buffer.slice();
		}, SPOOR_HERTEKEN_MS);
	}

	/** Nieuwe job, of geen job meer: een spoor van gisteren is misleiding. */
	begin(job: string | null) {
		if (this.job === job) return;
		this.job = job;
		this.#buffer = [];
		if (this.#timer) clearTimeout(this.#timer);
		this.#timer = null;
		this.punten = [];
	}
}

/** Eén spoor per pagina; het canvas leest hem rechtstreeks. */
export const kopspoor = new Kopspoor();

export class StatusConnection {
	snapshot = $state<Snapshot | null>(null);
	events = $state<SignalEvent[]>([]);
	connected = $state(false);
	lastUpdate = $state<number | null>(null);
	/** Welk serverproces we aan de lijn hebben; verandert alleen bij een herstart. */
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
	 * De job waar de bediening over gaat — lopend óf stilstaand.
	 *
	 * Dit filterde op `running`, en dat vlaggetje gaat bij Lihuiyu op `false`
	 * zodra je pauzeert. Gevolg: de job verdween uit de statusbalk, uit het
	 * Job-paneel en van de telefoon, er was geen knop om te hervatten, en
	 * "Job starten" werd weer active bovenop werk dat alleen maar stilstond.
	 */
	get activeJob() {
		return currentJob(this.device);
	}

	/**
	 * Welke job dit is, als één tekenreeks.
	 *
	 * Label plus het aantal stappen, en bewust níet de lengte van de wachtrij:
	 * die loopt terug zodra een job vóór deze klaar is, en dan zou het spoor
	 * midden in het branden op zwart springen.
	 *
	 * Twee keer hetzelfde vel achter elkaar geeft twee jobs met dezelfde sleutel,
	 * maar daartussen is er even geen actieve job — dan komt hier `null` langs en
	 * begint het spoor sowieso opnieuw.
	 */
	#jobsleutel(): string | null {
		const job = this.activeJob;
		if (!job) return null;
		return `${job.label}|${job.steps_total ?? 0}`;
	}

	connect() {
		this.#stopped = false;
		connection.retryNow = () => this.#nu();
		this.#open();
	}

	/**
	 * Meteen opnieuw proberen in plaats van de backoff uitzitten.
	 *
	 * Na een halve minuut wachten we tien seconden tussen pogingen. Wie net de
	 * server heeft herstart wil niet tien seconden naar een dood scherm kijken,
	 * en heeft bovendien informatie die wij niet hebben: hij weet dát hij hem
	 * herstart heeft.
	 */
	#nu() {
		if (this.#retryTimer) clearTimeout(this.#retryTimer);
		this.#retryTimer = null;
		this.#retryDelay = RECONNECT_MIN;
		this.#tellen(0);
		this.#open();
	}

	close() {
		this.#stopped = true;
		if (this.#retryTimer) clearTimeout(this.#retryTimer);
		this.#retryTimer = null;
		this.#tellen(0);
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
			this.#tellen(0);
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
				this.#hallo(payload.instance);
			} else if (payload.type === 'snapshot') {
				this.snapshot = payload.data;
				// Het spoor hoort bij één job (gat J3). Zodra er een andere in de
				// spooler staat — of geen enkele meer — begint het opnieuw, want
				// een lijn van de vorige job over het huidige werk is een leugen
				// die er precies uitziet als voortgang.
				kopspoor.begin(this.#jobsleutel());
			} else {
				if (payload.code === 'driver;position' && this.activeJob) {
					kopspoor.push(payload.args);
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
	 * De server stelt zich voor (gat E2).
	 *
	 * Hier zat een stille failure: de WebSocket verbond na een herstart keurig
	 * terug, de statusbalk werd weer groen, en de pagina toonde daarna
	 * onverstoorbaar het ontwerp van vóór de herstart — dat aan de andere kant
	 * niet meer bestaat. Je tekent verder in een document dat weg is.
	 *
	 * Zelfde `instance` = hetzelfde proces, dus een netwerkhik: de snapshot die
	 * er meteen achteraan komt herstelt alles wat live is, en er valt niets op
	 * te halen. Een ander `instance` betekent een nieuwe engine met een lege
	 * boom, en dan is er niets meer te redden aan de pagina zoals hij is. We
	 * herladen niet uit onszelf — dat gooit ongesaveld werk weg zonder dat
	 * iemand erom vroeg — maar zetten de vlag waar de app op reageert.
	 */
	#hallo(instance: string) {
		if (!instance) return;
		if (this.instance === null) {
			this.instance = instance;
			return;
		}
		if (this.instance !== instance) {
			this.instance = instance;
			connection.herstart = true;
		}
	}

	#scheduleReconnect() {
		if (this.#stopped || this.#retryTimer) return;
		this.#tellen(this.#retryDelay);
		this.#retryTimer = setTimeout(() => {
			this.#retryTimer = null;
			this.#open();
		}, this.#retryDelay);
		this.#retryDelay = Math.min(this.#retryDelay * 2, RECONNECT_MAX);
	}

	/**
	 * De aftelklok naar de volgende poging.
	 *
	 * Een app die stilstaat zonder te zeggen dat hij iets doet, ziet eruit als
	 * een app die vastgelopen is. Eén zichtbaar getal is het verschil tussen
	 * "hij is bezig" en "hij is dood".
	 */
	#tellen(ms: number) {
		if (this.#tikker) clearInterval(this.#tikker);
		this.#tikker = null;
		connection.inSeconds = Math.ceil(ms / 1000);
		if (ms <= 0) return;
		this.#tikker = setInterval(() => {
			connection.inSeconds = Math.max(0, connection.inSeconds - 1);
			if (connection.inSeconds === 0 && this.#tikker) {
				clearInterval(this.#tikker);
				this.#tikker = null;
			}
		}, 1000);
	}

	#tikker: ReturnType<typeof setInterval> | null = null;
}
