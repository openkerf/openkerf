/**
 * Meldingen — besluit B3: melden ja, zelf ingrijpen nee.
 *
 * Twee dingen, en het verschil ertussen is belangrijk:
 *
 * 1. Een **browsermelding** als de job klaar is of niet meer vooruitkomt. Die
 *    is er juist voor het moment dat je níet kijkt: ander tabblad, telefoon in
 *    je zak. Zolang je moet blijven kijken is een monitor een halve monitor.
 * 2. Een **alarm** in de app zelf, voor wat de engine ons doorgeeft over de
 *    verbinding met de machine.
 *
 * Wat hier nadrukkelijk niet gebeurt: iets afleiden dat we niet meten. Wij
 * zien geen vlam, geen rook en geen temperatuur — de camera hangt aan de
 * computer, niet aan de machine. Elke uitspraak hieronder komt uit een signaal
 * dat de engine zelf uitzendt, en de tekst zegt erbij waar hij vandaan komt.
 * Er wordt ook nergens automatisch ingegrepen: dit bestand stuurt geen enkele
 * opdracht naar de laser.
 */

import { currentJob, formatDuration, type Device, type SignalEvent } from './api';
import { t, type MessageKey } from './i18n/core.ts';

export type Toestemming = 'unsupported' | 'default' | 'granted' | 'denied';

const AAN_KEY = 'openkerf.meldingen';
const GEVRAAGD_KEY = 'openkerf.meldingen.gevraagd';

/** Wat de browser ervan vindt, in mensentaal. Wordt getoond, niet gelogd. */
export function toestemmingTekst(toestemming: Toestemming): string {
	return t(`notify.permission.${toestemming}` as never);
};

export class Meldingen {
	toestemming = $state<Toestemming>('unsupported');
	/**
	 * De voorkeur van de gebruiker, los van wat de browser vindt.
	 *
	 * Twee aparte dingen: "ik wil dit niet" is iets anders dan "de browser laat
	 * het niet toe", en ze vragen om een ander antwoord op het scherm.
	 */
	aan = $state(true);
	/** Is de vraag ooit gesteld? Zo niet, dan mag de aanleidingkaart komen. */
	gevraagd = $state(false);
	/** De laatste melding die we verstuurd hebben — bewijs op de instelkaart. */
	laatste = $state<{ titel: string; tekst: string; tijd: number; getoond: boolean } | null>(null);
	fout = $state<string | null>(null);

	constructor() {
		if (typeof window === 'undefined') return;
		this.lees();
		this.aan = localStorage.getItem(AAN_KEY) !== 'uit';
		// Als de browser al een antwoord heeft, is de vraag gesteld — ook als dat
		// in een vorige sessie of door een ander tabblad gebeurde.
		this.gevraagd = localStorage.getItem(GEVRAAGD_KEY) === 'ja' || this.toestemming !== 'default';
	}

	/** De browser kan buiten ons om wijzigen (site-instellingen); opnieuw lezen. */
	lees() {
		if (typeof window === 'undefined' || !('Notification' in window)) {
			this.toestemming = 'unsupported';
			return;
		}
		this.toestemming = Notification.permission as Toestemming;
	}

	/** Sturen we ook echt iets? Beide moeten ja zeggen. */
	get actief() {
		return this.aan && this.toestemming === 'granted';
	}

	/**
	 * Mag de aanleidingkaart in beeld?
	 *
	 * Alleen als de browser nog niets weet én we het nog niet gevraagd hebben.
	 * Een toestemmingsvraag zonder aanleiding wordt geweigerd, en een geweigerde
	 * toestemming krijg je niet meer terug — dus vragen we hem op het moment dat
	 * er iets te melden valt, niet bij het laden van de app.
	 */
	get vragen() {
		return this.toestemming === 'default' && !this.gevraagd;
	}

	/** "Niet nu." Geen tweede kans vragen; de instelkaart blijft de weg terug. */
	nietNu() {
		this.gevraagd = true;
		if (typeof localStorage !== 'undefined') localStorage.setItem(GEVRAAGD_KEY, 'ja');
	}

	zet(aan: boolean) {
		this.aan = aan;
		if (typeof localStorage !== 'undefined') localStorage.setItem(AAN_KEY, aan ? 'aan' : 'uit');
	}

