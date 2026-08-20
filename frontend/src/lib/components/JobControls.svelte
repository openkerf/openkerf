<script lang="ts">
	import {
		phaseBody,
		phaseTitle,
		formatDuration,
		jobBusy,
		jobPhase,
		isStalled,
		remainingSeconds,
		PAUSE_KEY,
		STOP_KEY,
		type Device,
		type Job
	} from '$lib/api';
	import { apparaat } from '$lib/apparaat.svelte';
	import type { Controller, Position } from '$lib/control.svelte';
	import { verbinding } from '$lib/verbinding.svelte';
	import { inktOp, laagNummer, type Design } from '$lib/design.svelte';
	import JobPreview from './JobPreview.svelte';
	import Segmented from './Segmented.svelte';

	let {
		control,
		device,
		job,
		revisie = 0,
		preflight = $bindable(),
		onJog,
		onHome,
		onUnlock,
		onFocus,
		onFrame,
		colorFor,
		profile = null
	}: {
		control: Controller;
		device: Device | null;
		job: Job | null;
		/** Loopt op bij elke wijziging in het ontwerp; de schatting volgt hem. */
		revisie?: number;
		preflight: boolean;
		onJog?: (dxMm: number, dyMm: number) => void;
		onHome?: () => void;
		onUnlock?: () => void;
		onFocus?: (distanceMm: number) => void;
		/** De kop langs de omtrek sturen, zonder te branden. */
		onFrame?: () => void;
		/** Dezelfde laagkleur als het canvas en de lagenlijst tonen. */
		colorFor?: (operationId: string | null) => string;
		/** Wat dit machineprofiel zegt te kunnen; bepaalt wat er verschijnt. */
		profile?: { has_z: number; has_autofocus: number } | null;
	} = $props();

	// Gat J9: één bron voor "waar woont deze actie". Zie apparaat.svelte.ts.
	let balkdraagt = $derived(apparaat.bedieningInBalk);
	let actions = $derived(control.capabilities?.actions ?? null);
	let running = $derived(Boolean(job?.running));
	// Stilstaand, niet alleen "gepauzeerd volgens het statusveld": pauzeren zet
	// bij Lihuiyu `running` op false en meldt verder niets. Zonder dit stond hier
	// "Pauze" (uitgeschakeld) op een job die juist hervat moest worden.
	let paused = $derived(isStalled(job));
	let queued = $derived(device?.spooler.queue_length ?? 0);
	// Een lopende job is de reden dat starten niet mag; dat moet in de tooltip
	// staan, want een grijze knop zonder reden is een raadsel.
	let bezet = $derived(running || paused);
	let tokenDraft = $state('');
	let step = $state(10);
	type Warning = { code: string; text: string; ernst?: number };
	type Layer = {
		id: string | null;
		label: string;
		speed_mm_s: number | null;
		power_percent: number | null;
		passes: number;
		elements: number;
		source: string | null;
		/** Het materiaal waarvoor deze instelling gemaakt is — bekend zodra hij
		 *  uit een preset komt (besluit B1). */
		material_name?: string | null;
		thickness_mm?: number | null;
		warnings?: Warning[];
		/** Voert deze engine de laag daadwerkelijk uit? Zie `rasterUit`. */
		burns?: boolean;
	};
	type Bounds = {
		bed: { width_mm: number; height_mm: number } | null;
		sheet: { width_mm: number; height_mm: number } | null;
		work: { x_mm: number; y_mm: number; width_mm: number; height_mm: number } | null;
		outside_bed: number;
		outside_sheet: number;
		outside_bed_ids: string[];
		outside_sheet_ids: string[];
	};
	type SheetInfo = {
		name: string;
		width_mm: number;
		height_mm: number;
		material_name: string | null;
		thickness_mm: number | null;
	};
	let estimate = $state<{ seconds: number; parts: number } | null>(null);
	/**
	 * Wat er gebrand wordt, los van hoe lang het duurt.
	 *
	 * Eigen bron, want `/api/job/estimate` bouwt voor de klok het hele snijplan
	 * en dat duurt op een zwaar ontwerp minuten. De waarschuwing dat een laag
	 * een instelling van ánder materiaal draagt, is precies wat je vóór het
	 * starten moet zien; die hoort niet achter een tijdschatting te wachten.
	 */
	let overzicht = $state<{
		sheet?: SheetInfo | null;
		layers?: Layer[];
		bounds?: Bounds | null;
		engine?: { raster: boolean } | null;
	} | null>(null);
	let layers = $derived(overzicht?.layers ?? []);
	/**
	 * Het ontwerp voor de weergave erboven (besluit B8).
	 *
	 * Eigen ophaalslag en niet de store van de pagina: dit paneel krijgt hem
	 * niet doorgegeven, en vlak vóór het starten wil je sowieso zien wat er nú
	 * op het bed ligt en niet wat er stond toen het canvas voor het laatst
	 * ververste.
	 */
	let ontwerp = $state<Design | null>(null);

	// Wat de laag draagt tegenover waarin gebrand wordt. Dit is het laatste
	// moment waarop dat verschil nog iets kost dat je kunt terugdraaien.
	//
	// Eén regel per laag: twee bezwaren over dezelfde laag lazen als twee lagen,
	// omdat de naam er dan twee keer boven staat. En het zwaarste bezwaar eerst
	// — een gemeten instelling van het verkeerde materiaal is erger dan een
	// uitgerekende op het juiste, en dan moet die bovenaan staan.
	let mismatch = $derived(
		layers
			.filter((l) => l.burns !== false && l.warnings?.length)
			.map((l) => ({
				laag: l.label,
				ernst: Math.max(...(l.warnings ?? []).map((w) => w.ernst ?? 1)),
				tekst: (l.warnings ?? []).map((w) => w.text).join(' ')
			}))
			.sort((a, b) => b.ernst - a.ernst)
	);
	// Alleen wijzen als er iets te kiezen valt: bij bezwaren van gelijk gewicht
	// is "eerst dit" een willekeurige aanwijzing en dus ruis.
	let eersteWeegtZwaarder = $derived(
		mismatch.length > 1 && mismatch[0].ernst > mismatch[mismatch.length - 1].ernst
	);
	let velTekst = $derived.by(() => {
		const vel = overzicht?.sheet;
		if (!vel?.material_name) return null;
		const dikte = vel.thickness_mm;
		return dikte === null || dikte === undefined
			? vel.material_name
			: `${vel.material_name} · ${String(dikte).replace('.', ',')} mm`;
	});

	/**
	 * Past het op het bed, en past het op het vel? (gaten J5 en C2)
	 *
	 * Beide vragen worden door de server beantwoord en niet hier: die meet ze
	 * toch al voor het canvas en de telefoon, en drie plekken die het zelf
	 * uitrekenen kunnen het over de rand oneens worden. `bounds` hoort daarom
	 * in `/api/job/layers` en niet alleen in `/api/job/estimate` — anders
	 * verschijnt "valt buiten het bed" pas als de klok terug is, en dat kan op
	 * een zwaar ontwerp seconden duren.
	 *
	 * De melding zelf staat in `JobPreview`, direct onder de tekening waar de
	 * vorm te zien is waar het over gaat.
	 */
	let grenzen = $derived(overzicht?.bounds ?? null);

	/**
	 * Brandt deze engine rasterlagen?
	 *
	 * Nee, headless: de omzetter van rastervlak naar laserregels zit in de
	 * wxPython-GUI. De laag gooit tijdens het plannen zijn eigen vormen weg en
	 * levert nul cutcode. Dat mag geen verrassing zijn ná het branden, en de
	 * tijdschatting mag er geen seconden voor beloven.
	 */
	let rasterUit = $derived(overzicht?.engine?.raster === false);
	let blindeLagen = $derived(layers.filter((l) => l.burns === false));
	// Hele millimeters waar het kan; 0,5 mm blijft 0,5 mm.
	function maat(value: number): string {
		return (Math.round(value * 10) / 10).toString().replace('.', ',');
	}

	// Instellingen die niet gemeten zijn, verdienen een waarschuwing vóór het
	// materiaal in de machine ligt — niet erna.
	const ONZEKER: Record<string, string> = {
		geextrapoleerd: 'geëxtrapoleerd — niet gemeten',
		handmatig: 'handmatig ingesteld',
		geimporteerd: 'van iemand anders'
	};
	// Een laag die niet brandt, hoeft geen betrouwbare instellingen te hebben:
	// er wordt niets mee gedaan. Hem meetellen maakt van "3 lagen zijn niet
	// gemeten" een getal dat niet klopt met wat er straks gebeurt.
	let risky = $derived(layers.filter((l) => l.burns !== false && l.source !== 'testraster'));

	/**
	 * Waar de getallen van deze laag vandaan komen, in twee woorden.
	 *
	 * "Gemeten" boven een instelling die op ánder materiaal gemeten is, stelt
	 * gerust waar dat niet hoort: het meten klopt, het materiaal niet. Dan zegt
	 * deze kolom wat er wél aan de hand is, en de regel eronder waarom.
	 */
	function bron(layer: Layer): string {
		const codes = (layer.warnings ?? []).map((w) => w.code);
		if (codes.includes('ander-materiaal')) return 'ander materiaal';
		if (codes.includes('andere-dikte')) return 'andere dikte';
		if (layer.source === 'testraster') return 'gemeten';
		return ONZEKER[layer.source ?? ''] ?? 'niet gemeten';
	}
	let estimating = $state(false);
	let estimateTraag = $state(false);

	// De engine bouwt voor deze schatting het hele snijplan op. Op een zwaar
	// ontwerp duurde dat hier meer dan drie minuten, en de pre-flight bleef
	// intussen op een puntje staan. Een schatting mag nooit de reden zijn dat
	// je niet kunt starten, dus na tien seconden zeggen we het gewoon.
	const ESTIMATE_GEDULD = 10_000;

	// De schatting van de engine vóór het starten: de pre-flight toonde tot nu
	// toe alleen de tijd van een al lopende job, wat precies te laat is.
	//
	// Twee verzoeken, bewust niet één: het overzicht (lagen, materiaal,
	// bezwaren) komt meteen, de klok mag daarna komen. Andersom stond de
	// waarschuwing over verkeerd materiaal minutenlang achter een tijdschatting
	// te wachten op een zwaar ontwerp.
	async function loadEstimate() {
		estimating = true;
		estimateTraag = false;
		try {
			// Naast elkaar: de weergave en de lagentabel horen samen op het
			// scherm te verschijnen, niet de een een halve seconde na de ander.
			const [lagen, snapshot] = await Promise.all([
				fetch('/api/job/layers'),
				fetch('/api/design')
			]);
			overzicht = lagen.ok ? await lagen.json() : null;
			ontwerp = snapshot.ok ? await snapshot.json() : null;
		} catch {
			overzicht = null;
			ontwerp = null;
		}
		const traag = setTimeout(() => (estimateTraag = true), ESTIMATE_GEDULD);
		try {
			const response = await fetch('/api/job/estimate');
			estimate = response.ok ? await response.json() : null;
		} catch {
			estimate = null;
		} finally {
			clearTimeout(traag);
			estimating = false;
			estimateTraag = false;
		}
	}

	/**
	 * De schatting ophalen zolang de voorbereiding in beeld staat.
	 *
	 * Hij hing aan het `preflight`-vlaggetje, en dat ging maar één keer om. Nu
	 * staat het blok altijd open als er niets onderweg is, dus moet hij meelopen
	 * met het ontwerp — anders staat er straks een tijd van een tekening die je
	 * al vervangen hebt.
	 *
	 * Met een rem erop: elke vorm die je tekent geeft een signaal, en `plan` is
	 * niet gratis. 400 ms na de laatste wijziging is snel genoeg om vers te
	 * voelen en langzaam genoeg om niet mee te typen.
	 */
	let schatKlok: ReturnType<typeof setTimeout> | null = null;
	$effect(() => {
		// Bewust níet op `busyWithWork` kijken: die hangt via `leeg` aan de
		// schatting, en dan zou dit effect zijn eigen aanleiding zijn. De
		// wachtrijlengte zegt hetzelfde zonder de lus.
		const zichtbaar = (device?.spooler?.queue_length ?? 0) === 0;
		void revisie;
		if (!zichtbaar) {
			if (schatKlok) clearTimeout(schatKlok);
			return;
		}
		if (schatKlok) clearTimeout(schatKlok);
		schatKlok = setTimeout(loadEstimate, 400);
		return () => {
			if (schatKlok) clearTimeout(schatKlok);
		};
	});

	// Zonder token levert elke schrijfactie een 401 op. Een knop aanbieden die
	// gegarandeerd faalt is een lege belofte, dus die blokkeren we hier al.
	// Hetzelfde geldt voor een weggevallen server: dan komt er niets aan, en
	// een knop die er bedienbaar uitziet belooft iets wat niet gebeurt.
	let blocked = $derived(
		control.tokenProbleem || control.busy !== null || !verbinding.online
	);
	let blockedReason = $derived(
		!verbinding.online
			? 'Geen verbinding met OpenKerf — de opdracht komt niet aan'
			: control.tokenProbleem
				? 'Eerst een geldige token invullen'
				: undefined
	);

	// De kop verzetten terwijl er gebrand wordt, verpest op zijn best de job.
	let movingBlocked = $derived(
		!verbinding.online
			? 'Geen verbinding met OpenKerf — de kop beweegt hier niet van'
			: running
				? 'Kan niet tijdens een lopende job'
				: undefined
	);
	let bewegenUit = $derived(running || !verbinding.online);

	// ------------------------------------------- bewaarde posities (gat J6)

	let posities = $state<Position[]>([]);
	let bewaren = $state(false);
	let nieuweNaam = $state('');
	let huidigMm = $derived(device?.position.mm ?? null);

	async function ophalenPosities() {
		posities = await control.listPositions();
	}
	// Bij het openen van het paneel én na een machinewissel: posities horen bij
	// de machine, dus die van de vorige zijn hier onzin. Dat geldt net zo goed
	// voor het nulpunt (J12) en voor de bijstelling (J11) — allebei staan ze op
	// de machine en niet in de browser.
	$effect(() => {
		void device?.path;
		ophalenPosities();
		control.loadOrigin();
		if (control.canAdjust) control.loadAdjustment();
	});

	/** De twee grootheden die tijdens een job bijgesteld kunnen worden (J11). */
	const STELBAAR = [
		{ wat: 'power' as const, naam: 'Vermogen' },
		{ wat: 'speed' as const, naam: 'Snelheid' }
	];

	async function bewaar() {
		const naam = nieuweNaam.trim();
		if (!naam) return;
		if (await control.savePosition(naam)) {
			bewaren = false;
			nieuweNaam = '';
			await ophalenPosities();
		}
	}

	async function vergeet(naam: string) {
		if (await control.deletePosition(naam)) await ophalenPosities();
	}

	async function confirmStart() {
		if (await control.start()) preflight = false;
	}

	/**
	 * Valt er iets te branden?
	 *
	 * De pre-flight toonde bij een leeg bed opgewekt "Geschatte tijd 0:00", de
	 * volledige veiligheidschecklist en een groene "Nu starten". Dat is twee
	 * keer fout: je krijgt pas na het starten te horen dat er niets was, en je
	 * leert intussen om een veiligheidslijst weg te klikken die nergens over
	 * gaat. Een checklist die je went af te vinken, beschermt niemand meer.
	 *
	 * `parts` is het aantal onderdelen in het gebouwde snijplan; nul betekent
	 * dat de machine niets zou doen. Zolang de schatting nog loopt weten we het
	 * niet, en dan houden we onze mond.
	 */
	let leeg = $derived(!estimating && estimate !== null && estimate.parts === 0);

	/**
	 * De phase, uit één bron (`jobPhase` in `$lib/api.ts`).
	 *
	 * Dit paneel las hiervóór `job.running` en de bovenbalk de machinetoestand, en
	 * bij een job die gespoold was maar nog niet opgepakt (`status: "Waiting"`,
	 * `running: false`) waren die twee het oneens: de balk zette starten uit, dit
	 * paneel liet het aan staan. Eén tik hier spoolde dan een tweede job bovenop
	 * de eerste.
	 */
	let phase = $derived(jobPhase(device, job, leeg));
	let busyWithWork = $derived(jobBusy(phase));
	let voortgang = $derived.by(() => {
		const deel = job?.progress;
		if (deel === null || deel === undefined || !Number.isFinite(deel)) return null;
		// Een job die klaar is maar door de engine niet afgemeld wordt, staat op
		// 0,998; die tonen we als vol, want dat is wat er gebeurd is.
		return phase === 'done' ? 1 : Math.min(1, Math.max(0, deel));
	});
	let resterend = $derived(phase === 'done' ? 0 : remainingSeconds(job));
