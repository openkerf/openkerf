<script lang="ts">
	/**
	 * De telefoon: monitor en noodrem.
	 *
	 * Geen canvas, geen gereedschappen, geen lagen. Wie hier komt wil weten hoe
	 * het ervoor staat en desnoods ingrijpen — met één duim, terwijl hij naast
	 * de machine staat. Ontwerpen gebeurt op de desktop, en dat zegt dit scherm
	 * ook met zoveel woorden in plaats van een canvas erbij te proppen.
	 *
	 * Drie regels die de vorm bepalen:
	 * 1. De noodrem staat vást onderin en scrollt nooit weg — anders haal je de
	 *    twee seconden niet zodra de fotolijst langer wordt dan het scherm.
	 * 2. Elk blok verdient zijn hoogte. Een leeg podium van 130 px dat "geen job
	 *    active" zegt terwijl de kop dat al zei, is verspilde ruimte.
	 * 3. Wat je meet, toon je één keer. Voortgang stond hier drie keer en de
	 *    resterende tijd — het enige getal waar je op wacht — nul keer.
	 */
	import { i18n, t, type MessageKey } from '$lib/i18n/index.svelte';
	import {
		currentJob,
		gridSummary,
		formatDuration,
		jobLabel,
		remainingSeconds,
		machineStateLabel,
		type Device,
		type GridAxis,
		type Job,
		type MachineState
	} from '$lib/api';
	import type { Controller } from '$lib/control.svelte';
	import type { CameraStore } from '$lib/camera.svelte';
	import ConnectionCard from './ConnectionCard.svelte';
	import { connection } from '$lib/connection.svelte';
	import AlarmCard from './AlarmCard.svelte';
	import NotificationCard from './NotificationCard.svelte';
	import type { Bewaker, Meldingen } from '$lib/notifications.svelte';
	import type { DesignStore } from '$lib/design.svelte';

	let {
		device,
		state: machineState,
		job,
		control,
		camera,
		notifications,
		bewaker,
		connected,
		position,
		design = null,
		sheet = null
	}: {
		device: Device | null;
		state: MachineState;
		/** Alleen de lópende job, en daarom hier ongebruikt: dit scherm leest
		 *  `currentJob(device)`, want een gepauzeerde job hoort er ook bij (J8). */
		job: Job | null;
		control: Controller;
		camera: CameraStore;
		notifications: Meldingen;
		bewaker: Bewaker;
		connected: boolean;
		position: string;
		/** Wat er op het bed ligt (gat J10). Zonder dit tekende de telefoon een
		 *  leeg kader, ook met zeven vormen erop. */
		design?: DesignStore | null;
		sheet?: { name: string; width_mm: number; height_mm: number } | null;
	} = $props();

	// `job` is alleen de lópende job. Een gepauzeerde job valt daar buiten, en
	// die verdween daardoor compleet van dit scherm: je pauzeerde en het scherm
	// meldde "geen job active", zonder knop om te hervatten. `currentJob` is de
	// gedeelde definitie van "de job waar de bediening over gaat".
	let huidig = $derived<Job | null>(currentJob(device));
	let running = $derived(Boolean(huidig?.running));
	/**
	 * Staat er werk stil? Eén bron: `machineState()`, die `isStalled()` al
	 * aanroept en ook de device-kant (`laser_status === "pause"`) meeneemt.
	 *
	 * Hier stond een eigen variant die de eis "er was al voortgang" liet vallen
	 * (gat J8). Gevolg: een vers gespoolde job loopt nog niet en heette op de
	 * telefoon één pollronde lang "Pauze", terwijl de rest van de app hem in de
	 * wachtrij zag staan. Twee schermen die iets anders zeggen over één job.
	 */
	let stil = $derived(machineState === 'paused');

	/**
	 * De pauzeknop moet iets doen dat je ziet.
	 *
	 * De Lihuiyu-driver meldt een pauze niet terug in zijn status, dus zonder
	 * dit blijft het scherm na de druk exact hetzelfde en druk je nog eens.
	 * Dit is geen bewering dat hij stilstaat — het label zegt "gevraagd".
	 */
	let pauzeGevraagd = $state(false);
	$effect(() => {
		if (stil || !huidig) pauzeGevraagd = false;
	});
	async function pauzeer() {
		pauzeGevraagd = true;
		const ok = await control.pause();
		if (!ok) pauzeGevraagd = false;
	}

	/**
	 * Een camera die "aan" staat maar geen beeld levert.
	 *
	 * Zonder dit toont de browser zijn eigen kapotte-plaatje-icoon met de
	 * alt-tekst ernaast, en verdwijnt tegelijk alles wat wél te melden viel.
	 * Een losgetrokken USB-kabel hoort geen half scherm te kosten.
	 */
	let beeldStuk = $state(false);
	$effect(() => {
		camera.generation;
		beeldStuk = false;
	});

	let camAan = $derived(
		camera.state.available && camera.shown && camera.state.running && !beeldStuk
	);
	let progress = $derived(huidig?.progress ?? 0);
	let percent = $derived(Math.round(progress * 100));

	/**
	 * Resterende tijd, niet de totale schatting.
	 *
	 * Uit `remainingSeconds()`: hier stond dezelfde berekening met een eigen
	 * drempel (5 % voortgang tegen de 10 % van de gedeelde versie), dus telefoon
	 * en statusbalk sprongen op een ander moment van schatten naar meten en
	 * toonden even twee verschillende resttijden voor dezelfde job.
	 */
	let resterend = $derived(remainingSeconds(huidig));

	// Een aftelklok zegt hoe lang je moet wachten; een kloktijd zegt of je nog
	// koffie kunt halen. Naast elkaar kosten ze één regel.
	let klaarOm = $derived.by(() => {
		if (resterend === null) return null;
		const eind = new Date(Date.now() + resterend * 1000);
		return eind.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' });
	});

	// De ring: één omtrek die de voortgang draagt, in plaats van hetzelfde
	// percentage in drie vormen naast elkaar.
	const STRAAL = 78;
	const OMTREK = 2 * Math.PI * STRAAL;

	// Rasters die nog op een foto wachten: dat is de reden dat je met een
	// telefoon naast de machine staat. De bibliotheek houdt ze niet vast, dus
	// halen we ze hier op.
	type Raster = {
		id: number;
		material_name: string | null;
		operation: string;
		photo_path: string | null;
		thickness_mm: number | null;
		speed_min: number;
		speed_max: number;
		power_min: number;
		power_max: number;
		speed_steps: number;
		power_steps: number;
		// Sinds B12 kiest de gebruiker de assen zelf; welke grootheid waar staat
		// bepaalt wat de samenvattingsregel mag beweren.
		row_axis: GridAxis | null;
		column_axis: GridAxis | null;
		rows: number | null;
		columns: number | null;
		interval_min: number | null;
		interval_max: number | null;
		/** Waar het bord op de foto ligt. Null = foto binnen, nog niet uitgelijnd. */
		alignment: unknown;
		created_at: string;
	};
	let rasters = $state<Raster[]>([]);
	let bezig = $state<number | null>(null);
	/** Een rij die verdwijnt is te stil; dit vertelt wat er nu gebeurd is. */
	let gelukt = $state<string | null>(null);

	/** Veel materiaalnamen dragen de dikte al ("Berkentriplex 4 mm"); dan niet
	    nog eens "4 mm" erachter plakken. */
	function rasterNaam(g: Raster): string {
		// Zonder materiaal stond hier "raster · graveren-raster": tweemaal
		// hetzelfde woord, en van de twee is er één een interne sleutel.
		const naam = g.material_name ?? 'Testraster';
		if (!g.thickness_mm || /\bmm\b/i.test(naam)) return naam;
		return `${naam} ${g.thickness_mm} mm`;
	}

	/** De sleutels van de generator zijn geen woorden voor op het scherm. */
	const BEWERKING: Record<string, MessageKey> = {
		snijden: 'phone.operation.cut',
		'graveren-vector': 'phone.operation.engrave',
		'graveren-raster': 'phone.operation.raster',
		markeren: 'phone.operation.mark'
	};

	function bewerking(kind: string): string {
		return kind in BEWERKING ? t(BEWERKING[kind]) : kind;
	}

	/** "2026-08-11 19:33:37" → "11 Aug 19:33". No seconds, no year. */
	function stempel(waarde: string): string {
		const d = new Date(waarde.replace(' ', 'T'));
		if (Number.isNaN(d.getTime())) return waarde;
		// Not toLocaleString: that puts a comma between them, and then the line breaks
		// exactly there — "11 Aug," on one line, "19:51" on the next.
		const dag = new Intl.DateTimeFormat(i18n.locale, { day: 'numeric', month: 'short' }).format(d);
		const tijd = new Intl.DateTimeFormat(i18n.locale, { timeStyle: 'short' }).format(d);
		// Hard space: date and time belong together and must not fall apart.
		return `${dag} ${tijd}`.replace(/ /g, ' ');
	}

	/**
	 * The photo list knew only two states: photo needed, or gone (gap P9).
	 *
	 * Since there is an alignment on the grid row there is a third — photo in, not
	 * aligned yet — and that one quietly disappeared from the list. A half-finished
	 * step should not disappear: the board is still there, the preset is not yet, and
	 * nobody looking only at their phone knew there was still something to do.
	 */
	let wachtend = $derived(rasters.filter((g) => !g.photo_path));
	let uitlijnen = $derived(rasters.filter((g) => g.photo_path && !g.alignment));
	/** Eerst waar de telefoon voor nodig is, dan wat op de desktop wacht. */
	let lijst = $derived([...wachtend, ...uitlijnen]);

	async function haalRasters() {
		const r = await fetch('/api/library/testgrids');
		if (!r.ok) return;
		rasters = await r.json();
	}
	/**
	 * De rasterlijst bijhouden, want dit scherm is de tweede in de kamer.
	 *
	 * Dit haalde één keer op, bij het opbouwen van de pagina, en daarna nooit
	 * meer. Gemeten met twee vensters op dezelfde server: de desktop maakt een
	 * raster, je pakt de telefoon die al aanstond, en er staat niets — het
	 * raster verscheen pas na handmatig verversen. Precies de volgorde waarin
	 * je hem gebruikt: eerst instellen op de desktop, dan met de telefoon naar
	 * de machine.
	 *
	 * Geen WebSocket: die draagt machinestatus, en de bibliotheek zit in een
	 * andere database die geen signalen geeft. Tien seconden is ruim genoeg
	 * voor iets wat op een gebrand bord wacht, en het is één klein verzoek.
	 * Terugkomen op het tabblad haalt meteen op — dat is het moment waarop je
	 * kijkt.
	 */
	$effect(() => {
		haalRasters();
		const klok = setInterval(haalRasters, 10_000);
		const terug = () => {
			if (document.visibilityState === 'visible') haalRasters();
		};
		document.addEventListener('visibilitychange', terug);
		return () => {
			clearInterval(klok);
			document.removeEventListener('visibilitychange', terug);
		};
	});

	async function foto(gridId: number, bestand: File) {
		bezig = gridId;
		try {
			const form = new FormData();
			form.append('file', bestand);
			const token = localStorage.getItem('openkerf.token') ?? '';
			await fetch(`/api/library/testgrids/${gridId}/photo`, {
				method: 'POST',
				headers: token ? { Authorization: `Bearer ${token}` } : {},
				body: form
			});
			await haalRasters();
			gelukt = t('phone.photoSaved');
		} finally {
			bezig = null;
		}
	}

	/**
	 * De toestemmingsvraag krijgt hier zijn aanleiding van de machine zelf.
	 *
	 * Op de telefoon start je geen job (dat doet de desktop), dus is "er brandt
	 * nu iets" het moment waarop de ask ergens op slaat. Bij een leeg bed
	 * shouldAsk we niets; dan staat de instelling gewoon onderaan te wachten.
	 */
	let vraagWeg = $state(false);
	let vraagNu = $derived(notifications.shouldAsk && !vraagWeg && Boolean(huidig));
	/** De instelkaart uitgeklapt? Ingeklapt kost hij één regel. */
	let instellingenOpen = $state(false);

	/**
	 * De rangorde van dit scherm (besluit B13).
	 *
	 * Loopt er een job, dan is "hoe ver" de ask en blijft de ring boven. Staat
	 * de machine stil terwijl er een gebrand bord op een foto wacht, dan is dát
	 * het werk — en het is het enige werk in deze hele app waarvoor je fysiek
	 * een telefoon in je hand moet hebben.
	 *
	 * Uitlijnen telt hier niet mee: dat doe je op een groot scherm, dus het
	 * verandert niets aan waarom je hier staat.
	 */
	let fotoEerst = $derived(!huidig && wachtend.length > 0);
	/**
	 * De machinestand mag pas inkrimpen tot één regel als er niets aan de hand
	 * is. Een losgetrokken kabel of een alarm is geen bijzin; dan komt de hele
	 * kaart terug, mét de zin die uitlegt waarom het stil is.
	 */
	let standInEenRegel = $derived(fotoEerst && connected && machineState === 'ready');
	/** De bedtekening onder die ene regel. Dicht, want je kwam voor de foto. */
	let bedOpen = $state(false);
	let meldStand = $derived(
		notifications.permission === 'denied'
			? 'geblokkeerd'
			: notifications.active
				? 'aan'
				: 'uit'
	);

	let bedW = $derived(device?.bed.width_mm ?? 0);
	let bedH = $derived(device?.bed.height_mm ?? 0);
	let kop = $derived(device?.position.mm ?? null);

	/**
	 * Wat er op het bed ligt (gat J10).
	 *
	 * Dit scherm tekende een leeg kader, ook met zeven vormen erop — en dan is
	 * "kijken naast de machine" precies de ene ask die je niet beantwoord
	 * krijgt: wát gaat er zo meteen gebrand worden.
	 *
	 * De paddata staat in Tats, net als op het canvas; één schaaltransform set
	 * hem om naar de millimeters waarin deze tekening meet. En omdat het in
	 * millimeters meet, krijgt elke lijn `non-scaling-stroke` — anders is een
	 * streek van 1 op een bed van 610 mm een haar van niks (of op een klein bed
	 * een balk van een halve centimeter).
	 */
	let perMm = $derived(design?.design?.units_per_mm ?? 1);
	/**
	 * Hoe breed deze tekening werkelijk staat, in pixels.
	 *
	 * De SVG meet in millimeters (viewBox = het bed), dus zonder dit getal weet
	 * niets in dit bestand hoe groot een millimeter op het scherm is. Dat is wel
	 * nodig: zie `TEKST_MINIMUM`.
	 */
	let bedBreedtePx = $state(0);
	/**
	 * Onder deze weergavehoogte laten we vectortekst weg.
	 *
	 * De generator tekent opschriften in millimeters, want in millimeters wordt
	 * het gebrand — daar is niets mis mee. Maar 4 mm letterhoogte is op een bed
	 * van 610 mm in een tekening van 340 px ruim 2 px, en een contour van 2 px
	 * hoog met een streek van 1,5 px is geen letter meer: het is een balkje.
	 * Zichtbaar als twee massieve blauwe strepen linksboven het testraster.
	 *
	 * Weglaten is eerlijker dan vullen. Wat je overhoudt is het raster zelf, en
	 * dát is waar je op je telefoon naar kijkt. 12 px is de hoogte waaronder de
	 * binnenruimte van een `e` of een `a` bij deze streekdikte dichtloopt.
	 */
	const TEKST_MINIMUM = 12;
	/**
	 * Kleur en stand komen uit `strokeFor` — dezelfde helper die het canvas
	 * gebruikt. Zelf de laag uitzoeken leverde een ander antwoord op dan het
	 * canvas: bij een vorm in twee lagen pakte ik de eerste uit de lijst en het
	 * canvas de bovenste in de boom. Twee schermen die hetzelfde werk in een
	 * andere kleur tekenen is precies het soort verschil waardoor je op je
	 * telefoon niet meer durft te vertrouwen.
	 */
	let vormen = $derived.by(() => {
		const store = design;
		if (!store) return [];
		return store.elements
			.filter((element) => !element.hidden && (element.path || element.image))
			.map((element) => {
				const streek = store.strokeFor(element);
				return {
					id: element.id,
					path: element.path,
					image: element.image,
					// De hoogte in mm van een tekstelement; null voor al het andere.
					// `font_size_mm` is wat de generator bedoelde; ontbreekt dat, dan
					// is het kader van de vorm de beste benadering.
					tekstMm: element.text
						? (element.text.font_size_mm ??
							(element.bounds ? (element.bounds[3] - element.bounds[1]) / perMm : 0))
						: null,
					kleur: streek.color,
					zichtbaar: streek.visible,
					// "Brandt niet" dekt twee gevallen: in geen enkele laag, of in een
					// laag die op "brandt niet mee" staat. Voor wie naast de machine
					// staat is dat dezelfde mededeling.
					stil: streek.dashed || streek.dimmed
				};
			})
			.filter((vorm) => vorm.zichtbaar);
	});
	let brandt = $derived(vormen.filter((v) => !v.stil).length);
	let stille = $derived(vormen.filter((v) => v.stil).length);

	/**
	 * Werk dat buiten het bed of buiten het vel valt (gat P8).
	 *
	 * Het canvas meldt dit since C2 in twee zinnen onder de tekening; hier stond
	 * de vorm wél buiten het velkader getekend, maar zonder een woord erbij. Wie
	 * naast de machine in de zon staat, leest kleurverschil als eerste niet meer.
	 *
	 * Dezelfde som als op het canvas, met dezelfde speling en dezelfde regel dat
	 * alleen werk dat écht brandt meetelt: een vorm in geen laag kost geen
	 * materiaal, en valse alarmbellen leren mensen alarmbellen te negeren. De
	 * berekening is bewust hier en niet uit `/api/job/estimate`: dit scherm
	 * ververst op signalen, en een tweede bron zou een tweede antwoord geven.
	 */
	const RAND_SPELING = 0.5;

	function buitenKader(
		doos: { x: number; y: number; width: number; height: number },
		kader: { width: number; height: number }
	) {
		return (
			doos.x < -RAND_SPELING ||
			doos.y < -RAND_SPELING ||
			doos.x + doos.width > kader.width + RAND_SPELING ||
			doos.y + doos.height > kader.height + RAND_SPELING
		);
	}

	let buitenstaanders = $derived.by(() => {
		const uit = { bed: 0, vel: 0 };
		if (!design || !bedW || !bedH) return uit;
		for (const element of design.elements) {
			if (!element.bounds || element.hidden) continue;
			const streek = design.strokeFor(element);
			if (streek.dashed || streek.dimmed || !streek.visible) continue;
			const [x0, y0, x1, y1] = element.bounds.map((v) => v / perMm);
			const doos = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
			if (buitenKader(doos, { width: bedW, height: bedH })) uit.bed += 1;
			else if (
				sheet &&
				sheet.width_mm > 0 &&
				sheet.height_mm > 0 &&
				buitenKader(doos, { width: sheet.width_mm, height: sheet.height_mm })
			) {
				uit.vel += 1;
			}
		}
		return uit;
	});

	/**
	 * Wat er getékend wordt. Dat is niet hetzelfde als wat er brandt: te kleine
	 * opschriften vallen hier weg (`TEKST_MINIMUM`), maar ze branden wel, dus de
	 * telling erboven blijft ongemoeid. Een tekening mag iets weglaten; een
	 * getal dat zegt wat de machine gaat doen mag dat niet.
	 */
	let getekend = $derived.by(() => {
		const perPx = bedW > 0 && bedBreedtePx > 0 ? bedBreedtePx / bedW : 0;
		if (perPx === 0) return vormen;
		return vormen.filter((v) => v.tekstMm === null || v.tekstMm * perPx >= TEKST_MINIMUM);
	});

	/** Eén zin voor wie het beeld niet krijgt; hij staat ook onder de tekening. */
	let bedUitleg = $derived.by(() => {
		const delen = [`Bed ${Math.round(bedW)} bij ${Math.round(bedH)} millimeter`];
		if (vormen.length === 0) delen.push('leeg');
		else {
			delen.push(`${brandt} ${brandt === 1 ? 'vorm brandt' : 'vormen branden'}`);
			if (stille) delen.push(`${stille} in geen laag`);
		}
		if (buitenstaanders.bed) delen.push(`${buitenstaanders.bed} buiten het bed`);
		if (buitenstaanders.vel) delen.push(`${buitenstaanders.vel} buiten het vel`);
		delen.push(`kop op ${position}`);
		return delen.join(', ') + '.';
	});