	/**
	 * De toestemmingsvraag stellen. Alleen aanroepen vanuit een echte klik:
	 * Safari eist een verse gebruikershandeling en weigert de vraag anders.
	 */
	async vraag(): Promise<Toestemming> {
		this.nietNu();
		this.fout = null;
		if (typeof window === 'undefined' || !('Notification' in window)) {
			this.toestemming = 'unsupported';
			return this.toestemming;
		}
		try {
			this.toestemming = (await Notification.requestPermission()) as Toestemming;
		} catch {
			// Oudere Safari kent alleen de callback-vorm en gooit hier.
			this.lees();
		}
		if (this.toestemming === 'granted') this.zet(true);
		return this.toestemming;
	}

	/**
	 * Eén melding versturen.
	 *
	 * `altijd` is voor wat niet kan wachten: normaal houden we ons stil zolang
	 * het tabblad in beeld is — daar staat het al op het scherm, en een pop-up
	 * over iets wat je aankijkt is ruis. Een storing gaat wel altijd door.
	 */
	async meld(
		titel: string,
		tekst: string,
		tag: string,
		opties: { altijd?: boolean } = {}
	): Promise<boolean> {
		const zichtbaar = typeof document !== 'undefined' && document.visibilityState === 'visible';
		const stuur = this.actief && (opties.altijd || !zichtbaar);
		this.laatste = { titel, tekst, tijd: Date.now(), getoond: stuur };
		if (!stuur) return false;
		const inhoud: NotificationOptions = {
			body: tekst,
			tag,
			icon: '/icon-192.png',
			badge: '/icon-192.png',
			lang: 'nl',
			// Een storing hoort te blijven staan tot je hem wegklikt; "klaar" mag
			// vanzelf verdwijnen.
			requireInteraction: Boolean(opties.altijd)
		};
		try {
			// Via de service worker als het kan: Android laat `new Notification()`
			// niet toe vanuit een pagina en gooit daar een TypeError.
			if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
				const registratie = await navigator.serviceWorker.getRegistration();
				if (registratie) {
					await registratie.showNotification(titel, inhoud);
					return true;
				}
			}
			new Notification(titel, inhoud);
			return true;
		} catch {
			this.fout =
				t('notify.refused');
			return false;
		}
	}

	/** Zelf controleren of het werkt, zonder op een job te wachten. */
	test() {
		return this.meld(
			t('notify.test.title'),
			t('notify.test.body'),
			'openkerf-test',
			{ altijd: true }
		);
	}
}

export type Alarm = {
	/** Uniek per feit, zodat "gezien" niet blijft plakken op een nieuw alarm. */
	code: string;
	titel: string;
	tekst: string;
	/** Wat je nu kunt doen. Nooit iets wat wij zelf al gedaan zouden hebben. */
	raad: string;
	/** De regel van de engine zelf, woordelijk. Bewijs, geen versiering. */
	bron?: string;
	sinds: number;
};

/**
 * Wat de USB-log van de engine zegt als de machine niet bereikbaar is.
 *
 * Bewust een lijst en géén zoektocht naar woorden als "fail": diezelfde log
 * meldt bij elke normale verbinding op macOS "Kernel detach: Failed." zonder
 * dat er iets aan de hand is. Een vals alarm op een scherm dat een laser
 * bewaakt is erger dan een late melding — na twee loze alarmen kijkt niemand
 * er nog naar. Daarom alleen de regels die écht betekenen dat er niet gebrand
 * wordt, elk met een Nederlandse zin erbij; de oorspronkelijke regel blijft als
 * bron zichtbaar.
 *
 * Bron: `meerk40t/lihuiyu/controller.py` en `meerk40t/ch341/` (gelezen, niet
 * geraden). Komt er upstream een regel bij, dan zwijgt deze lijst — dat is de
 * veilige kant van de fout.
 */
