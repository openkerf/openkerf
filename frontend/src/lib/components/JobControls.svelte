<script lang="ts">
	import { formatDuration, isStalled, type Device, type Job } from '$lib/api';
	import type { Controller } from '$lib/control.svelte';
	import { verbinding } from '$lib/verbinding.svelte';
	import Segmented from './Segmented.svelte';

	let {
		control,
		device,
		job,
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
	};
	type SheetInfo = {
		name: string;
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
	let overzicht = $state<{ sheet?: SheetInfo | null; layers?: Layer[] } | null>(null);
	let layers = $derived(overzicht?.layers ?? []);

	// Wat de laag draagt tegenover waarin gebrand wordt. Dit is het laatste
	// moment waarop dat verschil nog iets kost dat je kunt terugdraaien.
	//
	// Eén regel per laag: twee bezwaren over dezelfde laag lazen als twee lagen,
	// omdat de naam er dan twee keer boven staat. En het zwaarste bezwaar eerst
	// — een gemeten instelling van het verkeerde materiaal is erger dan een
	// uitgerekende op het juiste, en dan moet die bovenaan staan.
	let mismatch = $derived(
		layers
			.filter((l) => l.warnings?.length)
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

	// Instellingen die niet gemeten zijn, verdienen een waarschuwing vóór het
	// materiaal in de machine ligt — niet erna.
	const ONZEKER: Record<string, string> = {
		geextrapoleerd: 'geëxtrapoleerd — niet gemeten',
		handmatig: 'handmatig ingesteld',
		geimporteerd: 'van iemand anders'
	};
	let risky = $derived(layers.filter((l) => l.source !== 'testraster'));

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
			const response = await fetch('/api/job/layers');
			overzicht = response.ok ? await response.json() : null;
		} catch {
			overzicht = null;
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

	$effect(() => {
		if (preflight) loadEstimate();
		else {
			estimate = null;
			overzicht = null;
		}
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
</script>

<div class="section">
	<h2 class="section-title">Bediening</h2>

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

	{#if preflight}
		<!-- Pre-flight in het paneel, geen modaal venster. -->
		<div class="preflight" class:niets={leeg}>
			<!-- "Geschatte tijd 0:00" boven een leeg bed leest als een job van nul
			     seconden in plaats van als geen job. Bij niets te doen zwijgt de
			     klok en spreekt de melding eronder. -->
			{#if !leeg}
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
				{#if velTekst}
					<div class="pf-time vel">
						<span class="muted">Materiaal</span>
						<span class="v">{velTekst}</span>
					</div>
				{/if}
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
										     als op het canvas en in de lagenlijst. -->
										{#if colorFor}
											<span class="chip" style:background={colorFor(layer.id)} aria-hidden="true"></span>
										{/if}{layer.label}
									</td>
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
				<div class="pf-actions een">
					<button class="btn" onclick={() => (preflight = false)}>Terug naar het ontwerp</button>
				</div>
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

			<!-- De kop langs de omtrek, zonder te branden: de laatste controle die
			     je écht kunt uitvoeren in plaats van alleen aanvinken. Stond alleen
			     in de bovenbalk; hier is het moment waarop je hem nodig hebt. -->
			{#if onFrame}
				<button
					class="btn kader"
					disabled={control.busy !== null || running}
					title="De kop langs de omtrek van je werk sturen — de laser blijft uit"
					onclick={() => onFrame?.()}
				>
					Eerst het kader tonen
				</button>
			{/if}

			<div class="pf-actions">
				<button class="btn" onclick={() => (preflight = false)}>Annuleren</button>
				<button
					class="btn primary"
					onclick={confirmStart}
					disabled={control.busy !== null || !verbinding.online}
					title={verbinding.online ? undefined : blockedReason}
				>
					{control.busy === 'start' ? 'Bezig…' : 'Nu starten'}
				</button>
			</div>
			{/if}
		</div>
	{:else}
		<div class="controls">
			<!-- Eén primaire knop per toestand. Stond "Job starten" ook tijdens een
			     lopende job in het accent, dan is de opvallendste knop op het scherm
			     degene die je niet moet hebben — en spoolt een tik er een tweede
			     job achteraan. -->
			<button
				class="btn dubbel"
				class:primary={!bezet}
				disabled={!actions?.start || blocked || bezet}
				title={bezet ? 'Er loopt al een job — eerst stoppen of afwachten' : blockedReason}
				onclick={() => (preflight = true)}
			>
				Job starten
			</button>
			{#if paused}
				<button
					class="btn primary dubbel"
					disabled={!actions?.resume || blocked}
					title={blockedReason}
					onclick={() => control.resume()}
				>
					Hervatten
				</button>
			{:else}
				<button
					class="btn dubbel"
					disabled={!actions?.pause || !running || blocked}
					title={running
						? blockedReason
						: 'Er loopt niets om te pauzeren'}
					onclick={() => control.pause()}
				>
					Pauze
				</button>
			{/if}
			<button
				class="btn subtle"
				disabled={!actions?.clear_queue || queued === 0 || blocked}
				title={queued === 0 ? 'De wachtrij is al leeg' : blockedReason}
				onclick={() => control.clearQueue()}
			>
				Wachtrij legen ({queued})
			</button>
			<!-- Stoppen kan altijd, in één tik — maar niet vlak naast pauze:
			     24px eronder, eigen breedte, zodat een mistik niet je werkstuk
			     kost. Zie DESIGN-SYSTEM v2, "Touch als eersteklas input". -->
			<!-- Sluimerend als er niets loopt, net als de stopknop in de bovenbalk.
			     Twee stopknoppen op één scherm met verschillend gedrag is erger
			     dan één: dan weet je niet meer welke van de twee iets betekent. -->
			<button
				class="btn danger stop dubbel"
				class:sluimer={!running && !paused}
				disabled={!actions?.stop || control.tokenProbleem || !verbinding.online}
				title={!verbinding.online
					? 'Geen verbinding met OpenKerf — stoppen kan alleen met de knop op de machine'
					: (blockedReason ?? 'Job direct afbreken')}
				onclick={() => control.stop()}
			>
				Stop
			</button>
			<!-- Op tablet dragen starten, pauzeren en stoppen vast in de bovenbalk
			     (die kan niet dichtklappen, dit paneel wel). Ze hier nog eens
			     herhalen maakt er drie van dezelfde knop op één scherm van 768px,
			     dus verwijzen we in plaats van te dupliceren. -->
			<p class="elders">
				Starten, pauzeren en stoppen staan vast in de balk bovenin.
			</p>
		</div>

	{/if}

	{#if !control.tokenProbleem}
		<!-- Beweging: nodig om uit te lijnen en het nulpunt te zetten. Deze
		     knoppen zetten de kop echt in beweging. -->
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
	.controls {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
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
		.controls {
			gap: var(--space-6);
		}
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
	.elders { display: none; }
	/* Tablet. Onder 768px rendert dit paneel niet — dan neemt PhoneView het over
	   — dus deze grens dekt precies het bereik waarin de bovenbalk zijn eigen
	   pauzeknop toont. Haalt de tablet-agent die knoppen daar weg, dan moet dit
	   mee: het is een afspraak tussen twee bestanden. */
	@media (max-width: 1199px) {
		.controls .dubbel { display: none; }
		.elders {
			display: block;
			grid-column: 1 / -1;
			margin: var(--space-2) 0 0;
			font-size: var(--text-xs);
			color: var(--text-2);
		}
	}
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
	.pf-name {
		max-width: 9em;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.unsure { color: var(--warn); }
	.pf-warn.strong { color: var(--warn); font-weight: 500; }
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
	.kader {
		width: 100%;
		margin-bottom: var(--space-3);
	}
	.pf-actions {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
	}
	.pf-actions.een { grid-template-columns: 1fr; }
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
	.btn.danger.sluimer {
		background: var(--surface-1);
		border-color: var(--danger-solid);
		color: var(--text-1);
	}
	.btn.danger.sluimer:hover:not(:disabled) {
		background: var(--danger-solid);
		color: var(--on-color);
	}
	.hint {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
</style>