</script>

<ConnectionCard brandt={running} />

<div class="telefoon">
	<!--
		At the top and outside the scroll area: an alarm you can scroll away is not an
		alarm (decision B3). Deliberately not an overlay: as a fixed block it pushes
		the rest down instead of covering the header and half the bed drawing. At
		390 px the floating version cost 270 px of cut-off content, and the machine
		status — precisely the first thing you want to see with a connection alarm —
		was permanently out of reach.
	-->
	<AlarmCard {bewaker} groot />
	<header>
		<span class="dot {machineState}" aria-hidden="true"></span>
		<span class="staat"
			>{connected ? machineStateLabel(machineState) : t('phone.noConnection')}</span
		>
		<span class="machine mono">{device?.label ?? t('phone.noMachine')}</span>
	</header>

	<!--
		The ranking follows what you do here, not what the screen is called
		(decision B13).

		With a running job the progress stays on top: then "how far" is the question.
		If the machine is idle and a burned board is waiting, there is exactly one
		thing to do for which you need a phone in your hand — taking a photo of
		something lying on the bed. That goes on top, and the machine state falls back
		to one line.

		The emergency brake does not move with it. See "The emergency brake: a
		trade-off with a price" in DESIGN-SYSTEM.md: findable blind weighs more than
		the dead button.
	-->
	{#snippet beeld()}
		<!-- Camera: if you can look, you look. -->
		<div class="podium">
			<img src={camera.src} alt={t('phone.cameraAlt')} onerror={() => (beeldStuk = true)} />
		</div>
	{/snippet}

	{#snippet bedkaart()}
		<!-- What is on the bed: the bed to scale, the sheet in it, the work in layer
		     colour and a cross on the head. -->
		<div class="rust">
			{#if bedW > 0 && bedH > 0}
				<svg
					class="bedje"
					viewBox="0 0 {bedW} {bedH}"
					role="img"
					aria-label={bedUitleg}
					bind:clientWidth={bedBreedtePx}
				>
					<rect class="vlak" x="0" y="0" width={bedW} height={bedH} vector-effect="non-scaling-stroke" />
					<!-- The sheet: where the material is. Without that frame the work floats
					     somewhere in a 610 mm bed and you cannot see whether it fits on your
					     offcut. -->
					{#if sheet && sheet.width_mm > 0 && sheet.height_mm > 0}
						<rect
							class="vel"
							x="0"
							y="0"
							width={sheet.width_mm}
							height={sheet.height_mm}
							vector-effect="non-scaling-stroke"
						/>
					{/if}
					<!-- Het werk zelf, in laagkleur. Eén schaal van Tats naar mm,
					     precies zoals het canvas het doet. -->
					{#if getekend.length}
						<g transform="scale({1 / perMm})">
							{#each getekend as vorm (vorm.id)}
								{#if vorm.image}
									<image
										href="/api/design/elements/{encodeURIComponent(vorm.id)}/image.png"
										x={vorm.image.x_mm * perMm}
										y={vorm.image.y_mm * perMm}
										width={vorm.image.width_mm * perMm}
										height={vorm.image.height_mm * perMm}
										preserveAspectRatio="none"
										opacity={vorm.stil ? 0.35 : 1}
									/>
								{:else}
									<path
										d={vorm.path}
										class="vorm"
										class:stil={vorm.stil}
										style:stroke={vorm.stil ? undefined : vorm.kleur}
									/>
								{/if}
							{/each}
						</g>
					{/if}
					{#if kop}
						<g class="kop">
							<line x1={kop[0]} y1="0" x2={kop[0]} y2={bedH} vector-effect="non-scaling-stroke" />
							<line x1="0" y1={kop[1]} x2={bedW} y2={kop[1]} vector-effect="non-scaling-stroke" />
							<circle cx={kop[0]} cy={kop[1]} r={Math.max(bedW, bedH) / 80} />
						</g>
					{/if}
				</svg>
			{/if}
			<dl class="feiten">
				<div><dt>{t('phone.bed')}</dt><dd class="mono">{bedW && bedH
						? `${Math.round(bedW)} × ${Math.round(bedH)} mm`
						: '—'}</dd></div>
				<div><dt>{t('phone.head')}</dt><dd class="mono">{position}</dd></div>
				<!-- What is there, in words. A grey dotted line among seven coloured ones
				     cannot be seen on a phone in the sun; the number can. -->
				<div>
					<dt>{t('phone.onTheBed')}</dt>
					<dd>
						{#if vormen.length === 0}
							{t('phone.nothing')}
						{:else}
							{t('preview.shapesBurn', { n: brandt })}{#if stille}<span class="stilnoot"
									>{t('phone.noLayer', { n: stille })}</span
								>{/if}
						{/if}
					</dd>
				</div>
			</dl>
			<!-- Gap P8: the same as the strip under the canvas (C2), in the same two
			     sentences. Outside the bed the head does not go; outside the sheet it
			     does, but there is no material. That difference decides whether you move
			     the work or replace your board, so it is two lines and not one "careful". -->
			{#if buitenstaanders.bed || buitenstaanders.vel}
				<div class="buiten" role="status">
					{#if buitenstaanders.bed}
						<p class="bedrand">
							<span class="teken" aria-hidden="true">!</span>
							{t('canvas.outsideBed', { n: buitenstaanders.bed })}
						</p>
					{/if}
					{#if buitenstaanders.vel}
						<p class="velrand">
							<span class="teken" aria-hidden="true">!</span>
							{t('canvas.outsideSheet', {
								n: buitenstaanders.vel,
								sheet: sheet ? sheet.name : t('canvas.theSheet')
							})}
						</p>
					{/if}
				</div>
			{/if}
			<!-- A bed without a job only said "Ready" at the top. That is a state, not an
			     answer: whoever looks here wants to know whether it is quiet because it is
			     finished, or quiet because something is wrong. -->
			<p class="waarom">
				{#if !connected}
					{t('phone.lastSeen')}
				{:else if machineState === 'unplugged'}
					{t('phone.unplugged')}
				{:else}
					{t('phone.idle')}
				{/if}
			</p>
		</div>
	{/snippet}

	{#snippet camerablok()}
		{#if beeldStuk}
			<p class="uitleg">{t('phone.cameraNoImage')}</p>
		{/if}
		{#if camera.state.available && !camAan}
			<button class="camknop" onclick={() => camera.start()} disabled={camera.busy}>
				{camera.busy
					? t('phone.cameraStarting')
					: beeldStuk
						? t('phone.cameraRetry')
						: t('phone.cameraOn')}
			</button>
		{:else if !camera.state.available}
			<p class="uitleg">{camera.state.reason ?? t('phone.noCamera')}</p>
		{/if}
		{#if camera.error}
			<p class="failure">{camera.error}</p>
		{/if}
	{/snippet}

	{#snippet fotolijst()}
		{#if gelukt}
			<p class="goed" role="status">{gelukt}</p>
		{/if}
		{#if lijst.length}
			<section class="rasters">
				<h2>
					{#if wachtend.length}
						{t('phone.waitingPhoto', { n: wachtend.length })}
					{:else}
						{t('phone.waitingAlign', { n: uitlijnen.length })}
					{/if}
				</h2>
				{#each lijst as grid (grid.id)}
					<label class="raster" class:gedaan={Boolean(grid.photo_path)}>
						<span class="naam">
							<span class="kop">{rasterNaam(grid)} · {bewerking(grid.operation)}</span>
							{#if grid.photo_path}
								<!-- Halfway, and that may be visible. The next step is not yours:
								     aligning is done on a big screen. -->
								<span class="detail rest">{t('phone.photoIn')}</span>
							{:else}
								<span class="detail mono">
									{gridSummary(grid)} · {stempel(grid.created_at)}
								</span>
							{/if}
						</span>
						<span class="knop" class:zacht={Boolean(grid.photo_path)}>
							{#if bezig === grid.id}
								{t('common.busy')}
							{:else if grid.photo_path}
								{t('phone.again')}
							{:else}
								{t('phone.takePhoto')}
							{/if}
						</span>
						<input
							type="file"
							accept="image/*"
							capture="environment"
							aria-label={grid.photo_path
								? t('phone.newPhotoOf', { id: grid.id })
								: t('library.photo.alt', { id: grid.id })}
							onchange={(e) => {
								const f = e.currentTarget.files?.[0];
								e.currentTarget.value = '';
								if (f) foto(grid.id, f);
							}}
						/>
					</label>
				{/each}
			</section>
		{/if}
	{/snippet}

	<div class="rol">
		{#if fotoEerst}
			<!-- There is a burned board on the bed and the machine is idle: this is what
			     you have the phone in your hand for. -->
			{@render fotolijst()}
			{#if standInEenRegel}
				<section class="standsectie">
					<button
						class="standrij"
						aria-expanded={bedOpen}
						onclick={() => (bedOpen = !bedOpen)}
					>
						<span class="dot {machineState}" aria-hidden="true"></span>
						<span class="naam">{t('phone.notBurning')}</span>
						<span class="stand mono">{position}</span>
						<span class="pijl" aria-hidden="true">{bedOpen ? '▴' : '▾'}</span>
					</button>
					{#if bedOpen}
						{@render bedkaart()}
					{/if}
				</section>
			{:else}
				<!-- Not simply idle: then the machine state is no longer a subclause. -->
				{@render bedkaart()}
			{/if}
			{#if camAan}
				{@render beeld()}
			{/if}
			{@render camerablok()}
		{:else}
			{#if camAan}
				{@render beeld()}
				{#if huidig}
					<div class="strook" role="progressbar" aria-valuenow={percent} aria-valuemin="0" aria-valuemax="100">
						<div class="vol" style="width: {percent}%"></div>
					</div>
				{/if}
			{:else if huidig}
				<!-- One ring carries the progress; the number inside it is the same story,
				     not a second one. -->
				<div class="podium">
					<svg class="ring" viewBox="0 0 200 200" role="progressbar"
						aria-valuenow={percent} aria-valuemin="0" aria-valuemax="100"
						aria-label={t('job.progressAria')}>
						<circle class="baan" cx="100" cy="100" r={STRAAL} />
						<circle
							class="voor"
							class:pauze={stil}
							cx="100" cy="100" r={STRAAL}
							stroke-dasharray="{OMTREK}"
							stroke-dashoffset={OMTREK * (1 - progress)}
						/>
					</svg>
					<div class="binnen">
						<span class="groot mono">{percent}<span class="pct">%</span></span>
						{#if stil}
							<span class="onder">{t('phone.paused')}</span>
						{:else if pauzeGevraagd}
							<span class="onder">{t('phone.pauseAsked')}</span>
						{:else if resterend !== null}
							<span class="onder">{t('phone.remaining', { time: formatDuration(resterend) })}</span>
							<span class="klaar">{t('phone.doneAt', { time: klaarOm })}</span>
						{:else}
							<span class="onder">{t('phone.burning')}</span>
						{/if}
					</div>
				</div>
				<div class="jobregel">
					<span class="titel">{jobLabel(huidig)}</span>
					<span class="mono muted">{huidig.steps_done} / {huidig.steps_total}</span>
				</div>
			{:else}
				{@render bedkaart()}
			{/if}

			{#if vraagNu}
				<!-- The occasion is here now: there is work in the machine. -->
				<NotificationCard {notifications} variant="aanleiding" onKlaar={() => (vraagWeg = true)} />
			{/if}

			{@render camerablok()}
			{@render fotolijst()}
		{/if}

		<!-- The fixed place where notifications go on and off, and where it says what
		     the browser makes of it. Collapsed that costs one line; blocked is a state
		     you see *and* undo here. -->
		<section class="meldsectie">
			<button
				class="meldrij"
				aria-expanded={instellingenOpen}
				onclick={() => (instellingenOpen = !instellingenOpen)}
			>
				<span class="naam">{t('notifications.title')}</span>
				<span class="stand {meldStand}">{meldStand}</span>
				<span class="pijl" aria-hidden="true">{instellingenOpen ? '▴' : '▾'}</span>
			</button>
			{#if instellingenOpen}
				<div class="meldbody">
					<NotificationCard {notifications} />
				</div>
			{/if}
		</section>

		<p class="elders">{t('phone.designElsewhere')}</p>
	</div>

	<!-- The emergency brake: fixed at the bottom, does not scroll, far apart. What
	     the machine refuses belongs here and must not disappear into the console. -->
	<div class="noodrem">
		{#if !connected}
			<!-- The only brake that still works is not on this screen. You should not
			     have to conclude that yourself from two grey buttons. -->
			<p class="failure" role="alert">
				{t('phone.stopOnMachine')}
				<button class="opnieuw" onclick={() => connection.retryNow()}>
					{connection.inSeconds > 0
						? t('phone.retry.auto', { seconds: connection.inSeconds })
						: t('phone.retry')}
				</button>
			</p>
		{/if}
		{#if control.error}
			<p class="failure" role="alert">{control.error}</p>
		{/if}
		<div class="knoppen">
			{#if stil}
				<button class="rem hervat" disabled={control.needsToken || !connected} onclick={() => control.resume()}>
					{t('phone.resume')}
				</button>
			{:else}
				<button class="rem pauze" disabled={!huidig || control.needsToken || !connected} onclick={pauzeer}>
					{pauzeGevraagd ? t('phone.pausing') : t('job.pause')}
				</button>
			{/if}
			<!-- Without a connection this tap arrives nowhere. A red button that looks
			     pressable and does nothing is the most dangerous thing on this screen:
			     you press, you walk away, and you believe it stops. -->
			<button
				class="rem stop"
				class:scherp={Boolean(huidig) && connected}
				disabled={control.needsToken || !connected}
				onclick={() => control.stop()}
			>
				{t('job.stop')}
			</button>
		</div>
	</div>
</div>

<style>
	.telefoon {
		display: flex;
		flex-direction: column;
		height: 100%;
		box-sizing: border-box;
		background: var(--surface-0);
		overflow: hidden;
	}
	header {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex: none;
		padding: var(--space-3);
	}
	.staat { font-weight: 600; font-size: var(--text-md); }
	.machine { margin-left: auto; color: var(--text-2); font-size: var(--text-xs); }
	.dot { width: 10px; height: 10px; border-radius: var(--radius-dot); background: var(--text-2); }
	.dot.ready { background: var(--ok); }
	/* Was `.dot.running`, and that class did not exist: MachineState is called
	   `busy`. The dot therefore stayed grey while the machine was burning. */
	.dot.busy { background: var(--accent); }
	.dot.paused { background: var(--warn-solid); }
	/* `unplugged` did not exist yet when this dot was written; without a rule it
	   fell back to grey and a dead port read as "nothing wrong". */
	.dot.unplugged { background: var(--warn-solid); }
	.dot.alarm { background: var(--danger-solid); }
	.dot.unplugged { background: var(--warn-solid); }
	.opnieuw {
		display: block;
		width: 100%;
		min-height: 44px;
		margin-top: var(--space-2);
		font: inherit;
		font-weight: 600;
		color: var(--text-1);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
	}
	/* Gat P8: dezelfde twee regels als onder het canvas, met dezelfde kleur én
	   hetzelfde teken. Kleur alleen mag het nooit dragen — deze telefoon ligt
	   naast de machine, vaak met de zon erop. */
	.buiten {
		display: grid;
		gap: var(--space-2);
		margin-top: var(--space-3);
	}
	.buiten p {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		margin: 0;
		padding-left: var(--space-2);
		font-size: var(--text-sm);
		line-height: 1.4;
		color: var(--text-1);
		border-left: 4px solid var(--danger-solid);
	}
	.buiten p.velrand { border-left-color: var(--warn-solid); }
	.buiten .teken {
		flex: none;
		width: 18px;
		height: 18px;
		margin-top: 1px;
		display: grid;
		place-items: center;
		border-radius: var(--radius-dot);
		font-weight: 700;
		font-size: var(--text-xs);
		color: var(--on-color);
		background: var(--danger-solid);
	}
	.buiten p.velrand .teken { background: var(--warn-solid); color: var(--void); }

	.waarom {
		margin: var(--space-3) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
		text-align: center;
	}

	/* Alleen dit deel scrollt; de kop en de noodrem staan stil. */
	.rol {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: 0 var(--space-3) var(--space-3);
	}

	.podium {
		flex: none;
		position: relative;
		border-radius: var(--radius-card);
		background: var(--stage);
		box-shadow: var(--lift-1);
		display: grid;
		place-items: center;
		overflow: hidden;
		aspect-ratio: 4 / 3;
		max-height: 40vh;
	}
	.podium img { width: 100%; height: 100%; object-fit: contain; }
	.ring { width: min(72vw, 240px); height: auto; transform: rotate(-90deg); }
	.ring .baan { fill: none; stroke: var(--surface-2); stroke-width: 10; }
	.ring .voor {
		fill: none;
		stroke: var(--accent);
		stroke-width: 10;
		stroke-linecap: round;
		transition: stroke-dashoffset var(--transition-panel);
	}
	.ring .voor.pauze { stroke: var(--warn-solid); }
	.binnen {
		position: absolute;
		display: grid;
		gap: var(--space-1);
		justify-items: center;
		text-align: center;
	}
	.groot { font-size: var(--text-display); line-height: 1; color: var(--text-1); font-variant-numeric: tabular-nums; }
	.pct { font-size: var(--text-lg); color: var(--text-2); }
	.binnen .onder { color: var(--text-1); font-size: var(--text-md); }
	.binnen .klaar { color: var(--text-2); font-size: var(--text-xs); }

	.strook { flex: none; height: 8px; border-radius: var(--radius-dot); background: var(--surface-2); overflow: hidden; }
	.strook .vol { height: 100%; background: var(--accent); transition: width var(--transition-panel); }

	.jobregel { flex: none; display: flex; align-items: baseline; gap: var(--space-2); }
	.jobregel .titel { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.muted { margin-left: auto; color: var(--text-2); font-size: var(--text-xs); }

	/* Rusttoestand: het bed op schaal met een kruis op de kop. Kost dezelfde
	   ruimte als het lege grijze vlak dat hier stond, en zegt iets. */
	.rust {
		flex: none;
		display: grid;
		gap: var(--space-3);
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		box-shadow: var(--lift-1);
	}
	/* Krap houden: de wachtende rasters zijn de reden dat je de telefoon pakt,
	   en die staan hieronder. Het bed hoeft alleen herkenbaar te zijn. */
	.bedje { width: 100%; height: auto; max-height: 30vh; display: block; }
	/* --bed is wit en de kaart is dat ook: in het lichte thema was het bed dan
	   onzichtbaar. --canvas-bg staat in beide thema's los van de kaart. */
	.bedje .vlak { fill: var(--canvas-bg); stroke: var(--line); stroke-width: 1; }
	.bedje .kop line { stroke: var(--accent); stroke-width: 1; stroke-dasharray: 4 4; opacity: 0.7; }
	.bedje .kop circle { fill: var(--accent); }
	/* De rand van het vel is de grens van je materiaal. `--line` haalt daar
	   tegen `--canvas-bg` te weinig om als grens te lezen; `--text-2` is
	   dezelfde keuze als in de pre-flight. */
	.bedje .vel {
		fill: var(--bed);
		stroke: var(--text-2);
		stroke-width: 1;
		stroke-dasharray: 5 4;
	}
	.bedje .vorm {
		fill: none;
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
		stroke-linejoin: round;
	}
	/* Zit in geen meebrandende laag: dezelfde taal als op het canvas en in de
	   pre-flight — grijs gestippeld betekent "de machine slaat dit over". */
	.bedje .vorm.stil {
		stroke: var(--text-2);
		stroke-width: 1;
		stroke-dasharray: 4 3;
	}
	.feiten .stilnoot { color: var(--text-2); font-weight: 400; }
	.feiten { margin: 0; display: grid; gap: var(--space-1); }
	.feiten > div { display: flex; justify-content: space-between; align-items: baseline; }
	.feiten dt { color: var(--text-2); }
	.feiten dd { margin: 0; font-weight: 500; }

	.camknop {
		flex: none;
		min-height: 48px;
		font: inherit;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.camknop:disabled { opacity: 0.5; }
	.uitleg { flex: none; margin: 0; color: var(--text-2); font-size: var(--text-xs); }
	.failure { margin: 0; color: var(--danger); font-size: var(--text-xs); }

	/* 12px tussen de rijen: elke rij is zelf een doel, en 8px was te dicht om
	   met een duim zonder te kijken de goede te raken. */
	.rasters { flex: none; display: grid; gap: var(--space-3); }
	.rasters h2 {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-2);
	}
	.raster {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: 60px;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
	}
	.raster .naam { min-width: 0; display: grid; gap: var(--space-1); }
	.raster .kop { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	/* Liever twee regels dan een afgekapte sweep: dit is precies het gegeven
	   waarmee je twee rasters van hetzelfde materiaal uit elkaar houdt. */
	.raster .detail { color: var(--text-2); font-size: var(--text-xs); line-height: 1.3; }
	.goed { flex: none; margin: 0; color: var(--ok); font-size: var(--text-xs); }
	/* Zag eruit als een tekstlink terwijl de hele rij het doel is. Nu een knop
	   in vorm, zodat de duim weet waar hij aan toe is. */
	.raster .knop {
		margin-left: auto;
		flex: none;
		white-space: nowrap;
		display: grid;
		place-items: center;
		min-height: 44px;
		padding: 0 var(--space-3);
		border: 1px solid var(--accent);
		border-radius: var(--radius-field);
		color: var(--accent);
		font-weight: 600;
	}
	.raster input { position: absolute; width: 0; height: 0; opacity: 0; }
	/* Foto binnen, nog niet uitgelijnd (gat P9). Blijft in de lijst staan omdat
	   de stap half af is, maar draagt niet de nadruk van een rij die nog iets
	   van jou wil: de rand is dezelfde, de knop is stil. */
	.raster.gedaan { background: var(--surface-0); }
	.raster .detail.rest { color: var(--text-2); font-size: var(--text-xs); line-height: 1.3; }
	.raster .knop.zacht {
		border-color: var(--line);
		color: var(--text-2);
		font-weight: 500;
	}

	/* De machinestand als één regel (besluit B13): dezelfde vorm als de
	   meldingenrij eronder, zodat "regel die opengaat" één ding betekent op dit
	   scherm. */
	.standsectie { flex: none; display: grid; gap: var(--space-2); }
	.standrij {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		min-height: 52px;
		padding: 0 var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
		font: inherit;
		text-align: left;
	}
	.standrij .dot { flex: none; }
	.standrij .naam { font-weight: 500; }
	.standrij .stand { margin-left: auto; font-size: var(--text-xs); color: var(--text-2); }
	.standrij .pijl { flex: none; color: var(--text-2); }

	.meldsectie { flex: none; display: grid; gap: var(--space-2); }
	.meldrij {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		min-height: 52px;
		padding: 0 var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
		text-align: left;
	}
	.meldrij .naam { font-weight: 500; }
	.meldrij .stand {
		margin-left: auto;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.meldrij .stand.aan { color: var(--ok); }
	/* Geblokkeerd is geen failure van de gebruiker maar wel iets wat je moet zien:
	   amber, want er valt iets te herstellen. */
	.meldrij .stand.geblokkeerd { color: var(--warn); }
	.meldrij .pijl { flex: none; color: var(--text-2); }
	.meldbody {
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
	}

	.elders {
		flex: none;
		/* `auto` boven: staat er weinig op het scherm — twee rasters en een
		   ingeklapte machinestand — dan zakt deze regel naar de onderrand van het
		   scrolgebied in plaats van een gat van 200 px achter te laten. Loopt de
		   inhoud vol, dan valt de auto-marge terug op nul en verandert er niets. */
		margin: auto 0 0;
		padding-top: var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
		text-align: center;
	}

	/* 24 px tussen de twee knoppen: tegengestelde gevolgen mogen niet naast
	   elkaar liggen als je met een duim mikt. */
	.noodrem {
		flex: none;
		display: grid;
		gap: var(--space-2);
		padding: var(--space-3);
		padding-bottom: max(var(--space-3), env(safe-area-inset-bottom));
		background: var(--surface-0);
		border-top: 1px solid var(--line);
	}
	.knoppen { display: flex; gap: var(--space-6); }
	.rem {
		flex: 1;
		min-height: 64px;
		font: inherit;
		font-size: var(--text-md);
		font-weight: 600;
		border-radius: var(--radius-card);
		border: 1px solid var(--line);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.rem:disabled { opacity: 0.4; }
	.rem.hervat { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
	/* Rustend is stop een omtrek, niet een rood vlak: een knalrode knop op een
	   scherm waar niets draait trekt de duim naar de enige actie die niets
	   oplost. Zodra er iets te stoppen valt, vult hij zich. */
	.rem.stop { background: transparent; border-color: var(--danger); color: var(--danger); }
	.rem.stop.scherp { background: var(--danger-solid); border-color: var(--danger-solid); color: var(--on-color); }

	/* De ring is een melding, geen versiering: de stand blijft, het naar de
	   stand toe glijden gaat eruit. */
	@media (prefers-reduced-motion: reduce) {
		.ring .voor,
		.strook .vol {
			transition: none;
		}
	}
</style>