const STORINGEN: { patroon: RegExp; zin: MessageKey; raad: MessageKey }[] = [
	{
		patroon: /usb connection did not exist/i,
		zin: 'fault.usb.none',
		raad: 'fault.usb.none.advice'
	},
	{
		patroon: /connection (to usb )?failed/i,
		zin: 'fault.usb.failed',
		raad: 'fault.usb.failed.advice'
	},
	{
		patroon: /devices? not found|no ch341 devices detected/i,
		zin: 'fault.usb.notFound',
		raad: 'fault.usb.notFound.advice'
	},
	{
		patroon: /no backend libusb|driver detected: none/i,
		zin: 'fault.usb.noDriver',
		raad: 'fault.usb.noDriver.advice'
	},
	{
		patroon: /does not give you permissions/i,
		zin: 'fault.usb.noPermission',
		raad: 'fault.usb.noPermission.advice'
	},
	{
		patroon: /interface claim: failed/i,
		zin: 'fault.usb.busy',
		raad: 'fault.usb.busy.advice'
	},
	{
		patroon: /requires serial number confirmation/i,
		zin: 'fault.usb.serial',
		raad: 'fault.usb.serial.advice'
	}
];

/** En de regels waarmee hij zegt dat het weer goed zit. */
const HERSTEL = /usb connected|device connected|serial number confirmed/i;

/** Zo lang stilstand voordat we het een vastloper noemen. */
const STIL_MS = 120_000;

/**
 * De bewaker leest de status en besluit wanneer er iets te melden valt.
 *
 * Alles hier is afgeleid van wat de engine doorgeeft: de spooler, de
 * verbindingsstatus van het apparaat en het signaal `pipe;usb_status`. Er komt
 * geen enkele eigen waarneming bij kijken, en er gaat geen enkele opdracht uit.
 */
export class Bewaker {
	alarm = $state<Alarm | null>(null);
	/** Weggeklikt. Het alarm blijft bestaan; alleen de balk gaat weg. */
	gezien = $state(false);

	#liep = false;
	#naam = '';
	#duur = 0;
	#stand = '';
	#standSinds = 0;
	#stilGemeld = false;

	#meldingen: Meldingen;

	constructor(meldingen: Meldingen) {
		this.#meldingen = meldingen;
	}

	get toon() {
		return this.alarm !== null && !this.gezien;
	}

	sluit() {
		this.gezien = true;
	}

