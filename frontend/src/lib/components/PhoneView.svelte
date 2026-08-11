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
	import { formatDuration, STATE_LABEL, type Device, type Job, type MachineState } from '$lib/api';
	import type { Controller } from '$lib/control.svelte';
	import type { CameraStore } from '$lib/camera.svelte';
	import Verbinding from './Verbinding.svelte';
	import { verbinding } from '$lib/verbinding.svelte';

	let {
		device,
		state: machineState,
		job,
		control,
		camera,
		connected,
		position
	}: {
		device: Device | null;
		state: MachineState;
		job: Job | null;
		control: Controller;
		camera: CameraStore;
		connected: boolean;
		position: string;
	} = $props();

	// `job` is alleen de lópende job. Een gepauzeerde job valt daar buiten, en
	// die verdween daardoor compleet van dit scherm: je pauzeerde en het scherm
	// meldde "geen job actief", zonder knop om te hervatten. De spooler weet
	// beter, dus die vragen we.
	let wachtrij = $derived(device?.spooler.jobs ?? []);
	let huidig = $derived<Job | null>(job ?? wachtrij[0] ?? null);
	let running = $derived(Boolean(job?.running));
	// Stilstaand werk: pauze zet bij de ene driver `running` op false en laat
	// hem bij de andere staan terwijl de laserstatus omslaat. Beide gevallen
	// betekenen hier hetzelfde — er ligt werk dat niet vooruitkomt.
	let stil = $derived(Boolean(huidig) && (!running || machineState === 'paused'));

	// De kop is de belangrijkste regel van dit scherm; die mag niet "Gereed"
	// zeggen terwijl de spooler brandt. Sommige drivers melden hun laserstatus
	// pas laat (of nooit); een lopende job is bewijs genoeg.
	let staat = $derived<MachineState>(
		!connected ? 'offline' : stil ? 'paused' : running ? 'busy' : machineState
	);

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

	// Een job die nog nooit gelopen heeft staat in de wachtrij; een job die
	// halverwege stilviel is gepauzeerd. Voor de kijker is dat verschil groot.
	let stilLabel = $derived(/wait/i.test(huidig?.status ?? '') ? 'in de wachtrij' : 'gepauzeerd');

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
	 * Zodra de job een eind op weg is, is het gemeten tempo betrouwbaarder dan
	 * de vooraf berekende schatting; daaronder valt hij terug op die schatting.
	 */
	let resterend = $derived.by(() => {
		if (!huidig) return null;
		const verstreken = huidig.elapsed_seconds ?? 0;
		if (progress > 0.05 && verstreken > 5) return Math.max(0, verstreken / progress - verstreken);
		const schatting = huidig.estimate_seconds;
		if (schatting == null) return null;
		return Math.max(0, schatting * (1 - progress));
	});

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
		created_at: string;
	};
	let wachtend = $state<Raster[]>([]);
	let bezig = $state<number | null>(null);
	/** Een rij die verdwijnt is te stil; dit vertelt wat er nu gebeurd is. */
	let gelukt = $state<string | null>(null);

	/** Veel materiaalnamen dragen de dikte al ("Berkentriplex 4 mm"); dan niet
	    nog eens "4 mm" erachter plakken. */
	function rasterNaam(g: Raster): string {
		const naam = g.material_name ?? 'raster';
		if (!g.thickness_mm || /\bmm\b/i.test(naam)) return naam;
		return `${naam} ${g.thickness_mm} mm`;
	}

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

	async function haalRasters() {
		const r = await fetch('/api/library/testgrids');
		if (!r.ok) return;
		wachtend = (await r.json()).filter((g: Raster) => !g.photo_path);
	}
	$effect(() => {
		haalRasters();
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
	 * De engine noemt een naamloze job "Spooler:1 items".
	 *
	 * Dat is de interne opsomming van de wachtrij, geen titel. Op de enige
	 * regel die zegt wát er brandt hoort geen debug-tekst te staan.
	 */
	let jobNaam = $derived.by(() => {
		const label = huidig?.label ?? '';
		const m = label.match(/^Spooler:\s*(\d+)\s*items?$/i);
		if (!m) return label || 'Naamloze job';
		const n = Number(m[1]);
		return `${n} ${n === 1 ? 'bewerking' : 'bewerkingen'}`;
	});

	let bedW = $derived(device?.bed.width_mm ?? 0);
	let bedH = $derived(device?.bed.height_mm ?? 0);
	let kop = $derived(device?.position.mm ?? null);
</script>

<Verbinding brandt={running} />

<div class="telefoon">
	<header>
		<span class="dot {staat}" aria-hidden="true"></span>
		<span class="staat">{connected ? STATE_LABEL[staat] : 'Geen verbinding'}</span>
		<span class="machine mono">{device?.label ?? 'geen machine'}</span>
	</header>

	<div class="rol">
		{#if camAan}
			<!-- Camera boven alles: als je kunt kijken, kijk je. -->
			<div class="podium">
				<img src={camera.src} alt="Camerabeeld van het bed" onerror={() => (beeldStuk = true)} />
			</div>
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
						<span class="onder">{stilLabel}</span>
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
				<span class="titel">{jobNaam}</span>
				<span class="mono muted">{huidig.steps_done} / {huidig.steps_total}</span>
			</div>
		{:else}
			<!-- Niets brandt. Dan is de vraag niet "hoe ver" maar "waar staat de
			     kop en wat is dit voor machine" — en dat is te tekenen. -->
			<div class="rust">
				{#if bedW > 0 && bedH > 0}
					<svg class="bedje" viewBox="0 0 {bedW} {bedH}" role="img"
						aria-label="Bed {Math.round(bedW)} bij {Math.round(bedH)} millimeter, kop op {position}">
						<rect class="vlak" x="0" y="0" width={bedW} height={bedH} vector-effect="non-scaling-stroke" />
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
				</dl>
				<!-- Een bed zonder job zei alleen "Gereed" bovenin. Dat is een
				     toestand, geen antwoord: wie hier kijkt wil weten of het stil is
				     omdat het klaar is, of stil omdat er iets mis is. -->
				<p class="waarom">
					{#if !connected}
						Dit is de laatste stand die we gezien hebben.
					{:else if staat === 'unplugged'}
						Er hangt geen machine aan de server. Controleer of hij aanstaat en
						of de kabel erin zit.
					{:else}
						Niets aan het branden. Een job start je op de desktop.
					{/if}
				</p>
			</div>
		{/if}

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

		{#if gelukt}
			<p class="goed" role="status">{gelukt}</p>
		{/if}

		{#if wachtend.length}
			<section class="rasters">
				<h2>
					{wachtend.length}
					{wachtend.length === 1 ? 'testraster wacht' : 'testrasters wachten'} op een foto
				</h2>
				{#each wachtend as grid (grid.id)}
					<label class="raster">
						<span class="naam">
							<span class="kop">{rasterNaam(grid)} · {grid.operation}</span>
							<span class="detail mono">
								{grid.speed_min}–{grid.speed_max} mm/s · {grid.power_min}–{grid.power_max}% ·
								{stempel(grid.created_at)}
							</span>
						</span>
						<span class="knop">{bezig === grid.id ? 'bezig…' : 'Foto maken'}</span>
						<input
							type="file"
							accept="image/*"
							capture="environment"
							aria-label="Foto van testraster {grid.id}"
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
	.bedje { width: 100%; height: auto; max-height: 24vh; display: block; }
	/* --bed is wit en de kaart is dat ook: in het lichte thema was het bed dan
	   onzichtbaar. --canvas-bg staat in beide thema's los van de kaart. */
	.bedje .vlak { fill: var(--canvas-bg); stroke: var(--line); stroke-width: 1; }
	.bedje .kop line { stroke: var(--accent); stroke-width: 1; stroke-dasharray: 4 4; opacity: 0.7; }
	.bedje .kop circle { fill: var(--accent); }
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

	.rasters { flex: none; display: grid; gap: var(--space-2); }
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

	.elders {
		flex: none;
		margin: var(--space-2) 0 0;
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
