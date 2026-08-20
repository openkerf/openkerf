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
	 *    actief" zegt terwijl de kop dat al zei, is verspilde ruimte.
	 * 3. Wat je meet, toon je één keer. Voortgang stond hier drie keer en de
	 *    resterende tijd — het enige getal waar je op wacht — nul keer.
	 */
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
	import Verbinding from './Verbinding.svelte';
	import { verbinding } from '$lib/verbinding.svelte';
	import MeldingAlarm from './MeldingAlarm.svelte';
	import MeldingKaart from './MeldingKaart.svelte';
	import type { Bewaker, Meldingen } from '$lib/meldingen.svelte';
	import type { DesignStore } from '$lib/design.svelte';

	let {
		device,
		state: machineState,
		job,
		control,
		camera,
		meldingen,
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
		meldingen: Meldingen;
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
	// meldde "geen job actief", zonder knop om te hervatten. `currentJob` is de
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
	const BEWERKING: Record<string, string> = {
		snijden: 'snijden',
		'graveren-vector': 'graveren',
		'graveren-raster': 'rasteren',
		markeren: 'markeren'
	};

	/** "2026-08-11 19:33:37" → "11 aug 19:33". Zonder seconden, zonder jaar. */
	function stempel(waarde: string): string {
		const d = new Date(waarde.replace(' ', 'T'));
		if (Number.isNaN(d.getTime())) return waarde;
		// Niet toLocaleString: die zet er een komma tussen, en dan breekt de
		// regel juist daar af — "11 aug," op de ene regel, "19:51" op de volgende.
		const dag = d.toLocaleDateString('nl-NL', { day: 'numeric', month: 'short' });
		const tijd = d.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' });
		// Harde spatie: datum en tijd horen bij elkaar en mogen niet uiteenvallen.
		return `${dag} ${tijd}`.replace(/ /g, ' ');
	}

	/**
	 * De fotolijst kende maar twee standen: foto nodig, of weg (gat P9).
	 *
	 * Sinds er een uitlijning op de rasterrij staat is er een derde — foto
	 * binnen, nog niet uitgelijnd — en die verdween stil uit de lijst. Een
	 * halfafgemaakte stap hoort niet te verdwijnen: het bord ligt er nog, de
	 * preset is er nog niet, en niemand die alleen op zijn telefoon kijkt wist
	 * dat er nog iets te doen was.
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
			gelukt = 'Foto opgeslagen. De preset haal je er op de desktop uit.';
		} finally {
			bezig = null;
		}
	}

	/**
	 * De toestemmingsvraag krijgt hier zijn aanleiding van de machine zelf.
	 *
	 * Op de telefoon start je geen job (dat doet de desktop), dus is "er brandt
	 * nu iets" het moment waarop de vraag ergens op slaat. Bij een leeg bed
	 * vragen we niets; dan staat de instelling gewoon onderaan te wachten.
	 */
	let vraagWeg = $state(false);
	let vraagNu = $derived(meldingen.vragen && !vraagWeg && Boolean(huidig));
	/** De instelkaart uitgeklapt? Ingeklapt kost hij één regel. */
	let instellingenOpen = $state(false);

	/**
	 * De rangorde van dit scherm (besluit B13).
	 *
	 * Loopt er een job, dan is "hoe ver" de vraag en blijft de ring boven. Staat
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
		meldingen.toestemming === 'denied'
			? 'geblokkeerd'
			: meldingen.actief
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
	 * "kijken naast de machine" precies de ene vraag die je niet beantwoord
	 * krijgt: wát gaat er zo meteen gebrand worden.
	 *
	 * De paddata staat in Tats, net als op het canvas; één schaaltransform zet
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
	 * Het canvas meldt dit sinds C2 in twee zinnen onder de tekening; hier stond
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

<Verbinding brandt={running} />

<div class="telefoon">
	<!--
		Bovenaan en buiten het scrolgebied: een alarm dat je weg kunt scrollen is
		geen alarm (besluit B3). Bewust géén overlay: als vast blok dúwt hij de
		rest omlaag in plaats van de kop en de helft van de bedtekening af te
		dekken. Op 390 px kostte de zwevende versie 270 px aan afgesneden inhoud,
		en de machinestatus — juist bij een verbindingsalarm het eerste wat je wilt
		zien — was permanent onbereikbaar.
	-->
	<MeldingAlarm {bewaker} groot />
	<header>
		<span class="dot {machineState}" aria-hidden="true"></span>
		<span class="staat">{connected ? machineStateLabel(machineState) : 'Geen verbinding'}</span>
		<span class="machine mono">{device?.label ?? 'geen machine'}</span>
	</header>

	<!--
		De rangorde volgt wat je hier doet, niet hoe het scherm heet (besluit B13).

		Bij een lopende job blijft de voortgang boven: dan is "hoe ver" de vraag.
		Staat de machine stil en ligt er een gebrand bord te wachten, dan is er
		precies één ding te doen waarvoor je een telefoon in je hand moet hebben —
		een foto maken van iets dat op het bed ligt. Dat staat bovenaan, en de
		machinestand zakt terug tot één regel.

		De noodrem verhuist niet mee. Zie "De noodrem: een afweging met een prijs"
		in DESIGN-SYSTEM.md: blind vindbaar weegt zwaarder dan de dode knop.
	-->
	{#snippet beeld()}
		<!-- Camera: als je kunt kijken, kijk je. -->
		<div class="podium">
			<img src={camera.src} alt="Camerabeeld van het bed" onerror={() => (beeldStuk = true)} />
		</div>
	{/snippet}

	{#snippet bedkaart()}
		<!-- Wat er op het bed ligt: het bed op schaal, het vel erin, het werk in
		     laagkleur en een kruis op de kop. -->
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
					<!-- Het vel: waar het materiaal ligt. Zonder dat kader zweeft het
					     werk ergens in een bed van 610 mm en zie je niet of het op je
					     restje past. -->
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
				<div><dt>Bed</dt><dd class="mono">{bedW && bedH
						? `${Math.round(bedW)} × ${Math.round(bedH)} mm`
						: '—'}</dd></div>
				<div><dt>Kop</dt><dd class="mono">{position}</dd></div>
				<!-- Wat er ligt, in woorden. Een grijze stippellijn tussen zeven
				     gekleurde is op een telefoon in de zon niet te zien; het getal
				     erbij wel. -->
				<div>
					<dt>Op het bed</dt>
					<dd>
						{#if vormen.length === 0}
							niets
						{:else}
							<span class="mono">{brandt}</span>
							{brandt === 1 ? 'vorm brandt' : 'vormen branden'}{#if stille}<span class="stilnoot"
									>, <span class="mono">{stille}</span> in geen laag</span
								>{/if}
						{/if}
					</dd>
				</div>
			</dl>
			<!-- Gat P8: hetzelfde als de strook onder het canvas (C2), in dezelfde
			     twee zinnen. Buiten het bed komt de kop niet; buiten het vel komt
			     hij wel, maar ligt er geen materiaal. Dat verschil bepaalt of je
			     het werk verschuift of je plaat vervangt, dus het staat er als
			     twee regels en niet als één "let op". -->
			{#if buitenstaanders.bed || buitenstaanders.vel}
				<div class="buiten" role="status">
					{#if buitenstaanders.bed}
						<p class="bedrand">
							<span class="teken" aria-hidden="true">!</span>
							{buitenstaanders.bed === 1
								? 'Eén vorm ligt'
								: `${buitenstaanders.bed} vormen liggen`} buiten het bed — daar komt de kop niet.
						</p>
					{/if}
					{#if buitenstaanders.vel}
						<p class="velrand">
							<span class="teken" aria-hidden="true">!</span>
							{buitenstaanders.vel === 1
								? 'Eén vorm ligt'
								: `${buitenstaanders.vel} vormen liggen`} buiten {sheet ? sheet.name : 'het vel'} —
							daar ligt geen materiaal.
						</p>
					{/if}
				</div>
			{/if}
			<!-- Een bed zonder job zei alleen "Gereed" bovenin. Dat is een
			     toestand, geen antwoord: wie hier kijkt wil weten of het stil is
			     omdat het klaar is, of stil omdat er iets mis is. -->
			<p class="waarom">
				{#if !connected}
					Dit is de laatste stand die we gezien hebben.
				{:else if machineState === 'unplugged'}
					Er hangt geen machine aan de server. Controleer of hij aanstaat en
					of de kabel erin zit.
				{:else}
					Niets aan het branden. Een job start je op de desktop.
				{/if}
			</p>
		</div>
	{/snippet}

	{#snippet camerablok()}
		{#if beeldStuk}
			<p class="uitleg">De camera staat aan maar levert geen beeld. Kabel los?</p>
		{/if}
		{#if camera.state.available && !camAan}
			<button class="camknop" onclick={() => camera.start()} disabled={camera.busy}>
				{camera.busy ? 'Camera starten…' : beeldStuk ? 'Opnieuw proberen' : 'Camera aanzetten'}
			</button>
		{:else if !camera.state.available}
			<p class="uitleg">{camera.state.reason ?? 'Geen camera gekoppeld aan deze machine.'}</p>
		{/if}
		{#if camera.error}
			<p class="fout">{camera.error}</p>
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
						{wachtend.length}
						{wachtend.length === 1 ? 'testraster wacht' : 'testrasters wachten'} op een foto
					{:else}
						{uitlijnen.length}
						{uitlijnen.length === 1 ? 'testraster wacht' : 'testrasters wachten'} op uitlijnen
					{/if}
				</h2>
				{#each lijst as grid (grid.id)}
					<label class="raster" class:gedaan={Boolean(grid.photo_path)}>
						<span class="naam">
							<span class="kop">{rasterNaam(grid)} · {BEWERKING[grid.operation] ?? grid.operation}</span>
							{#if grid.photo_path}
								<!-- Halverwege, en dat mag je zien. De volgende stap is niet
								     de jouwe: uitlijnen doe je op een groot scherm. -->
								<span class="detail rest">foto binnen — uitlijnen op de desktop</span>
							{:else}
								<span class="detail mono">
									{gridSummary(grid)} · {stempel(grid.created_at)}
								</span>
							{/if}
						</span>
						<span class="knop" class:zacht={Boolean(grid.photo_path)}>
							{#if bezig === grid.id}
								bezig…
							{:else if grid.photo_path}
								Opnieuw
							{:else}
								Foto maken
							{/if}
						</span>
						<input
							type="file"
							accept="image/*"
							capture="environment"
							aria-label={grid.photo_path
								? `Nieuwe foto van testraster ${grid.id}`
								: `Foto van testraster ${grid.id}`}
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
			<!-- Er staat een gebrand bord op het bed en de machine is stil: dit is
			     waarvoor je de telefoon in je hand hebt. -->
			{@render fotolijst()}
			{#if standInEenRegel}
				<section class="standsectie">
					<button
						class="standrij"
						aria-expanded={bedOpen}
						onclick={() => (bedOpen = !bedOpen)}
					>
						<span class="dot {machineState}" aria-hidden="true"></span>
						<span class="naam">Niets aan het branden</span>
						<span class="stand mono">{position}</span>
						<span class="pijl" aria-hidden="true">{bedOpen ? '▴' : '▾'}</span>
					</button>
					{#if bedOpen}
						{@render bedkaart()}
					{/if}
				</section>
			{:else}
				<!-- Niet gewoon stil: dan is de machinestand geen bijzin meer. -->
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
				<!-- Eén ring draagt de voortgang; het getal erbinnen is hetzelfde
				     verhaal, niet een tweede. -->
				<div class="podium">
					<svg class="ring" viewBox="0 0 200 200" role="progressbar"
						aria-valuenow={percent} aria-valuemin="0" aria-valuemax="100"
						aria-label="Voortgang van de job">
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
							<span class="onder">gepauzeerd</span>
						{:else if pauzeGevraagd}
							<span class="onder">pauze gevraagd…</span>
						{:else if resterend !== null}
							<span class="onder">nog <span class="mono">{formatDuration(resterend)}</span></span>
							<span class="klaar">klaar om <span class="mono">{klaarOm}</span></span>
						{:else}
							<span class="onder">bezig met branden</span>
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
				<!-- De aanleiding is er nu: er ligt werk in de machine. -->
				<MeldingKaart {meldingen} variant="aanleiding" onKlaar={() => (vraagWeg = true)} />
			{/if}

			{@render camerablok()}
			{@render fotolijst()}
		{/if}

		<!-- De vaste plek waar meldingen aan en uit gaan, en waar staat wat de
		     browser ervan vindt. Ingeklapt kost dat één regel; geblokkeerd is een
		     toestand die je hier ziet én terugdraait. -->
		<section class="meldsectie">
			<button
				class="meldrij"
				aria-expanded={instellingenOpen}
				onclick={() => (instellingenOpen = !instellingenOpen)}
			>
				<span class="naam">Meldingen</span>
				<span class="stand {meldStand}">{meldStand}</span>
				<span class="pijl" aria-hidden="true">{instellingenOpen ? '▴' : '▾'}</span>
			</button>
			{#if instellingenOpen}
				<div class="meldbody">
					<MeldingKaart {meldingen} />
				</div>
			{/if}
		</section>

		<p class="elders">
			Ontwerpen doe je op de desktop — dit scherm houdt de machine in de gaten.
		</p>
	</div>

	<!-- De noodrem: vast onderin, scrollt niet mee, ver uit elkaar. Wat de
	     machine weigert hoort hier te staan en niet in de console te verdwijnen. -->
	<div class="noodrem">
		{#if !connected}
			<!-- De enige rem die nu nog werkt, staat niet op dit scherm. Dat mag je
			     niet zelf hoeven concluderen uit twee grijze knoppen. -->
			<p class="fout" role="alert">
				Geen verbinding — stoppen kan alleen met de knop op de machine.
				<button class="opnieuw" onclick={() => verbinding.nuProberen()}>
					Opnieuw proberen{verbinding.overSeconden > 0
						? ` (vanzelf over ${verbinding.overSeconden} s)`
						: ''}
				</button>
			</p>
		{/if}
		{#if control.error}
			<p class="fout" role="alert">{control.error}</p>
		{/if}
		<div class="knoppen">
			{#if stil}
				<button class="rem hervat" disabled={control.needsToken || !connected} onclick={() => control.resume()}>
					Hervat
				</button>
			{:else}
				<button class="rem pauze" disabled={!huidig || control.needsToken || !connected} onclick={pauzeer}>
					{pauzeGevraagd ? 'Pauze…' : 'Pauze'}
				</button>
			{/if}
			<!-- Zonder verbinding komt deze tik nergens aan. Een rode knop die
			     indrukbaar oogt en niets doet, is op dit scherm het gevaarlijkste
			     wat er is: je drukt, je loopt weg, en je gelooft dat het stopt. -->
			<button
				class="rem stop"
				class:scherp={Boolean(huidig) && connected}
				disabled={control.needsToken || !connected}
				onclick={() => control.stop()}
			>
				Stop
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
	/* Was `.dot.running`, en die klasse bestond niet: MachineState heet `busy`.
	   De stip bleef daardoor grijs terwijl de machine brandde. */
	.dot.busy { background: var(--accent); }
	.dot.paused { background: var(--warn-solid); }
	/* `unplugged` bestond nog niet toen deze stip geschreven werd; zonder regel
	   viel hij terug op grijs en las een dode poort als "niets aan de hand". */
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
	.fout { margin: 0; color: var(--danger); font-size: var(--text-xs); }

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
	/* Geblokkeerd is geen fout van de gebruiker maar wel iets wat je moet zien:
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