	#zet(alarm: Omit<Alarm, 'sinds'>) {
		// Een storing overrulet een "klaar" die nog op de rol staat.
		if (this.#klaarTimer) {
			clearTimeout(this.#klaarTimer);
			this.#klaarTimer = null;
		}
		if (this.alarm?.code === alarm.code) return;
		this.alarm = { ...alarm, sinds: Date.now() };
		this.gezien = false;
		this.#meldingen.meld(alarm.titel, `${alarm.tekst} ${alarm.raad}`, 'openkerf-alarm', {
			altijd: true
		});
	}

	#wis(voorvoegsel: string) {
		if (this.alarm?.code.startsWith(voorvoegsel)) {
			this.alarm = null;
			this.gezien = false;
		}
	}

	/**
	 * De job is begonnen. Wordt aangeroepen op de druk op de knop én zodra we
	 * een lopende job in de snapshot zien — een korte job is namelijk voorbij
	 * voordat de status hem ooit laat zien, en zonder dit zou uitgerekend die
	 * job nooit een "klaar" opleveren.
	 */
	gestart() {
		this.#liep = true;
		this.#stilGemeld = false;
	}

	/** Signalen uit de engine. Twee ervan zeggen hier iets. */
	signaal(event: SignalEvent) {
		if (event.code === 'spooler;completed') {
			this.#klaar();
			return;
		}
		if (event.code !== 'pipe;usb_status') return;
		const tekst = String(event.args?.[0] ?? '').trim();
		if (!tekst) return;
		if (HERSTEL.test(tekst)) {
			this.#wis('usb:');
			return;
		}
		const storing = STORINGEN.find((s) => s.patroon.test(tekst));
		if (!storing) return;
		this.#zet({
			code: `usb:${storing.zin}`,
			titel: t('fault.noConnection'),
			tekst: t(storing.zin),
			raad: t(storing.raad),
			bron: tekst
		});
	}

	/**
	 * De spooler is leeg en er liep werk: dat is "klaar".
	 *
	 * Met een korte pauze erop, en dat is geen traagheid maar volgorde. Bij een
	 * machine die niet aan de USB hangt meldt de engine éérst `spooler;completed`
	 * en pás daarna dat de verbinding er nooit was. Zonder deze pauze krijg je
	 * "Job klaar" en een seconde later "Geen verbinding" — precies de verkeerde
	 * volgorde om op je telefoon te lezen. Een storing haalt de "klaar" nu in.
	 */
	#klaar() {
		if (!this.#liep) return;
		this.#liep = false;
		this.#stilGemeld = false;
		this.#wis('stil');
		if (this.#klaarTimer) clearTimeout(this.#klaarTimer);
		this.#klaarTimer = setTimeout(() => {
			this.#klaarTimer = null;
			this.#stuurKlaar();
		}, 2500);
	}

	#klaarTimer: ReturnType<typeof setTimeout> | null = null;

	#stuurKlaar() {
		this.#meldingen.meld(
			t('notify.job.done'),
			this.#duur > 0
				? t('notify.job.doneBody', { name: this.#naam, time: formatDuration(this.#duur) })
				: t('notify.job.endedBody', { name: this.#naam }),
			'openkerf-job'
		);
	}

	/**
	 * De snapshot, elke twee seconden.
	 *
	 * Hier zit de detectie van "klaar" en van "komt niet vooruit". De grens voor
	 * dat laatste ligt bewust ruim: een raster met veel kleine bewerkingen mag
	 * even niets lijken te doen, en een vals alarm op een machine die brandt is
	 * erger dan een late melding.
	 */
	status(device: Device | null, connected: boolean) {
		if (!connected) {
			if (this.#liep) {
				this.#liep = false;
				// Geen alarmkaart (gat B9). Dit alarm gaat niet over de machine maar
				// over ónze server, en dat is exact het onderwerp van de
				// verbindingskaart die op elk apparaat al bovenaan staat — inclusief
				// de zin "stoppen kan alleen op de machine zelf" én een knop om het
				// opnieuw te proberen. Twee kaarten die hetzelfde zeggen, waarvan de
				// onderste er drie regels over doet, maken de bovenste niet
				// geloofwaardiger.
				//
				// De systeemmelding blijft wél: die bereikt je met de tab op de
				// achtergrond of het scherm op zwart, en dáár staat geen kaart.
				this.#meldingen.meld(t('notify.lost.title'), t('notify.lost.body'), 'openkerf-alarm', {
					altijd: true
				});
			}
			return;
		}

		const job = currentJob(device);
		if (!job) {
			// Vangnet naast `spooler;completed`: dat signaal is de snelle weg, dit
			// is de weg die het ook haalt als het signaal onderweg verloren ging.
			this.#klaar();
			return;
		}

		this.#naam = jobNaam(job.label);
		this.#duur = job.elapsed_seconds ?? 0;
		// Pas vanaf het moment dat er echt iets gebeurd is telt hij als "liep";
		// anders meldt een job die alleen maar in de wachtrij stond ook "klaar".
		if (job.running || (job.elapsed_seconds ?? 0) > 0 || (job.progress ?? 0) > 0) this.#liep = true;

		const stand = `${job.steps_done ?? 0}/${job.progress ?? 0}`;
		const nu = Date.now();
		if (stand !== this.#stand) {
			this.#stand = stand;
			this.#standSinds = nu;
			this.#stilGemeld = false;
			this.#wis('stil');
			return;
		}
		if (!this.#standSinds) this.#standSinds = nu;
		if (!this.#stilGemeld && job.running && nu - this.#standSinds > STIL_MS) {
			this.#stilGemeld = true;
			this.#zet({
				code: 'stil',
				titel: t('notify.stalled.title'),
				tekst: t('notify.stalled.body', {
					minutes: Math.round((nu - this.#standSinds) / 60_000),
					percent: Math.round((job.progress ?? 0) * 100)
				}),
				raad: t('notify.stalled.advice')
			});
		}
	}
}

/**
 * De engine noemt een naamloze job "Spooler:1 items".
 *
 * Dat is de interne opsomming van de wachtrij, geen titel — en op een melding
 * die je op je telefoon leest al helemaal niet (FEATURE-GAPS P4).
 */
export function jobNaam(label: string | null | undefined): string {
	const tekst = label ?? '';
	const m = tekst.match(/^Spooler:\s*(\d+)\s*items?$/i);
	if (!m) return tekst || t('notify.job.unnamed');
	return t('job.label.operations', { n: Number(m[1]) });
}