</script>

<div class="section">
	<!-- De kop zei "Bediening" en dat is waar: het zijn bedieningsorganen. Maar
	     het zegt niets over wat er nú aan de hand is, en dat is precies wat je op
	     dit tabblad komt halen. -->
	<h2 class="section-title">{busyWithWork || phase === 'done' ? 'De job' : 'Klaarmaken'}</h2>

	{#if control.tokenProbleem}
		<!-- De API is vanaf het netwerk bereikbaar; zonder token blijft alles
		     read-only. Ook bij een geweigerde token: die stond wél in de browser,
		     waardoor dit veld verdween en er geen weg terug was — elke actie
		     faalde met 401 en je kon nergens een andere token kwijt. -->
		<div class="token" class:afgewezen={control.rejected}>
			<label for="token">
				{control.rejected ? 'Deze token wordt geweigerd' : 'Token voor schrijfacties'}
			</label>
			<div class="token-row">
				<input id="token" type="password" bind:value={tokenDraft} placeholder="plak de token" />
				<button class="btn" onclick={() => control.saveToken(tokenDraft)}>Opslaan</button>
			</div>
			<p class="hint">
				{control.rejected
					? 'Kijk in het venster waarin de engine draait: daar staat de token die bij deze server hoort.'
					: 'De engine logt de token bij het starten van de API.'}
			</p>
		</div>
	{/if}

	{#if !busyWithWork && phase !== 'done'}
		<!--
			De voorbereiding staat er altijd, niet pas na een klik.

			Dit blok zat achter de knop "Job starten": je drukte, en het hele paneel
			werd vervangen door een overzicht — "alles gaat uit beeld", zoals de
			klacht luidde. Terwijl dit juist het beeld is waar je naar kijkt vóórdat
			je iets brandt. Het staat nu open zolang er niets onderweg is.

			De twee bewuste tikken blijven: VEILIGHEID.md legt vast dat geen enkele
			klik direct brandt. "Job starten" wapent, "Nu starten" vuurt — en anders
			dan hiervóór verdwijnt er bij die eerste tik niets uit beeld.
		-->
		<div class="preflight" class:niets={leeg}>
			<!-- "Geschatte tijd 0:00" boven een leeg bed leest als een job van nul
			     seconden in plaats van als geen job. Bij niets te doen zwijgt de
			     klok en spreekt de melding eronder. -->
			<!-- Eerst het werkstuk, dan pas de getallen erover (besluit B8). Wie
			     ziet dat er iets buiten het vel hangt, hoeft de tijd niet meer te
			     lezen — en op tablet en telefoon staat het canvas er niet naast. -->
			{#if !leeg}
				<!-- De meldingen over bed en vel horen bij de tekening en staan er
				     dus in, direct onder de vorm waar het over gaat (gaten J5 en
				     C2). Ze stonden hier als twee even rode kaarten op rij; dat
				     maakte "daar ligt geen materiaal" even ernstig als "daar komt de
				     kop niet", en dan weegt geen van beide nog. -->
				<JobPreview
					design={ontwerp}
					sheet={overzicht?.sheet ?? null}
					bounds={grenzen}
					{colorFor}
				/>
				<!-- De omzetter die een rastervlak naar laserregels rekent, zit in de
				     wxPython-versie van de engine. Ontbreekt hij, dan gooit de laag
				     tijdens het plannen zijn eigen vormen weg en komt er niets uit de
				     machine. Dezelfde woorden als de blokkade in de testrasterwizard:
				     wie ze daar gelezen heeft, herkent ze hier — en andersom. -->
				{#if rasterUit && blindeLagen.length}
					<p class="pf-geenraster" role="alert">
						<strong>Deze server kan rasterlagen niet branden.</strong>
						{blindeLagen.length === 1
							? `De laag "${blindeLagen[0].label}" levert`
							: `${blindeLagen.length} rasterlagen leveren`} niets — de omzetter
						van rastervlak naar laserregels zit in de wxPython-versie van de
						engine. De klok hieronder rekent er daarom nul voor. Maak er een
						graveer- of snijlaag van, of brand deze job vanuit de wxPython-UI.
					</p>
				{/if}
				<div class="pf-time">
					<span class="muted">Geschatte tijd</span>
					<span class="v mono">
						{#if estimating}
							<span class="rekent">rekent…</span>
						{:else}{formatDuration(estimate?.seconds ?? job?.estimate_seconds)}{/if}
					</span>
				</div>
				<!-- Waarín gebrand wordt, vlak boven de instellingen waarmee. Zonder
				     dat staat er een tabel met getallen zonder onderwerp. -->
				<!-- Altijd een regel, ook zonder materiaal. Niets zeggen leest als
				     "hoeft niet"; en dan draai je een preset van berken op acryl. -->
				<div class="pf-time vel" class:onbekend={!velTekst}>
					<span class="muted">Materiaal</span>
					<span class="v">{velTekst ?? 'niet ingevuld voor dit vel'}</span>
				</div>
					{#if control.origin}
						<!-- Gat J12: een nulpunt verplaatst het werk op het bed, en de
						     pre-flight is het laatste moment waarop je dat nog ziet. Het
						     staat er dus als eigen regel — zwijgen zou betekenen dat het
						     enige scherm vóór het branden niet vertelt wáár er gebrand
						     wordt. -->
						<div class="pf-time vel">
							<span class="muted">Nulpunt</span>
							<span class="v mono"
								>{maat(control.origin.x_mm)},&#8239;{maat(control.origin.y_mm)} mm</span
							>
						</div>
					{/if}
					<!-- Geen tweede regel met de jobafmeting: de weergave erboven zet
				     "werk 120 × 80 mm" al onder de tekening (besluit B8). Datzelfde
				     getal nog eens als eigen rij, negentig pixels lager, is geen
				     informatie maar ruis. Wat de weergave níet doet is het werk tegen
				     het bed houden — dat staat hieronder. -->
			{/if}
			{#if !leeg && device?.connection?.state === 'disconnected'}
				<!-- Starten mag: de engine zet de job in de wachtrij en verbindt
				     zodra de machine er is. Maar wie op "Nu starten" drukt en naar
				     een stille machine loopt, moet weten dat het wachten daaraan
				     ligt en niet aan de job. -->
				<p class="pf-warn strong">
					De machine meldt zich niet. Deze job gaat de wachtrij in en begint
					pas zodra de verbinding er is — zet hem aan of controleer de kabel.
				</p>
			{/if}
			{#if estimateTraag}
				<p class="pf-row">
					De engine bouwt het hele snijplan om dit te schatten; op een zwaar
					ontwerp duurt dat even. Starten kan gewoon — de machine wacht er
					niet op.
				</p>
			{/if}
			<!-- Alleen tonen als er iets in staat: "In wachtrij: 0" vlak vóór het
			     starten is de normale situatie, en dus geen mededeling. -->
			{#if queued > 0}
				<div class="pf-row">
					Er staat al <span class="mono">{queued}</span>
					{queued === 1 ? 'job' : 'jobs'} in de wachtrij; deze komt erachteraan.
				</div>
			{/if}

			<!-- Wat de machine gaat dóén. Tijd en aantal alleen is theater: een
			     laseraar controleert snelheid, vermogen en passes voordat hij
			     iets in de machine legt. -->
			{#if layers.length}
				<table class="pf-layers">
					<thead>
						<tr><th>Laag</th><th>mm/s</th><th>%</th><th>×</th><th>Bron</th></tr>
					</thead>
					<tbody>
						<!-- Op de index, niet op het label: twee operaties van hetzelfde
						     type heten allebei "Graveren", en een dubbele sleutel laat
						     Svelte de tabel verkeerd bijwerken. -->
						{#each layers as layer, i (i)}
							<tr>
								<td class="pf-name" title={layer.label}>
										<!-- Twee snijlagen heten allebei "Snijden"; de chip is het
										     enige wat ze uit elkaar houdt, en het is dezelfde kleur
										     als op het canvas en in de lagenlijst.

										     Gat J7: met het laagnummer erin. Het design system verbiedt
										     informatie die alleen in kleur zit, en van tien laagkleuren
										     botsen er twee bij deuteranopie. Het nummer komt uit
										     `laagNummer()` — dezelfde bron als de chip in het lagenpaneel
										     en het cijfer bij de vorm op het canvas, zodat ze niet uiteen
										     kunnen lopen. -->
										{#if colorFor}
											{@const nummer = laagNummer(ontwerp, layer.id)}
											<!-- Met `aria-hidden` eraf hoort een schermlezer anders een
											     kaal cijfer vóór de laagnaam: "1 Snijden". `role="img"`
											     met een naam maakt er "Laag 1, Snijden" van; zonder rol
											     negeren de meeste schermlezers een aria-label op een
											     span. Zonder nummer is de chip alleen kleur en dus
											     decoratie — die blijft verborgen. -->
											{#if nummer === null}
												<span class="chip mono" style:background={colorFor(layer.id)} aria-hidden="true"
												></span>
											{:else}
												<span
													class="chip mono genummerd"
													style:background={colorFor(layer.id)}
													style:color={inktOp(colorFor(layer.id))}
													role="img"
													aria-label="Laag {nummer}"
												>{nummer}</span>
											{/if}
										{/if}{layer.label}
									</td>
								<!-- Een laag die deze engine niet uitvoert, mag geen snelheid en
								     vermogen tonen alsof er iets gaat gebeuren. Ook de herkomst
								     verdwijnt: waar de getallen vandaan komen doet niet ter
								     zake als ze niet gebruikt worden. -->
								{#if layer.burns === false}
									<td class="pf-blind" colspan="4">brandt niet</td>
								{:else}
									<td class="mono">{layer.speed_mm_s ?? '—'}</td>
									<td class="mono">{layer.power_percent ?? '—'}</td>
									<td class="mono">{layer.passes}</td>
									<!-- "gemeten" in rustige tekst boven een instelling die op
									     ánder materiaal gemeten is, stelt gerust waar dat niet
									     hoort. De regel eronder zegt wat eraan schort; hier
									     zegt de kleur alvast dát er iets is. -->
									<td class:unsure={layer.source !== 'testraster' || (layer.warnings?.length ?? 0) > 0}>
										{bron(layer)}
									</td>
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
				<!-- Eerst het concrete bezwaar, dan het algemene. Een instelling van
				     ánder materiaal is geen kwestie van vertrouwen maar van
				     verkeerde plaat: dat hoort bovenaan te staan en met naam.

				     Binnen de lijst weegt niet alles even zwaar. Een gemeten waarde
				     van het verkeerde materiaal staat boven een uitgerekende waarde
				     op het juiste, en als die twee naast elkaar staan zegt het
				     merkje welke je eerst oplost. -->
				{#if mismatch.length}
					<ul class="pf-mismatch" role="alert">
						{#each mismatch as melding, i (i)}
							<li class:licht={melding.ernst < 2}>
								{#if i === 0 && eersteWeegtZwaarder}
									<span class="eerst">Eerst</span>
								{/if}<strong>{melding.laag}</strong> — {melding.tekst}
							</li>
						{/each}
					</ul>
				{/if}
				{#if risky.length}
					<p class="pf-warn strong">
						{risky.length === 1 ? 'Eén laag gebruikt' : `${risky.length} lagen gebruiken`}
						instellingen die niet met een testraster gemeten zijn. Op onbekend
						materiaal: eerst een proefje op een restje.
					</p>
				{/if}
			{/if}

			{#if leeg}
				<!-- Geen checklist, geen startknop: er is niets om na te lopen. -->
				<div class="pf-leeg">
					<strong>Er is niets om te branden</strong>
					<p>
						Het bed is leeg, of alles wat erop staat zit in een laag die niet
						meebrandt. Teken of importeer iets, geef het een laag, en kom
						hierna terug.
					</p>
				</div>
				<!-- Hier stond "Terug naar het ontwerp", en dat was de enige uitweg
				     uit een overzicht dat het paneel had overgenomen. Nu neemt het
				     paneel niets over, dus is er ook niets om uit terug te keren. -->
			{:else}
			<!-- Dit stond als tweede geel blok onder de risicomelding. Twee
			     waarschuwingen op rij van dezelfde kleur devalueren elkaar: de
			     routinecontrole maakte de échte melding onzichtbaar. Nu neutraal
			     en als lijst, want je loopt hem af. -->
			<div class="pf-check">
				<span class="pf-kop">Loop dit even na</span>
				<ul>
					<li>Deksel dicht</li>
					<li>Afzuiging en air assist aan</li>
					<li>Werkstuk ligt vast en vlak</li>
				</ul>
			</div>

			<!--
				De knoppen plakken onderaan het paneel.

				Sinds de voorbereiding altijd openstaat, is de kolom langer dan het
				paneel hoog is (gemeten: 1 427 px inhoud in 788 px). Zonder deze plak
				stond de startknop onder de vouw — de primaire handeling buiten beeld,
				en dat is precies wat deze ronde moest oplossen, niet veroorzaken.

				Het kader tonen staat op dezelfde regel: het is de laatste controle
				vóór dezelfde knop, dus hoort het ernaast en niet drie blokken hoger.
			-->
			<div class="pf-plak">
				{#if preflight}
					<!-- Twee bewuste tikken, op dezelfde plek: VEILIGHEID.md legt vast dat
					     geen enkele klik direct brandt. De eerste wapent, de tweede vuurt —
					     en anders dan hiervóór verdwijnt er bij die eerste tik niets uit
					     beeld. -->
					<button class="btn" onclick={() => (preflight = false)}>Annuleren</button>
					<button
						class="btn primary groot"
						onclick={confirmStart}
						disabled={control.busy !== null || !verbinding.online}
						title={verbinding.online ? undefined : blockedReason}
					>
						{control.busy === 'start' ? 'Bezig…' : 'Nu starten'}
					</button>
				{:else}
					{#if onFrame}
						<button
							class="btn"
							disabled={control.busy !== null || running}
							title="De kop langs de omtrek van je werk sturen — de laser blijft uit"
							onclick={() => onFrame?.()}
						>
							Kader tonen
						</button>
					{/if}
					<button
						class="btn primary groot"
						disabled={!actions?.start || blocked}
						title={blockedReason}
						onclick={() => (preflight = true)}
					>
						Job starten{#if !estimating && (estimate?.seconds ?? job?.estimate_seconds)}
							<span class="pf-startmaat"
								>{formatDuration(estimate?.seconds ?? job?.estimate_seconds)}</span
							>{/if}
					</button>
				{/if}
			</div>
			{/if}
		</div>
	{:else}
		<!--
			Het voortgangsblok.

			Hier stonden vier knoppen (starten, pauze, wachtrij legen, stop) plus
			vier regels uitleg over sneltoetsen, en dat stond er ongeacht wat de
			machine deed. Drie van de vier waren dood zolang er niets liep, en
			zodra er wél iets liep stond de enige informatie die dan iets betekent
			— de voortgang — op 700px, onder de jogknoppen, buiten beeld.

			Nu leidt de phase (`jobPhase` in `$lib/api.ts`): wat er nu aan de hand is
			staat bovenaan, met de knoppen die op dít moment iets doen. De
			sneltoetsen staan op de knoppen zelf, want dat is waar je ze leert.
		-->
		<div class="nu" class:brandt={phase === 'burning'} class:pauze={phase === 'paused'}>
			<div class="nu-kop">
				<span class="nu-phase">{phaseTitle(phase)}</span>
				{#if job}
					<span class="nu-job mono" title={job.label}>{job.label}</span>
				{/if}
			</div>

			{#if voortgang !== null}
				<!-- De balk en het percentage horen bij elkaar en staan dus op één
				     regel; de tijden eronder in dezelfde kolommen als altijd. -->
				<div class="nu-balk" role="progressbar" aria-valuenow={Math.round(voortgang * 100)} aria-valuemin="0" aria-valuemax="100" aria-label="Voortgang van de job">
					<span class="nu-vol" style="width: {Math.round(voortgang * 1000) / 10}%"></span>
				</div>
				<div class="nu-cijfers mono">
					<span class="nu-pct">{Math.round(voortgang * 100)}%</span>
					{#if job?.steps_total}
						<span class="nu-stap">{job.steps_done ?? 0} / {job.steps_total} stappen</span>
					{/if}
					{#if (job?.loops ?? 1) > 1}
						<span class="nu-pass">pass {(job?.loops_executed ?? 0) + 1} van {job?.loops}</span>
					{/if}
				</div>
				<div class="nu-tijd">
					<span>{formatDuration(job?.elapsed_seconds ?? null)} verstreken</span>
					{#if resterend !== null}<span class="nu-rest">nog {formatDuration(resterend)}</span>{/if}
				</div>
			{/if}

			<p class="nu-uitleg">{phaseBody(phase)}</p>

			<div class="nu-acties">
				{#if paused}
					<button
						class="btn primary"
						disabled={!actions?.resume || blocked}
						title="{blockedReason ?? 'Verder waar de kop gebleven was'} · {PAUSE_KEY}"
						onclick={() => control.resume()}
					>Hervatten</button>
				{:else}
					<!-- Op de phase en niet op `job.running`: een job die gespoold is maar
					     nog niet opgepakt staat op `running: false`, en dan bood de
					     bovenbalk pauze aan terwijl deze knop uit stond. `pause` is een
					     realtime-commando; hij landt zodra de machine begint. -->
					<button
						class="btn"
						disabled={!actions?.pause || !busyWithWork || blocked}
						title={busyWithWork
							? `${blockedReason ?? 'De kop stilzetten zonder de job te verliezen'} · ${PAUSE_KEY}`
							: 'Er loopt niets om te pauzeren'}
						onclick={() => control.pause()}
					>Pauze</button>
				{/if}
				<span class="nu-rek"></span>
				<!-- Stoppen houdt zijn eigen ruimte, links van pauze weg: een mistik
				     hier kost het werkstuk. Zie DESIGN-SYSTEM v2, "Touch als
				     eersteklas input". -->
				<button
					class="btn danger stop"
					class:dood={!verbinding.online}
					disabled={!actions?.stop || control.tokenProbleem || !verbinding.online}
					title={!verbinding.online
						? 'Geen verbinding met OpenKerf — deze knop komt niet aan. Stoppen kan nu alleen met de noodstop op de machine.'
						: `${blockedReason ?? 'Job direct afbreken'} · ${STOP_KEY}`}
					onclick={() => control.stop()}
				>
					{#if verbinding.online}Stop{:else}Stop <strong>op de machine</strong>{/if}
				</button>
			</div>

			<!-- Zodra er íets in de wachtrij staat. Eerst stond hier `queued > 1`, en
			     dan was met precies één job in de rij de wachtrij niet te legen — een
			     handeling die verdween in plaats van verhuisde. -->
			{#if queued > 0}
				<button
					class="btn subtle wachtrij"
					disabled={!actions?.clear_queue || queued === 0 || blocked}
					title={queued === 0 ? 'De wachtrij is al leeg' : blockedReason}
					onclick={() => control.clearQueue()}
				>
					Wachtrij legen ({queued})
				</button>
			{/if}

			<!-- Gat J4, ingekort. De toetsen staan nu in de tooltips van de knoppen
			     hierboven; wat een tooltip niet kan zeggen is dat ze buiten dit
			     venster niet werken, en dat is precies het deel dat je op het
			     verkeerde moment ontdekt. -->
			<p class="toetsen">
				<kbd>{PAUSE_KEY}</kbd> en <kbd>{STOP_KEY}</kbd> werken overal in de app,
				zolang dit venster voorop staat — daarbuiten kan een browser geen toetsen
				ontvangen.
			</p>
		</div>

	{/if}

	{#if !control.tokenProbleem}
		<!--
			De machinebediening: bewegen, naar een punt, het nulpunt, bijstellen.

			Dit is klaarmaak-werk. Het stond boven de voortgang en nam bij een
			lopende job het hele zichtbare paneel in — terwijl de knoppen er dan
			juist uit staan, want je jogt niet met een brandende laser. Nu staat het
			ónder wat er nu gebeurt, en klapt het dicht zodra er werk onderweg is.
			Dicht en niet weg: hij moet er zijn zodra je hem weer nodig hebt, en een
			blok dat verdwijnt leer je niet terug te vinden.
		-->
		<details class="machinevouw" open={!busyWithWork}>
			<summary>
				Machine bedienen
				{#if busyWithWork}<span class="waarom">— niet tijdens een job</span>{/if}
			</summary>
		<div class="motion">
			<span class="rot-label">Bewegen</span>
			<!-- Omgekeerde T, zoals de pijltjes op een toetsenbord: ↑ boven ↓,
			     met ← en → ernaast. Home staat ernaast en niet in het midden,
			     want dat is geen richting. -->
			<div class="pad" class:metz={control.capabilities?.motion?.focus}>
				<button class="jog up" aria-label="Naar boven" disabled={bewegenUit} title={movingBlocked} onclick={() => onJog?.(0, -step)}>↑</button>
				<button class="jog left" aria-label="Naar links" disabled={bewegenUit} title={movingBlocked} onclick={() => onJog?.(-step, 0)}>←</button>
				<button class="jog down" aria-label="Naar beneden" disabled={bewegenUit} title={movingBlocked} onclick={() => onJog?.(0, step)}>↓</button>
				<button class="jog right" aria-label="Naar rechts" disabled={bewegenUit} title={movingBlocked} onclick={() => onJog?.(step, 0)}>→</button>
				<button class="jog home" disabled={bewegenUit} title={movingBlocked} onclick={() => onHome?.()}>Home</button>
				{#if control.capabilities?.motion?.focus}
					<!-- De Z-as staat in dezelfde pad als X en Y: het is dezelfde
					     handeling met een derde richting, en hij volgt dezelfde
					     stapgrootte. -->
					<button
						class="jog zup"
						disabled={bewegenUit}
						title={movingBlocked ?? `Kop ${step} mm omhoog`}
						onclick={() => onFocus?.(-step)}
					>Z&nbsp;↑</button>
					<button
						class="jog zdown"
						disabled={bewegenUit}
						title={movingBlocked ?? `Kop ${step} mm omlaag`}
						onclick={() => onFocus?.(step)}
					>Z&nbsp;↓</button>
				{/if}
			</div>
			<div class="steps">
				<Segmented
					label="Stapgrootte"
					mono
					bind:value={step}
					options={[0.1, 1, 10, 50].map((size) => ({ value: size, label: `${size} mm` }))}
				/>
				<button class="rot" disabled={bewegenUit} title={movingBlocked} onclick={() => onUnlock?.()}>
					Ontgrendelen
				</button>
			</div>

			<!-- Naar een punt in plaats van een richting (gat J6). LightBurn's
			     Move-venster heeft "Go to Origin" en opgeslagen posities; wie een
			     mal op het bed heeft liggen, jogt die hoek anders elke sessie
			     opnieuw bij elkaar. -->
			{#if control.capabilities?.motion?.move}
				<div class="punten">
					<span class="rot-label">Naar een punt</span>
					<div class="puntrij">
						<button
							class="rot"
							disabled={bewegenUit}
							title={movingBlocked ?? 'De kop naar 0,0 van het bed sturen'}
							onclick={() => control.moveTo(0, 0)}
						>
							Naar oorsprong
						</button>
						{#each posities as plek (plek.name)}
							<span class="plek">
								<button
									class="rot naam"
									disabled={bewegenUit}
									title={movingBlocked ??
										`Naar ${maat(plek.x_mm)}, ${maat(plek.y_mm)} mm`}
									onclick={() => control.moveTo(plek.x_mm, plek.y_mm)}
								>
									{plek.name}
									<!-- De coördinaten erbij, niet alleen in de tooltip: op een
									     aanraakscherm bestaat hover niet, en dan is een bewaarde
									     positie een naam zonder plek. LightBurn zet ze in een eigen
									     kolom; hier is daar geen kolom voor, dus staan ze gedempt
									     achter de naam in dezelfde chip. -->
									<span class="coord mono">{maat(plek.x_mm)},&#8239;{maat(plek.y_mm)}</span>
								</button>
								<!-- Weggooien zit in de knop zelf, niet in een menu: het zijn
								     er hooguit twaalf en je doet het zelden. -->
								<button
									class="rot weg"
									aria-label="{plek.name} vergeten"
									title="Deze positie vergeten"
									onclick={() => vergeet(plek.name)}
								>×</button>
							</span>
						{/each}
					</div>
					{#if bewaren}
						<div class="bewaarrij">
							<!-- svelte-ignore a11y_autofocus -->
							<input
								class="naamveld"
								placeholder="bijv. hoek van de mal"
								maxlength="40"
								autofocus
								bind:value={nieuweNaam}
								onkeydown={(e) => {
									if (e.key === 'Enter') bewaar();
									if (e.key === 'Escape') bewaren = false;
								}}
							/>
							<button class="rot" onclick={bewaar} disabled={!nieuweNaam.trim()}>
								Bewaren
							</button>
							<button class="rot" onclick={() => (bewaren = false)}>Annuleren</button>
						</div>
					{:else}
						<button
							class="rot"
							disabled={bewegenUit || huidigMm === null}
							title={huidigMm === null
								? 'Deze machine meldt geen positie, dus er valt niets te bewaren'
								: `Bewaar ${maat(huidigMm[0])}, ${maat(huidigMm[1])} mm onder een naam`}
							onclick={() => {
								nieuweNaam = '';
								bewaren = true;
							}}
						>
							Deze plek bewaren
						</button>
					{/if}
				</div>
			{/if}
			<!-- Het nulpunt (gat J12). LightBurn heeft Set Origin / Clear Origin /
			     Go to Origin; bij ons was "Naar oorsprong" letterlijk 0,0 van het
			     bed en was er geen manier om een eigen nulpunt te leggen. Dat is
			     dagelijks werk: de restplank ligt waar hij ligt, en je wil je hele
			     tekening niet verslepen om hem erop te krijgen.

			     Bewust een eigen blokje onder "Naar een punt" en niet ertussen: de
			     bewaarde posities zeggen "ga daarheen", dit zegt "reken daarvandaan".
			     Tussen de plekken zou hij als nóg een plek lezen. -->
			{#if control.capabilities?.motion?.move}
				<div class="nulpunt" class:gezet={control.origin !== null}>
					<span class="rot-label">Nulpunt van het werk</span>
					{#if control.origin}
						<!-- Het getal staat er altijd bij. Een nulpunt dat je niet kunt
						     aflezen is een instelling die stilletjes je werk verplaatst,
						     en dat is precies de verrassing die een laser duur maakt. -->
						<p class="nulstand">
							<span class="mono"
								>{maat(control.origin.x_mm)},&#8239;{maat(control.origin.y_mm)} mm</span
							>
							— wat je op 0,0 tekent, brandt hier. Het vel schuift mee: het nulpunt
							is de hoek van het materiaal dat erin ligt.
						</p>
					{:else}
						<p class="hint">
							Staat uit: het werk brandt op de coördinaten waarop je het tekende.
						</p>
					{/if}
					<div class="puntrij">
						<button
							class="rot"
							disabled={bewegenUit || huidigMm === null}
							title={huidigMm === null
								? 'Deze machine meldt geen positie, dus er valt geen nulpunt vast te leggen'
								: `Leg het nulpunt op ${maat(huidigMm[0])}, ${maat(huidigMm[1])} mm — waar de kop nu staat`}
							onclick={() => control.setOrigin()}
						>
							{control.origin ? 'Hier opnieuw' : 'Hier het nulpunt'}
						</button>
						{#if control.origin}
							<button
								class="rot"
								disabled={bewegenUit}
								title={movingBlocked ?? 'De kop naar het nulpunt sturen'}
								onclick={() =>
									control.origin && control.moveTo(control.origin.x_mm, control.origin.y_mm)}
							>
								Naar nulpunt
							</button>
							<button
								class="rot"
								title="Terug naar het nulpunt van de machine zelf"
								onclick={() => control.clearOrigin()}
							>
								Wissen
							</button>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Bijstellen tijdens een lopende job (gat J11).
			     LightBurn heeft hier twee kolommen "Adjust Speed" en "Adjust Power"
			     waarmee je een job rédt in plaats van hem opnieuw doet: je ziet dat
			     het te donker wordt en draait tien procent terug zonder te stoppen.

			     Alleen zichtbaar als de driver het kan, en dat is geen netheid maar
			     noodzaak: alleen grbl heeft realtime overrides (0x90/0x99), de Ruida
			     zet snelheid en vermogen per cut-segment uit de settings. Een knop
			     die niets doet naast een brandende laser is erger dan geen knop.
			     Zie FEATURE-GAPS J11. -->
			{#if control.canAdjust}
				<div class="bijstellen">
					<span class="rot-label">Bijstellen tijdens de job</span>
					{#each STELBAAR as as (as.wat)}
						{#if control.capabilities?.adjust?.[as.wat]}
							{@const stand = control.adjust[as.wat] ?? 1}
							<div class="stelrij">
								<span class="stelnaam">
									{as.naam}
									<!-- Alleen het getal in mono; "zoals ontworpen" is een zin en
									     die staat in een cijferletter vreemd afgemeten. -->
									<span class="stelwaarde" class:mono={stand !== 1}
										>{stand === 1
											? 'zoals ontworpen'
											: `${stand > 1 ? '+' : '−'}${Math.abs(
													Math.round((stand - 1) * 100)
												)}%`}</span
									>
								</span>
								<div class="stelknoppen">
									{#each [-0.1, -0.01, 0.01, 0.1] as stap (stap)}
										<button
											class="rot stel"
											disabled={!verbinding.online}
											title="{stap > 0 ? 'Meer' : 'Minder'} {as.naam.toLowerCase()}"
											onclick={() => control.setAdjustment(as.wat, stand + stap)}
											>{stap > 0 ? '+' : '−'}{Math.abs(Math.round(stap * 100))}%</button
										>
									{/each}
									<button
										class="rot stel terug"
										disabled={!verbinding.online || stand === 1}
										title="Terug naar wat de laag zegt"
										onclick={() => control.setAdjustment(as.wat, 1)}>Terug</button
									>
								</div>
							</div>
						{/if}
					{/each}
					<p class="hint">
						Dit schaalt wat de machine nú doet. De laag houdt zijn eigen
						instelling — die kan uit een preset komen, en dan is hij bewijs.
					</p>
				</div>
			{/if}
			{#if !control.capabilities?.motion?.focus && profile?.has_z}
				<!-- Het profiel zegt dat deze machine een Z-as heeft, maar de
				     driver van de engine kent er geen commando voor. Dat is geen
				     ontbrekende knop maar ontbrekende ondersteuning; zeg dat. -->
				<p class="hint">
					Dit profiel meldt een Z-as, maar de driver van deze machine kent
					geen commando om de kop te verzetten. Scherpstellen doe je met de
					hand.
				</p>
			{/if}
			{#if profile?.has_autofocus}
				<!-- MeerK40t kent geen commando om een autofocus te starten. Een
				     knop die in plaats daarvan iets ánders doet, is erger dan geen
				     knop — dus zeggen we waar hij wél zit, in één zin. -->
				<p class="hint">Autofocus start je op de machine zelf.</p>
			{/if}
		</div>
		</details>
	{/if}

	{#if actions && !actions.pause}
		<p class="hint">
			Dit apparaat kent geen pauze/hervatten — die commando's komen van de device-service.
		</p>
	{/if}

	<!-- De foutmelding staat nu in de statusbalk, op elk tabblad zichtbaar.
	     Hier nóg een keer zou hem tweemaal tonen zodra je toevallig in Job
	     staat. -->
</div>

<style>
	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: 0 0 var(--space-2);
	}
	/* Onder 1200px staan starten en pauzeren in de bovenbalk en verdwijnt dit
	   blok grotendeels (zie `.dubbel` verderop). Maar een aanraakscherm kan
	   bréder zijn dan 1200, en daar stond alles op 8px — onder de 12px die
	   DESIGN-SYSTEM als ondergrens voor raakdoelen stelt.

	   Rijen tellen net zo hard als kolommen: "Pauze" en "Wachtrij legen" staan
	   ónder elkaar en zijn tijdens een job allebei bruikbaar, en dat tweede
	   knopje gooit je hele wachtrij weg. Dus `gap`, niet `column-gap`.
	   (Startknop en pauzeknop naast elkaar zijn overigens nooit tegelijk
	   bruikbaar — daar beschermt de afstand tegen niets. Deze wel.)
	   Ingezet door de tablet-agent, hier verbreed naar beide assen. */
	@media (pointer: coarse) {
	}
	.btn {
		padding: 8px 12px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
		transition: background var(--transition);
	}
	.btn:hover:not(:disabled) {
		background: var(--surface-2);
	}
	.btn:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.btn.danger {
		background: var(--danger-solid);
		border-color: var(--danger-solid);
		color: var(--on-color);
	}
	.btn.subtle {
		grid-column: 1 / -1;
	}
	.btn.stop {
		grid-column: 1 / -1;
		margin-top: var(--space-6);
	}
	/* De verwijzing bestaat alleen op tablet; op desktop staan de knoppen hier. */
	/* Gat J9. Hier stond `@media (max-width: 1199px)` en in TopBar een JS-prop:
	   twee bronnen voor één afspraak, die uit de pas kunnen lopen met als
	   slechtste uitkomst dat de pauzeknop nergens of twee keer staat. Beide
	   lezen nu `apparaat.bedieningInBalk`; de klasse hieronder is het gevolg,
	   niet de regel. */
	.preflight {
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		padding: var(--space-3);
	}
	.pf-layers {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-xs);
		margin: 8px 0;
	}
	.pf-layers th {
		text-align: left;
		font-weight: 500;
		color: var(--text-2);
		border-bottom: 1px solid var(--line);
		padding-bottom: 2px;
	}
	.pf-layers td { padding: 2px 0; }
	.pf-layers td.mono { text-align: right; padding-right: 8px; font-variant-numeric: tabular-nums; }
	.chip {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: var(--radius-sharp);
		margin-right: var(--space-1h);
		vertical-align: baseline;
	}
	/* Met een nummer erin is de chip geen stip meer maar een klein vlak (gat J7).
	   Even breed als hoog en met tabulaire cijfers, zodat een 1 en een 10 de
	   kolom niet laten verspringen. De inkt (zwart of wit) komt uit `inktOp`:
	   op geel is wit 1,58:1 en dan lees je het cijfer domweg niet. */
	.chip.genummerd {
		width: 15px;
		height: 15px;
		line-height: 15px;
		text-align: center;
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
		border-radius: var(--radius-field);
		vertical-align: -3px;
	}
	.pf-name {
		max-width: 9em;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.unsure { color: var(--warn); }
	/* Een laag die niets doet, in de rustige tint: er valt niets te controleren,
	   dus dit is een mededeling en geen alarm. Het alarm staat erboven. */
	.pf-blind {
		color: var(--text-2);
		font-style: italic;
		/* Links, direct naast de laagnaam: dit gaat over de laag en niet over een
		   kolom. Rechts uitgelijnd stond het los aan de andere kant van de rij,
		   waar de lezer een getal verwacht. */
		text-align: left;
		padding-left: 8px;
	}
	.pf-warn.strong { color: var(--warn); font-weight: 500; }
	/* Een eigen soort, niet de vierde gele waas. De linkerbalk in de
	   gevarenkleur zegt "dit werkt niet" tegenover "let hierop"; de tekst zelf
	   houdt de gewone kleur, want --danger op deze waas haalt het contrast niet
	   (dezelfde meting als bij .pf-mismatch hieronder). */
	.pf-geenraster {
		margin: var(--space-2) 0;
		padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
		border-left: 4px solid var(--danger-solid);
		border-radius: 0 var(--radius-field) var(--radius-field) 0;
		background: color-mix(in srgb, var(--danger) 16%, transparent);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.pf-time {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		padding-bottom: var(--space-2);
		margin-bottom: 8px;
		border-bottom: 1px solid var(--line);
	}
	.pf-time .v {
		font-size: var(--text-md);
	}
	.rekent {
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.pf-row {
		color: var(--text-2);
		font-size: var(--text-xs);
		padding: var(--space-1) 0;
	}
	.pf-warn {
		margin: var(--space-2) 0;
		padding: var(--space-2);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--warn) 14%, transparent);
		font-size: var(--text-xs);
	}
	/* De enige melding hier die over een concrete verwisseling gaat, en dus de
	   enige met een linkerbalk: zwaarder dan de algemene "niet gemeten"-notitie
	   eronder, en niet in dezelfde vlakke gele tint, want dan wegen ze gelijk. */
	.pf-mismatch {
		margin: var(--space-2) 0;
		padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
		list-style: none;
		border-left: 4px solid var(--warn-solid);
		border-radius: 0 var(--radius-field) var(--radius-field) 0;
		background: color-mix(in srgb, var(--warn) 22%, transparent);
		font-size: var(--text-xs);
		display: grid;
		gap: var(--space-1);
	}
	/* Het mildste bezwaar — uitgerekend maar op het juiste materiaal — hoort er
	   wel te staan en niet even hard te roepen als een verkeerde plaat. */
	.pf-mismatch .licht { color: var(--text-2); }
	.pf-mismatch .licht strong { color: var(--text-1); font-weight: 500; }
	/* Geen gevuld pilletje: --warn-solid is volgens tokens.css een vlakkleur en
	   haalt met wit erop maar 3,25:1 (zelf gemeten: 2,22 in donker). Ook --warn
	   als tekst bleef op deze waas op 3,73 steken. Dus draagt de rand de kleur
	   en het woord de gewone tekstkleur — gemeten 9,79:1 licht, 14,5:1 donker. */
	.eerst {
		display: inline-block;
		margin-right: var(--space-1h);
		padding: 0 var(--space-1h);
		border-radius: var(--radius-dot);
		border: 1px solid var(--warn-solid);
		color: var(--text-1);
		font-size: var(--text-xs);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	/* De maat is secundair maar moet leesbaar blijven; geen aparte tint. */
	.pf-time.vel { border-bottom: none; padding-bottom: 0; margin-bottom: var(--space-2); }
	.pf-time.vel .v { font-size: var(--text-sm); }
	/* Ontbrekend materiaal is geen storing maar wel een gat: dezelfde gedempte
	   tint als de labels, zodat het leest als "hier hoort nog iets" en niet als
	   een materiaal dat "niet ingevuld" heet. */
	.pf-time.vel.onbekend .v { color: var(--text-2); font-style: italic; }
	.pf-check {
		margin: var(--space-3) 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		font-size: var(--text-xs);
	}
	.pf-kop {
		display: block;
		font-weight: 600;
		color: var(--text-2);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: var(--space-1);
	}
	.pf-check ul {
		margin: 0;
		padding-left: 1.1em;
		color: var(--text-1);
	}
	.pf-check li { padding: 1px 0; }
	/* De rand van de pre-flight is neutraal; bij "niets te doen" mag hij het
	   zeggen zonder alarm te slaan — dit is geen storing, alleen een lege bak. */
	.preflight.niets { border-color: var(--warn); }
	.pf-leeg { margin-bottom: var(--space-3); }
	.pf-leeg strong {
		display: block;
		font-size: var(--text-sm);
		margin-bottom: 2px;
	}
	.pf-leeg p {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.muted {
		color: var(--text-2);
	}
	.token {
		border: 1px solid var(--warn);
		border-radius: var(--radius-card);
		padding: var(--space-3);
		margin-bottom: var(--space-3);
	}
	.token label {
		display: block;
		font-weight: 500;
		margin-bottom: var(--space-2);
	}
	.token-row {
		display: flex;
		gap: var(--space-2);
	}
	.token input {
		flex: 1;
		min-width: 0;
		font: inherit;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.token.afgewezen { border-color: var(--danger-solid); }
	.motion { margin-top: var(--space-4); }
	.rot-label {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-2);
	}
	.pad {
		display: grid;
		/* Vier kolommen; de vijfde bestaat alleen als er een Z-as is, anders
		   staat er een lege kolom ruimte in te nemen. */
		grid-template-columns: repeat(4, 40px);
		grid-template-rows: repeat(2, 34px);
		gap: 4px;
		margin: var(--space-2) 0;
	}
	/* Expliciet plaatsen: met impliciete plaatsing schoof ↓ naar de eerste
	   kolom in plaats van onder ↑. */
	.pad .up { grid-area: 1 / 2; }
	.pad .left { grid-area: 2 / 1; }
	.pad .down { grid-area: 2 / 2; }
	.pad .right { grid-area: 2 / 3; }
	.pad .home { grid-area: 1 / 4 / 3 / 5; }
	.pad.metz { grid-template-columns: repeat(5, 40px); }
	.pad .zup { grid-area: 1 / 5; }
	.pad .zdown { grid-area: 2 / 5; }
	/* De Z-knoppen dragen een letter én een pijl; dat past niet op 15px. */
	.pad .zup, .pad .zdown { font-size: var(--text-xs); }
	.jog {
		padding: 8px 0;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		font-weight: 500;
	}
	.jog:hover:not(:disabled) { background: var(--surface-2); }
	/* Uitgeschakeld moet je zíen. Deze knoppen waren wel geblokkeerd maar zagen
	   er identiek uit, dus bleef je erop drukken en gebeurde er niets. */
	.jog:disabled { opacity: 0.4; cursor: not-allowed; }
	.rot:disabled { opacity: 0.4; cursor: not-allowed; }
	.jog.home { font-size: var(--text-xs); }
	.steps { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
	.rot {
		font-size: var(--text-xs);
		padding: 4px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
	}
	/* Zelfde sluimerstand als in de bovenbalk: herkenbaar als de stopknop
	   (rode rand, rood vierkant) zonder de hele dag alarm te slaan. */
	/* Dezelfde dode staat als in de bovenbalk: onderbroken rand, geen rood, en
	   leesbaar — de tekst ís hier het bericht, dus die mag niet vervagen. */
	.btn.danger.dood {
		background: transparent;
		border: 1px dashed color-mix(in srgb, var(--text-2) 55%, transparent);
		color: var(--text-2);
	}
	.btn.danger.dood:disabled { opacity: 1; }
	.btn.danger.dood strong { color: var(--text-1); }
	.hint {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* ── Het voortgangsblok ─────────────────────────────────────────────────
	   Wat er nú aan de hand is, bovenaan het paneel. De maten zijn ruim: dit is
	   het blok waar je vanaf twee meter naar kijkt terwijl je bij de machine
	   staat, niet iets wat je van dichtbij afleest. */
	.nu {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
	}
	/* Alleen een lopende job krijgt het accent. Een gepauzeerde krijgt de
	   waarschuwingskleur, want stilstaan met werk in de machine is een toestand
	   waar je iets mee moet. */
	.nu.brandt { border-color: color-mix(in srgb, var(--accent) 55%, var(--line)); }
	.nu.pauze { border-color: color-mix(in srgb, var(--warn-solid) 55%, var(--line)); }
	.nu-kop {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
	}
	.nu-phase {
		font-size: var(--text-md);
		font-weight: 600;
		color: var(--text-1);
	}
	.nu.brandt .nu-phase { color: var(--accent); }
	.nu.pauze .nu-phase { color: var(--warn); }
	.nu-job {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		text-align: right;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.nu-balk {
		height: 8px;
		border-radius: 999px;
		background: var(--surface-2);
		overflow: hidden;
	}
	.nu-vol {
		display: block;
		height: 100%;
		border-radius: 999px;
		background: var(--accent);
		transition: width var(--transition);
	}
	.nu.pauze .nu-vol { background: var(--warn-solid); }
	.nu-cijfers {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	/* Het percentage is het getal dat je van een afstand leest; de rest is
	   bijschrift. */
	.nu-pct {
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-1);
		font-variant-numeric: tabular-nums;
	}
	.nu-stap,
	.nu-pass { font-variant-numeric: tabular-nums; }
	.nu-tijd {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.nu-rest { color: var(--text-1); font-weight: 500; }
	.nu-uitleg {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.5;
		color: var(--text-2);
	}
	.nu-acties {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-1);
	}
	/* Stoppen houdt afstand van pauze: een mistik kost hier het werkstuk. */
	.nu-rek { flex: 1; min-width: var(--space-6); }
	.nu-acties .btn { min-height: 40px; padding: 0 var(--space-4); }
	.wachtrij { align-self: flex-start; }

	/* De machinebediening onder de voortgang, dicht zolang er werk onderweg is. */
	.machinevouw {
		margin-top: var(--space-4);
		border-top: 1px solid var(--line);
		padding-top: var(--space-3);
	}
	.machinevouw > summary {
		cursor: pointer;
		font-size: var(--text-xs);
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text-2);
		list-style: none;
	}
	.machinevouw > summary::-webkit-details-marker { display: none; }
	.machinevouw > summary::before {
		content: '▸';
		display: inline-block;
		width: 1em;
		color: var(--text-2);
	}
	.machinevouw[open] > summary::before { content: '▾'; }
	.machinevouw > summary:hover { color: var(--text-1); }
	.machinevouw .waarom {
		text-transform: none;
		letter-spacing: 0;
		font-weight: 400;
	}

	/* De knoppenbalk plakt onderaan het paneel: de kolom is langer dan het paneel
	   en de primaire handeling mag nooit onder de vouw staan. Negatieve marges om
	   de padding van `.panel-scroll` heen, zodat de balk van rand tot rand loopt
	   en er niets onderdoor te zien is. */
	.pf-plak {
		position: sticky;
		bottom: calc(-1 * var(--space-4));
		z-index: 2;
		display: flex;
		gap: var(--space-2);
		margin: var(--space-3) calc(-1 * var(--space-4)) calc(-1 * var(--space-4));
		padding: var(--space-3) var(--space-4);
		background: var(--surface-1);
		border-top: 1px solid var(--line);
	}
	/* De hulpknop houdt zijn woord op één regel; de primaire krijgt de rest.
	   Met `flex: 1` op beide brak "Kader tonen" over twee regels en werd de rij
	   twee keer zo hoog. */
	.pf-plak .btn { flex: none; white-space: nowrap; }
	.pf-plak .btn.primary { flex: 1; }

	/* De startknop zegt wat hij gaat doen, met de tijd erin. */
	.btn.groot { min-height: 44px; font-size: var(--text-md); }
	.pf-startmaat {
		margin-left: 6px;
		font-size: var(--text-xs);
		font-weight: 400;
		opacity: 0.85;
	}

	.toetsen {
		grid-column: 1 / -1;
		margin: var(--space-3) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
		line-height: 1.5;
	}
	/* Vier regels over toetsen op een scherm zonder toetsenbord is de duurste
	   ruimte van de app vullen met iets wat je daar niet kunt doen. Op tablet
	   staat de bediening bovendien in de balk en is dit paneel al vooral proza.
	   Een tablet met een los toetsenbord houdt de sneltoets — hij staat nog in
	   de tooltip van de knop, en hij werkt gewoon. */
	@media (pointer: coarse) {
		.toetsen { display: none; }
	}
	kbd {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		padding: 1px var(--space-1h);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
		white-space: nowrap;
	}
	/* Naar een punt springen, naast de richtingsknoppen erboven. */
	.punten { margin-top: var(--space-3); }
	.puntrij {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin: var(--space-2) 0;
	}
	/* Naam en kruisje zijn één ding met twee doelen; de naad ertussen is een
	   haarlijn, zodat het als één chip leest en niet als twee losse knopjes. */
	.plek { display: inline-flex; }
	.plek .naam { border-radius: var(--radius-field) 0 0 var(--radius-field); }
	.plek .weg {
		border-left: none;
		border-radius: 0 var(--radius-field) var(--radius-field) 0;
		padding: 4px var(--space-2);
		color: var(--text-2);
	}
	.plek .weg:hover { color: var(--danger); }
	/* Op een aanraakscherm is een kruisje van 20px een vergissing die wacht om
	   te gebeuren: één misgeprikte tik en je bewaarde positie is weg. Het is
	   herstelbaar (naartoe joggen, opnieuw bewaren) en daarom geen bevestiging
	   waard, maar het doel mag wel de handschoenmaat halen. */
	@media (pointer: coarse) {
		.plek .naam,
		.plek .weg { min-height: 44px; }
		.plek .weg { padding: 0 var(--space-3); }
	}
	/* Gedempt en een maat kleiner: de naam is waar je op mikt, de coördinaten
	   zijn de bevestiging dat het de juiste plek is. */
	.coord { color: var(--text-2); margin-left: var(--space-1h); }
	.bewaarrij {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
	}
	/* ── Het nulpunt (gat J12) ─────────────────────────────────────────────────
	   Een eigen blokje met een rustige rand eromheen: dit is een stand die aan
	   of uit staat en die je werk verplaatst. Zonder omlijsting leest het als
	   nóg een rij knoppen tussen de bewaarde plekken, en dan zie je niet dát er
	   iets aan staat. */
	.nulpunt {
		margin-top: var(--space-3);
		padding: var(--space-2h) var(--space-3);
		border: 1px solid var(--line-1);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	/* Staat er een nulpunt, dan draagt de linkerrand dat — zodat je het aan de
	   rand van je oog ziet zonder de tekst te lezen. In het accent en niet in
	   een waarschuwingskleur: dit is niet gevaarlijk, het is aan. */
	.nulpunt.gezet {
		border-left: 3px solid var(--accent);
	}
	.nulstand {
		margin: var(--space-1h) 0 0;
		font-size: var(--text-xs);
		line-height: 1.45;
		color: var(--text-2);
	}
	.nulstand .mono {
		color: var(--text-1);
		font-variant-numeric: tabular-nums;
	}
	/* ── Bijstellen tijdens de job (gat J11) ───────────────────────────────── */
	.bijstellen { margin-top: var(--space-3); }
	.stelrij { margin-top: var(--space-2); }
	.stelnaam {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.stelwaarde {
		color: var(--text-2);
		font-variant-numeric: tabular-nums;
	}
	.stelknoppen {
		display: flex;
		gap: var(--space-1h);
		margin-top: var(--space-1h);
	}
	/* Vijf knoppen op één regel in een paneel van 280 px: elk mag krimpen, maar
	   de tekst blijft op de typeschaal — alleen de lucht eromheen gaat eraf. */
	.stel {
		flex: 1;
		min-width: 0;
		padding: 4px 2px;
		/* Getallen in mono: deze knoppen staan naast elkaar en verspringen
		   anders in breedte zodra +1% een +10% wordt. */
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
	}
	.stel.terug { flex: 1.3; }
	.naamveld {
		flex: 1;
		min-width: 10ch;
		font: inherit;
		font-size: var(--text-xs);
		padding: 4px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
</style>
