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
	import { screen } from '$lib/screen.svelte';
	import { i18n, t, type MessageKey } from '$lib/i18n/index.svelte';
	import type { Controller, Position } from '$lib/control.svelte';
	import { connection } from '$lib/connection.svelte';
	import { inkOn, layerNumber, type Design } from '$lib/design.svelte';
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

	// Gat J9: één bron voor "waar woont deze actie". Zie device.svelte.ts.
	let balkdraagt = $derived(screen.controlsInBar);
	let actions = $derived(control.capabilities?.actions ?? null);
	let running = $derived(Boolean(job?.running));
	// Stilstaand, niet alleen "gepauzeerd volgens het statusveld": pauzeren set
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

	// Wat de laag draagt tegenover waarin gebrand wordt. Dit is het last
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
	 * Beide shouldAsk worden door de server beantwoord en niet hier: die meet ze
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
	// Whole millimetres where it can be; 0.5 mm stays 0.5 mm. Written in the
	// reader's own notation, because these numbers get typed into a machine.
	function size(value: number): string {
		return i18n.number(Math.round(value * 10) / 10);
	}

	// Settings that were not measured deserve a warning before the material is in
	// the machine — not after.
	const UNMEASURED: Record<string, MessageKey> = {
		geextrapoleerd: 'preset.source.extrapolated',
		handmatig: 'preset.source.manual',
		geimporteerd: 'preset.source.someoneElse'
	};
	// A layer that does not burn need not have trustworthy settings: nothing is
	// done with them. Counting it turns "3 layers were not measured" into a number
	// that does not match what is about to happen.
	let risky = $derived(layers.filter((l) => l.burns !== false && l.source !== 'testraster'));

	/**
	 * Where the numbers of this layer come from, in two words.
	 *
	 * "Measured" above a setting that was measured on *other* material reassures
	 * where it should not: the measuring is sound, the material is not. So this
	 * column says what is actually going on, and the line below it says why.
	 */
	function source(layer: Layer): string {
		const codes = (layer.warnings ?? []).map((w) => w.code);
		if (codes.includes('ander-materiaal')) return t('preset.source.otherMaterial');
		if (codes.includes('andere-dikte')) return t('preset.source.otherThickness');
		if (layer.source === 'testraster') return t('preset.source.measured');
		return t(UNMEASURED[layer.source ?? ''] ?? 'preset.source.unmeasured');
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
	 * niet gratis. 400 ms na de last wijziging is snel genoeg om vers te
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

	// Without a token every write action yields a 401. Offering a button that is
	// guaranteed to fail is an empty promise, so it is blocked here already. The
	// same goes for a server that has dropped out: nothing arrives then, and a
	// button that looks operable promises something that will not happen.
	let blocked = $derived(
		control.tokenProbleem || control.busy !== null || !connection.online
	);
	let blockedReason = $derived(
		!connection.online
			? t('job.blocked.noServer')
			: control.tokenProbleem
				? t('job.blocked.token')
				: undefined
	);

	// Moving the head while burning ruins the job at best.
	let movingBlocked = $derived(
		!connection.online
			? t('job.blocked.noServerMove')
			: running
				? t('job.blocked.duringJob')
				: undefined
	);
	let bewegenUit = $derived(running || !connection.online);

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
	const ADJUSTABLE = [
		{ what: 'power' as const, key: 'job.adjust.power' as MessageKey },
		{ what: 'speed' as const, key: 'job.adjust.speed' as MessageKey }
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
	 * keer failure: je krijgt pas na het starten te horen dat er niets was, en je
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
	<!-- The heading said "Controls", and that is true: these are controls. But it
	     says nothing about what is going on right now, and that is exactly what
	     you come to this tab for. -->
	<h2 class="section-title">
		{busyWithWork || phase === 'done' ? t('job.section.theJob') : t('job.section.preparing')}
	</h2>

	{#if control.tokenProbleem}
		<!-- The API is reachable from the network; without a token everything stays
		     read-only. A refused token counts too: it *was* in the browser, so this
		     field disappeared and there was no way back — every action failed with a
		     401 and there was nowhere to put a different token. -->
		<div class="token" class:afgewezen={control.rejected}>
			<label for="token">
				{control.rejected ? t('job.token.rejected') : t('job.token.label')}
			</label>
			<div class="token-row">
				<input id="token" type="password" bind:value={tokenDraft} placeholder={t('job.token.placeholder')} />
				<button class="btn" onclick={() => control.saveToken(tokenDraft)}>{t('common.save')}</button>
			</div>
			<p class="hint">
				{control.rejected
					? t('job.token.rejectedHint')
					: t('job.token.hint')}
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
			<!-- "Estimated time 0:00" above an empty bed reads as a job of zero
			     seconds instead of as no job. With nothing to do the clock keeps
			     quiet and the message below it speaks. -->
			<!-- The workpiece first, the numbers about it after (decision B8).
			     Whoever sees something hanging off the sheet need not read the time
			     any more — and on tablet and phone the canvas is not beside it. -->
			{#if !leeg}
				<!-- The messages about bed and sheet belong to the drawing and so
				     live in it, right under the shape they are about (gaps J5 and C2).
				     They used to be here as two equally red cards in a row; that made
				     "there is no material there" as serious as "the head does not get
				     there", and then neither carries any weight. -->
				<JobPreview
					design={ontwerp}
					sheet={overzicht?.sheet ?? null}
					bounds={grenzen}
					{colorFor}
				/>
				<!-- The converter that turns a raster area into laser lines lives in
				     the wxPython version of the engine. When it is missing, the layer
				     throws its own shapes away during planning and nothing comes out
				     of the machine. The same words as the block in the test-grid
				     wizard: whoever read them there recognises them here — and the
				     other way round. -->
				{#if rasterUit && blindeLagen.length}
					<p class="pf-geenraster" role="alert">
						<strong>{t('job.noRaster.title')}</strong>
						{blindeLagen.length === 1
							? t('job.noRaster.one', { label: blindeLagen[0].label })
							: t('job.noRaster.many', { n: blindeLagen.length })}
					</p>
				{/if}
				<div class="pf-time">
					<span class="muted">{t('job.estimatedTime')}</span>
					<span class="v mono">
						{#if estimating}
							<span class="rekent">{t('job.calculating')}</span>
						{:else}{formatDuration(estimate?.seconds ?? job?.estimate_seconds)}{/if}
					</span>
				</div>
				<!-- *What* is being burned, right above the settings it is burned
				     with. Without it there is a table of numbers with no subject. -->
				<!-- Always a line, even without material. Saying nothing reads as
				     "not needed"; and then you run a birch preset on acrylic. -->
				<div class="pf-time vel" class:onbekend={!velTekst}>
					<span class="muted">{t('job.material')}</span>
					<span class="v">{velTekst ?? t('job.material.none')}</span>
				</div>
					{#if control.origin}
						<!-- Gap J12: a zero point moves the work on the bed, and the
						     preflight is the last moment you can still see that. So it is
						     here as a line of its own — saying nothing would mean the one
						     screen before burning does not say *where* it burns. -->
						<div class="pf-time vel">
							<span class="muted">{t('job.origin')}</span>
							<span class="v mono"
								>{size(control.origin.x_mm)},&#8239;{size(control.origin.y_mm)} mm</span
							>
						</div>
					{/if}
					<!-- No second line with the job size: the view above already puts
				     "work 120 × 80 mm" under the drawing (decision B8). That same
				     number again as a row of its own, ninety pixels lower, is not
				     information but noise. What the view does *not* do is hold the work
				     up against the bed — that is below. -->
			{/if}
			{#if !leeg && device?.connection?.state === 'disconnected'}
				<!-- Starting is allowed: the engine queues the job and connects as
				     soon as the machine is there. But whoever presses "Start now" and
				     walks over to a silent machine has to know the waiting is down to
				     that and not to the job. -->
				<p class="pf-warn strong">{t('job.notResponding')}</p>
			{/if}
			{#if estimateTraag}
				<p class="pf-row">{t('job.estimateSlow')}</p>
			{/if}
			<!-- Only shown when there is something in it: "In queue: 0" just before
			     starting is the normal situation, and therefore not news. -->
			{#if queued > 0}
				<div class="pf-row">{t('job.queueAhead', { n: queued })}</div>
			{/if}

			<!-- What the machine is going to *do*. Time and count alone is theatre: a
			     laser cutter checks speed, power and passes before putting anything in
			     the machine. -->
			{#if layers.length}
				<table class="pf-layers">
					<thead>
						<tr><th>{t('job.layer')}</th><th>mm/s</th><th>%</th><th>×</th><th>{t('job.source')}</th></tr>
					</thead>
					<tbody>
						<!-- Keyed on the index, not on the label: two operations of the same
						     type are both called "Engrave", and a duplicate key makes Svelte
						     update the table wrongly. -->
						{#each layers as layer, i (i)}
							<tr>
								<td class="pf-name" title={layer.label}>
										<!-- Two cut layers are both called "Cut"; the chip is the only
										     thing telling them apart, and it is the same colour as on the
										     canvas and in the layer list.

										     Gap J7: with the layer number in it. The design system forbids
										     information that lives in colour alone, and of ten layer
										     colours two collide under deuteranopia. The number comes from
										     `layerNumber()` — the same source as the chip in the layer panel
										     and the digit beside the shape on the canvas, so they cannot
										     drift apart. -->
										{#if colorFor}
											{@const nummer = layerNumber(ontwerp, layer.id)}
											<!-- Without `aria-hidden` a screen reader would otherwise hear a
											     bare digit in front of the layer name: "1 Cut". `role="img"`
											     with a name turns it into "Layer 1, Cut"; without a role most
											     screen readers ignore an aria-label on a span. With no number
											     the chip is colour only, and therefore decoration — that one
											     stays hidden. -->
											{#if nummer === null}
												<span class="chip mono" style:background={colorFor(layer.id)} aria-hidden="true"
												></span>
											{:else}
												<span
													class="chip mono genummerd"
													style:background={colorFor(layer.id)}
													style:color={inkOn(colorFor(layer.id))}
													role="img"
													aria-label={t('job.layerAria', { n: nummer })}
												>{nummer}</span>
											{/if}
										{/if}{layer.label}
									</td>
								<!-- A layer this engine does not carry out must not show speed and
								     power as if something is going to happen. The provenance goes
								     too: where the numbers come from is beside the point when they
								     are not used. -->
								{#if layer.burns === false}
									<td class="pf-blind" colspan="4">{t('panel.tag.doesNotBurn')}</td>
								{:else}
									<td class="mono">{layer.speed_mm_s ?? '—'}</td>
									<td class="mono">{layer.power_percent ?? '—'}</td>
									<td class="mono">{layer.passes}</td>
									<!-- "measured" in calm text above a setting that was measured on
									     *other* material reassures where it should not. The line below
									     says what is wrong with it; here the colour says at least that
									     there is something. -->
									<td class:unsure={layer.source !== 'testraster' || (layer.warnings?.length ?? 0) > 0}>
										{source(layer)}
									</td>
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
				<!-- The concrete objection first, the general one after. A setting from
				     *other* material is not a matter of trust but of the wrong board:
				     that belongs at the top, and by name.

				     Within the list not everything weighs the same. A measured value
				     from the wrong material outranks a calculated value on the right
				     one, and when those two stand side by side the tag says which to
				     fix first. -->
				{#if mismatch.length}
					<ul class="pf-mismatch" role="alert">
						{#each mismatch as melding, i (i)}
							<li class:licht={melding.ernst < 2}>
								{#if i === 0 && eersteWeegtZwaarder}
									<span class="eerst">{t('job.first')}</span>
								{/if}<strong>{melding.laag}</strong> — {melding.tekst}
							</li>
						{/each}
					</ul>
				{/if}
				{#if risky.length}
					<p class="pf-warn strong">{t('job.risky', { n: risky.length })}</p>
				{/if}
			{/if}

			{#if leeg}
				<!-- No checklist, no start button: there is nothing to run through. -->
				<div class="pf-leeg">
					<strong>{t('job.nothing.title')}</strong>
					<p>{t('job.nothing.body')}</p>
				</div>
				<!-- This used to say "Back to the design", which was the only way out
				     of an overview that had taken over the panel. The panel takes
				     nothing over now, so there is nothing to return from. -->
			{:else}
			<!-- This used to be a second yellow block under the risk warning. Two
			     warnings in a row of the same colour devalue each other: the routine
			     check made the real message invisible. Neutral now, and as a list,
			     because you work down it. -->
			<div class="pf-check">
				<span class="pf-kop">{t('job.checklist.title')}</span>
				<ul>
					<li>{t('job.checklist.lid')}</li>
					<li>{t('job.checklist.air')}</li>
					<li>{t('job.checklist.workpiece')}</li>
				</ul>
			</div>

			<!--
				The buttons stick to the bottom of the panel.

				Since the preparation is always open, the column is taller than the
				panel is high (measured: 1,427 px of content in 788 px). Without this
				sticky footer the start button sat below the fold — the primary action
				out of sight, which is exactly what this round had to solve, not cause.

				Showing the frame is on the same line: it is the last check before that
				same button, so it belongs beside it and not three blocks higher.
			-->
			<div class="pf-plak">
				{#if preflight}
					<!-- Two deliberate taps, in the same place: VEILIGHEID.md lays down that
					     no single click burns. The first arms, the second fires — and unlike
					     before, that first tap does not make anything disappear. -->
					<button class="btn" onclick={() => (preflight = false)}>{t('common.cancel')}</button>
					<button
						class="btn primary groot"
						onclick={confirmStart}
						disabled={control.busy !== null || !connection.online}
						title={connection.online ? undefined : blockedReason}
					>
						{control.busy === 'start' ? t('job.starting') : t('job.startNow')}
					</button>
				{:else}
					{#if onFrame}
						<button
							class="btn"
							disabled={control.busy !== null || running}
							title={t('job.frame.title')}
							onclick={() => onFrame?.()}
						>
							{t('job.frame')}
						</button>
					{/if}
					<button
						class="btn primary groot"
						disabled={!actions?.start || blocked}
						title={blockedReason}
						onclick={() => (preflight = true)}
					>
						{t('job.startJob')}{#if !estimating && (estimate?.seconds ?? job?.estimate_seconds)}
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
			The progress block.

			There used to be four buttons here (start, pause, clear queue, stop) plus
			four lines explaining shortcuts, and they were there regardless of what the
			machine was doing. Three of the four were dead as long as nothing was
			running, and the moment something *was* running the only information that
			then means anything — the progress — sat at 700px, under the jog buttons,
			out of sight.

			Now the phase leads (`jobPhase` in `$lib/api.ts`): what is going on is at
			the top, with the buttons that do something at *this* moment. The shortcuts
			are on the buttons themselves, because that is where you learn them.
		-->
		<div class="nu" class:brandt={phase === 'burning'} class:pauze={phase === 'paused'}>
			<div class="nu-kop">
				<span class="nu-phase">{phaseTitle(phase)}</span>
				{#if job}
					<span class="nu-job mono" title={job.label}>{job.label}</span>
				{/if}
			</div>

			{#if voortgang !== null}
				<!-- The bar and the percentage belong together and so sit on one line;
				     the times below in the same columns as always. -->
				<div class="nu-balk" role="progressbar" aria-valuenow={Math.round(voortgang * 100)} aria-valuemin="0" aria-valuemax="100" aria-label={t('job.progressAria')}>
					<span class="nu-vol" style="width: {Math.round(voortgang * 1000) / 10}%"></span>
				</div>
				<div class="nu-cijfers mono">
					<span class="nu-pct">{Math.round(voortgang * 100)}%</span>
					{#if job?.steps_total}
						<span class="nu-stap">{t('job.steps', { done: job.steps_done ?? 0, total: job.steps_total })}</span>
					{/if}
					{#if (job?.loops ?? 1) > 1}
						<span class="nu-pass">{t('job.pass', { n: (job?.loops_executed ?? 0) + 1, total: job?.loops })}</span>
					{/if}
				</div>
				<div class="nu-tijd">
					<span>{t('job.elapsed', { time: formatDuration(job?.elapsed_seconds ?? null) })}</span>
					{#if resterend !== null}<span class="nu-rest"
							>{t('status.remaining', { remaining: formatDuration(resterend) })}</span
						>{/if}
				</div>
			{/if}

			<p class="nu-uitleg">{phaseBody(phase)}</p>

			<div class="nu-acties">
				{#if paused}
					<button
						class="btn primary"
						disabled={!actions?.resume || blocked}
						title="{blockedReason ?? t('job.pause.keepGoing')} · {PAUSE_KEY}"
						onclick={() => control.resume()}
					>{t('job.resume')}</button>
				{:else}
					<!-- On the phase and not on `job.running`: a job that has been spooled
					     but not picked up sits at `running: false`, and then the top bar
					     offered pause while this button was disabled. `pause` is a realtime
					     command; it lands the moment the machine starts. -->
					<button
						class="btn"
						disabled={!actions?.pause || !busyWithWork || blocked}
						title={busyWithWork
							? `${blockedReason ?? t('job.pause.stopHead')} · ${PAUSE_KEY}`
							: t('transport.pause.nothing')}
						onclick={() => control.pause()}
					>{t('job.pause')}</button>
				{/if}
				<span class="nu-rek"></span>
				<!-- Stop keeps its own space, away to the left of pause: a mis-tap here
				     costs the workpiece. See DESIGN-SYSTEM v2, "Touch as first-class
				     input". -->
				<button
					class="btn danger stop"
					class:dood={!connection.online}
					disabled={!actions?.stop || control.tokenProbleem || !connection.online}
					title={!connection.online
						? t('job.stop.noServer')
						: `${blockedReason ?? t('job.stop.now')} · ${STOP_KEY}`}
					onclick={() => control.stop()}
				>
					{#if connection.online}{t('job.stop')}{:else}{t('job.stop')}
						<strong>{t('job.stop.onMachine')}</strong>{/if}
				</button>
			</div>

			<!-- As soon as there is anything in the queue. This used to say
			     `queued > 1`, and then with exactly one job in the row the queue could
			     not be cleared — an operation that disappeared instead of moving. -->
			{#if queued > 0}
				<button
					class="btn subtle wachtrij"
					disabled={!actions?.clear_queue || queued === 0 || blocked}
					title={queued === 0 ? t('job.queueEmpty') : blockedReason}
					onclick={() => control.clearQueue()}
				>
					{t('job.clearQueue', { n: queued })}
				</button>
			{/if}

			<!-- Gap J4, shortened. The keys are in the tooltips of the buttons above
			     now; what a tooltip cannot say is that they do not work outside this
			     window, and that is exactly the part you discover at the wrong
			     moment. -->
			<p class="toetsen">
				{t('job.keysWork', {
					pause: PAUSE_KEY,
					stop: STOP_KEY
				})}
			</p>
		</div>

	{/if}

	{#if !control.tokenProbleem}
		<!--
			The machine controls: moving, going to a point, the zero point, adjusting.

			This is getting-ready work. It used to sit above the progress and, during a
			running job, took up the whole visible panel — while its buttons are
			precisely then disabled, because you do not jog with a burning laser. Now it
			sits *under* what is happening, and folds shut as soon as work is under way.
			Shut and not gone: it has to be there the moment you need it again, and a
			block that disappears is not one you learn to find back.
		-->
		<details class="machinevouw" open={!busyWithWork}>
			<summary>
				{t('job.machineControls')}
				{#if busyWithWork}<span class="waarom">— {t('job.machineControls.notNow')}</span>{/if}
			</summary>
		<div class="motion">
			<span class="rot-label">{t('job.move')}</span>
			<!-- Inverted T, like the arrow keys on a keyboard: ↑ above ↓, with ← and →
			     beside them. Home sits next to it and not in the middle, because it is
			     not a direction. -->
			<div class="pad" class:metz={control.capabilities?.motion?.focus}>
				<button class="jog up" aria-label={t('job.jog.up')} disabled={bewegenUit} title={movingBlocked} onclick={() => onJog?.(0, -step)}>↑</button>
				<button class="jog left" aria-label={t('job.jog.left')} disabled={bewegenUit} title={movingBlocked} onclick={() => onJog?.(-step, 0)}>←</button>
				<button class="jog down" aria-label={t('job.jog.down')} disabled={bewegenUit} title={movingBlocked} onclick={() => onJog?.(0, step)}>↓</button>
				<button class="jog right" aria-label={t('job.jog.right')} disabled={bewegenUit} title={movingBlocked} onclick={() => onJog?.(step, 0)}>→</button>
				<button class="jog home" disabled={bewegenUit} title={movingBlocked} onclick={() => onHome?.()}>{t('job.home')}</button>
				{#if control.capabilities?.motion?.focus}
					<!-- The Z axis is in the same pad as X and Y: it is the same operation
					     with a third direction, and it follows the same step size. -->
					<button
						class="jog zup"
						disabled={bewegenUit}
						title={movingBlocked ?? t('job.jog.z', { step, direction: t('job.jog.zUp') })}
						onclick={() => onFocus?.(-step)}
					>Z&nbsp;↑</button>
					<button
						class="jog zdown"
						disabled={bewegenUit}
						title={movingBlocked ?? t('job.jog.z', { step, direction: t('job.jog.zDown') })}
						onclick={() => onFocus?.(step)}
					>Z&nbsp;↓</button>
				{/if}
			</div>
			<div class="steps">
				<Segmented
					label={t('job.stepSize')}
					mono
					bind:value={step}
					options={[0.1, 1, 10, 50].map((size) => ({ value: size, label: `${size} mm` }))}
				/>
				<button class="rot" disabled={bewegenUit} title={movingBlocked} onclick={() => onUnlock?.()}>
					{t('job.unlock')}
				</button>
			</div>

			<!-- To a point instead of in a direction (gap J6). LightBurn's Move window
			     has "Go to Origin" and saved positions; whoever has a jig on the bed
			     otherwise jogs that corner together again every session. -->
			{#if control.capabilities?.motion?.move}
				<div class="punten">
					<span class="rot-label">{t('job.toPoint')}</span>
					<div class="puntrij">
						<button
							class="rot"
							disabled={bewegenUit}
							title={movingBlocked ?? t('job.toOrigin.title')}
							onclick={() => control.moveTo(0, 0)}
						>
							{t('job.toOrigin')}
						</button>
						{#each posities as plek (plek.name)}
							<span class="plek">
								<button
									class="rot naam"
									disabled={bewegenUit}
									title={movingBlocked ??
										t('job.toSpot.title', { x: size(plek.x_mm), y: size(plek.y_mm) })}
									onclick={() => control.moveTo(plek.x_mm, plek.y_mm)}
								>
									{plek.name}
									<!-- The coordinates with it, not only in the tooltip: on a touch
									     screen there is no hover, and then a saved position is a name
									     without a place. LightBurn puts them in a column of their own;
									     there is no column for that here, so they sit muted behind the
									     name in the same chip. -->
									<span class="coord mono">{size(plek.x_mm)},&#8239;{size(plek.y_mm)}</span>
								</button>
								<!-- Discarding is in the button itself, not in a menu: there are at
								     most twelve of them and you do it rarely. -->
								<button
									class="rot weg"
									aria-label={t('job.forgetSpotAria', { name: plek.name })}
									title={t('job.forgetSpot')}
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
								placeholder={t('job.spotName.placeholder')}
								maxlength="40"
								autofocus
								bind:value={nieuweNaam}
								onkeydown={(e) => {
									if (e.key === 'Enter') bewaar();
									if (e.key === 'Escape') bewaren = false;
								}}
							/>
							<button class="rot" onclick={bewaar} disabled={!nieuweNaam.trim()}>
								{t('job.keep')}
							</button>
							<button class="rot" onclick={() => (bewaren = false)}>{t('common.cancel')}</button>
						</div>
					{:else}
						<button
							class="rot"
							disabled={bewegenUit || huidigMm === null}
							title={huidigMm === null
								? t('job.noPosition.keep')
								: t('job.keepSpot.title', { x: size(huidigMm[0]), y: size(huidigMm[1]) })}
							onclick={() => {
								nieuweNaam = '';
								bewaren = true;
							}}
						>
							{t('job.keepSpot')}
						</button>
					{/if}
				</div>
			{/if}
			<!-- The zero point (gap J12). LightBurn has Set Origin / Clear Origin / Go
			     to Origin; here "To origin" was literally 0,0 of the bed and there was
			     no way to set a zero point of your own. That is daily work: the offcut
			     lies where it lies, and you do not want to drag your whole drawing to
			     get it onto the board.

			     Deliberately a block of its own under "To a point" and not among them:
			     the saved positions say "go there", this says "measure from there".
			     Among the spots it would read as one more spot. -->
			{#if control.capabilities?.motion?.move}
				<div class="nulpunt" class:gezet={control.origin !== null}>
					<span class="rot-label">{t('job.workOrigin')}</span>
					{#if control.origin}
						<!-- The number is always with it. A zero point you cannot read off is
						     a setting that quietly moves your work, and that is exactly the
						     kind of surprise that makes a laser expensive. -->
						<p class="nulstand">
							<span class="mono"
								>{size(control.origin.x_mm)},&#8239;{size(control.origin.y_mm)} mm</span
							>
							— {t('job.origin.here')}
						</p>
					{:else}
						<p class="hint">{t('job.origin.off')}</p>
					{/if}
					<div class="puntrij">
						<button
							class="rot"
							disabled={bewegenUit || huidigMm === null}
							title={huidigMm === null
								? t('job.noPosition.origin')
								: t('job.origin.setTitle', { x: size(huidigMm[0]), y: size(huidigMm[1]) })}
							onclick={() => control.setOrigin()}
						>
							{control.origin ? t('job.origin.reset') : t('job.origin.set')}
						</button>
						{#if control.origin}
							<button
								class="rot"
								disabled={bewegenUit}
								title={movingBlocked ?? t('job.origin.goTitle')}
								onclick={() =>
									control.origin && control.moveTo(control.origin.x_mm, control.origin.y_mm)}
							>
								{t('job.toZero')}
							</button>
							<button
								class="rot"
								title={t('job.origin.clearTitle')}
								onclick={() => control.clearOrigin()}
							>
								{t('job.clearZero')}
							</button>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Adjusting during a running job (gap J11).
			     LightBurn has two columns here, "Adjust Speed" and "Adjust Power", with
			     which you *save* a job instead of redoing it: you see it going too dark
			     and dial ten per cent back without stopping.

			     Only visible when the driver can do it, and that is not tidiness but
			     necessity: only grbl has realtime overrides (0x90/0x99); the Ruida sets
			     speed and power per cut segment from the settings. A button that does
			     nothing next to a burning laser is worse than no button. See
			     FEATURE-GAPS J11. -->
			{#if control.canAdjust}
				<div class="bijstellen">
					<span class="rot-label">{t('job.adjust.title')}</span>
					{#each ADJUSTABLE as axis (axis.what)}
						{#if control.capabilities?.adjust?.[axis.what]}
							{@const level = control.adjust[axis.what] ?? 1}
							<div class="stelrij">
								<span class="stelnaam">
									{t(axis.key)}
									<!-- Only the number in mono; "as designed" is a phrase, and in a
									     figure font it sits oddly measured out. -->
									<span class="stelwaarde" class:mono={level !== 1}
										>{level === 1
											? t('job.adjust.asDesigned')
											: `${level > 1 ? '+' : '−'}${Math.abs(
													Math.round((level - 1) * 100)
												)}%`}</span
									>
								</span>
								<div class="stelknoppen">
									{#each [-0.1, -0.01, 0.01, 0.1] as stap (stap)}
										<button
											class="rot stel"
											disabled={!connection.online}
											title={t(stap > 0 ? 'job.adjust.more' : 'job.adjust.less', {
												what: t(axis.key).toLowerCase()
											})}
											onclick={() => control.setAdjustment(axis.what, level + stap)}
											>{stap > 0 ? '+' : '−'}{Math.abs(Math.round(stap * 100))}%</button
										>
									{/each}
									<button
										class="rot stel terug"
										disabled={!connection.online || level === 1}
										title={t('job.adjust.resetTitle')}
										onclick={() => control.setAdjustment(axis.what, 1)}
										>{t('job.adjust.reset')}</button
									>
								</div>
							</div>
						{/if}
					{/each}
					<p class="hint">{t('job.adjust.hint')}</p>
				</div>
			{/if}
			{#if !control.capabilities?.motion?.focus && profile?.has_z}
				<!-- The profile says this machine has a Z axis, but the engine's driver
				     has no command for it. That is not a missing button but missing
				     support; say so. -->
				<p class="hint">{t('job.zAxis.noCommand')}</p>
			{/if}
			{#if profile?.has_autofocus}
				<!-- MeerK40t has no command to start an autofocus. A button that does
				     something *else* instead is worse than no button — so we say where it
				     is, in one sentence. -->
				<p class="hint">{t('job.autofocus')}</p>
			{/if}
		</div>
		</details>
	{/if}

	{#if actions && !actions.pause}
		<p class="hint">{t('job.noPause')}</p>
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
	   lezen nu `screen.controlsInBar`; de klasse hieronder is het gevolg,
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
	   kolom niet laten verspringen. De inkt (zwart of wit) komt uit `inkOn`:
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
