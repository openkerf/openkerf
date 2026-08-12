<script lang="ts">
	/**
	 * Stap 1: wat voor machine heb je?
	 *
	 * De catalogus van MeerK40t telt veertig bordnamen. Wie net begint kent er
	 * geen, maar weet wél of er een glazen buis met waterkoeling in staat. Deze
	 * stap vertaalt dat naar een handvol modellen in de volgende.
	 *
	 * En als de machine aanstaat hoeft die vertaalslag helemaal niet: dan zoekt
	 * OpenKerf hem op (besluit B6). Zoeken is lezen — er wordt niets aangemaakt,
	 * verbonden of geactiveerd tot je hier op "toevoegen" drukt.
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import Segmented from '$components/Segmented.svelte';
	import { KINDS, kindOfMachine, type CatalogFamily, type ScanResult, type Vondst } from '$lib/machines.svelte';
	import { createStore } from '$lib/setup.svelte';

	const store = createStore();
	onMount(() => store.loadCatalog());

	// Hoeveel modellen er achter elke soort zitten; een soort zonder modellen
	// hoort niet klikbaar te zijn.
	let aantallen = $derived(
		KINDS.map((kind) => ({
			...kind,
			count: store.catalog.reduce(
				(n: number, f: CatalogFamily) =>
					n + f.machines.filter((m) => kindOfMachine(m) === kind.id).length,
				0
			)
		}))
	);

	// ------------------------------------------------------------------ zoeken

	let zoekt = $state(false);
	let resultaat = $state<ScanResult | null>(null);
	let verstreken = $state(0);
	/** Voorbij deze grens is "even wachten" een aanname geworden. */
	const TRAAG = 8;
	let keuze = $state<Record<string, string>>({});
	let controller: AbortController | null = null;
	let tikker: ReturnType<typeof setInterval> | null = null;

	function stopTikker() {
		if (tikker) clearInterval(tikker);
		tikker = null;
	}

	async function zoek() {
		zoekt = true;
		resultaat = null;
		verstreken = 0;
		// Een teller in plaats van een balk: we weten niet hoe lang het duurt, en
		// een balk die niet weet hoe ver hij is, liegt. Verstreken tijd is waar.
		stopTikker();
		tikker = setInterval(() => (verstreken += 1), 1000);
		controller = new AbortController();
		try {
			const gevonden = await store.scan({ signal: controller.signal });
			if (gevonden) {
				resultaat = gevonden;
				keuze = Object.fromEntries(
					gevonden.candidates
						.filter((v) => v.suggestions.length)
						.map((v) => [v.id, v.suggestions[0].key])
				);
			}
		} finally {
			zoekt = false;
			controller = null;
			stopTikker();
		}
	}

	function afbreken() {
		controller?.abort();
	}

	/**
	 * Bevestigen. Hier begint het aanmaken pas — en zelfs dan niet meteen: je
	 * komt in de gewone stap "naam", waar je nog steeds terug kunt.
	 */
	function bevestig(vondst: Vondst) {
		const key = keuze[vondst.id] ?? vondst.suggestions[0]?.key;
		if (!key) return;
		const params = new URLSearchParams({ type: key });
		if (Object.keys(vondst.settings).length) {
			// De verbinding reist als parameter mee, zodat terugknop en verversen
			// blijven werken — dezelfde regel als voor de rest van de wizard.
			params.set('verbinding', JSON.stringify(vondst.settings));
			params.set('gevonden', `${vondst.title} op ${vondst.where}`);
		}
		goto(`/setup/naam?${params}`);
	}

	// Kort: de pil zegt langs welke weg, de regel eronder zegt precies waar. Een
	// pil van drie woorden duwt bovendien de titels uit elkaar.
	const TRANSPORT: Record<string, string> = {
		usb: 'USB',
		serieel: 'Serieel',
		netwerk: 'Netwerk'
	};

	/** Zekerheid krijgt een woord én een vorm — kleur alleen is niet genoeg. */
	const ZEKERHEID: Record<string, { woord: string; uitleg: string; icon: string }> = {
		zeker: {
			woord: 'Antwoordde',
			uitleg: 'Dit apparaat gaf zelf antwoord.',
			icon: 'M4 12.5 9 17.5 20 6.5'
		},
		waarschijnlijk: {
			woord: 'Waarschijnlijk',
			uitleg: 'Herkend aan de besturingschip, maar het apparaat zei niets terug.',
			icon: 'M12 3.5 22 20H2z'
		},
		onzeker: {
			woord: 'Gok',
			uitleg: 'Deze chip zit op meer dan één soort machine. Controleer het model zelf.',
			icon: 'M9 8.5a3 3 0 1 1 3 3.5v2M12 18.5v.01'
		}
	};
</script>

<svelte:head><title>OpenKerf — wat voor machine</title></svelte:head>

<section class="setup">
	{#if store.error}<p class="error" role="alert">{store.error}</p>{/if}

	<h1>Wat voor machine is het?</h1>
	<p class="muted">
		Staat de laser aan en hangt hij aan deze computer of aan hetzelfde netwerk, dan
		zoekt OpenKerf hem zelf op. Anders kies je hem hieronder uit de lijst.
	</p>

	<section class="zoeken" aria-labelledby="zoekkop">
		<div class="kop">
			<h2 id="zoekkop">Laat OpenKerf zoeken</h2>
			{#if !zoekt}
				<button class="btn primary" onclick={zoek}>
					{resultaat ? 'Opnieuw zoeken' : 'Machines zoeken'}
				</button>
			{/if}
		</div>

		{#if zoekt}
			<div class="bezig" role="status" aria-live="polite">
				<span class="ring" aria-hidden="true"></span>
				<div>
					<div class="bezigkop">
						Zoeken… <span class="mono">{verstreken}s</span>
					</div>
					<p class="muted">
						USB en seriële poorten zijn zo bekeken; het netwerk kost een paar seconden,
						omdat elk adres in je subnet één vraag krijgt.
					</p>
					{#if verstreken >= TRAAG}
						<!-- Dit hoort binnen drie seconden klaar te zijn. Duurt het langer,
						     dan is er iets aan de hand en verdient de gebruiker een weg
						     vooruit in plaats van een ronddraaiend rondje. -->
						<p class="traag">
							Dit duurt langer dan normaal. Je kunt gerust stoppen en de machine
							hieronder zelf kiezen — dat levert precies hetzelfde op.
						</p>
					{/if}
				</div>
				<button class="btn subtle" onclick={afbreken}>Stoppen</button>
			</div>
		{/if}

		<!-- De belofte blijft ook tijdens het zoeken staan: juist dán vraag je je
		     af wat er met je machine gebeurt. -->
		<p class="belofte">
			<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" />
			</svg>
			Zoeken kijkt alleen. Er wordt niets aangemaakt en er gaat geen opdracht naar
			een machine tot jij hieronder op toevoegen drukt.
		</p>

		{#if resultaat && !zoekt}
			{#if resultaat.candidates.length}
				<h3 class="uitslag">
					{resultaat.candidates.length === 1
						? 'Eén machine gevonden'
						: `${resultaat.candidates.length} machines gevonden`}
				</h3>
				<ul class="vondsten">
					{#each resultaat.candidates as vondst (vondst.id)}
						{@const zeker = ZEKERHEID[vondst.confidence] ?? ZEKERHEID.onzeker}
						<li class="vondst" class:gok={vondst.confidence === 'onzeker'}>
							<!-- Gestapeld, niet naast elkaar: op 390 px werd de titel anders een
							     kolom van twee woorden breed en brak een IP-adres middenin. -->
							<div class="regel">
								<span class="transport">{TRANSPORT[vondst.transport] ?? vondst.transport}</span>
								<span class="zekerheid" title={zeker.uitleg}>
									<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
										<path d={zeker.icon} />
									</svg>
									{zeker.woord}
								</span>
							</div>
							<div class="titel">{vondst.title}</div>
							<div class="waar mono">
								{vondst.where}{vondst.detail ? ` · ${vondst.detail}` : ''}
							</div>

							<p class="waarom">{vondst.why}</p>

							{#if vondst.suggestions.length > 1}
								<div class="model">
									<span class="modelkop">Welk model?</span>
									{#if vondst.suggestions.length <= 4}
										<Segmented
											label="Model"
											options={vondst.suggestions.map((s) => ({ value: s.key, label: s.label }))}
											bind:value={keuze[vondst.id]}
										/>
									{:else}
										<select bind:value={keuze[vondst.id]}>
											{#each vondst.suggestions as suggestie (suggestie.key)}
												<option value={suggestie.key}>{suggestie.label}</option>
											{/each}
										</select>
									{/if}
								</div>
							{:else if vondst.suggestions.length === 1}
								<p class="model enkel">
									Voorstel: <strong>{vondst.suggestions[0].label}</strong>
									<span class="muted">({vondst.suggestions[0].family})</span>
								</p>
							{/if}

							<div class="doen">
								{#if vondst.suggestions.length}
									<button class="btn primary" onclick={() => bevestig(vondst)}>
										Deze toevoegen
									</button>
								{:else}
									<p class="muted geenmodel">
										We herkennen het apparaat, maar niet welk model erachter zit — dat model
										kent deze installatie niet. Kies hem hieronder zelf; dat er iets
										aangesloten is, weet je nu in elk geval.
									</p>
								{/if}
							</div>
						</li>
					{/each}
				</ul>
			{:else}
				<div class="niets">
					<h3>Niets gevonden</h3>
					<p>
						Staat de machine aan en zit de kabel erin? Kies hem anders hieronder zelf —
						dat werkt net zo goed.
					</p>
					{#if resultaat.notes.length === 1}
						<p class="muted">{resultaat.notes[0]}</p>
					{:else if resultaat.notes.length}
						<ul class="notities">
							{#each resultaat.notes as notitie}<li>{notitie}</li>{/each}
						</ul>
					{/if}
					<!-- Waar gekeken is, hoort erbij: zonder dat is "niets gevonden" niet te
					     controleren en dus niet te vertrouwen. -->
					<p class="muted herkomst mono">
						Gezocht in {resultaat.searched.join(', ') || 'niets'} · {(
							resultaat.duration_ms / 1000
						).toFixed(1)}s
					</p>
				</div>
			{/if}
		{/if}
	</section>

	<h2 class="zelfkop">Of kies zelf</h2>
	<p class="muted">
		Kies wat er in je werkplaats staat. De volgende stap toont alleen de modellen
		die daarbij horen — en weet je het precies, dan kun je daar zoeken.
	</p>

	<ul class="soorten">
		{#each aantallen as kind (kind.id)}
			<li>
				<a
					class="soort"
					class:leeg={kind.count === 0}
					href={kind.count ? `/setup/type?soort=${kind.id}` : undefined}
					aria-disabled={kind.count === 0}
				>
					<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
						<path d={kind.icon} />
					</svg>
					<span class="naam">{kind.label}</span>
					<span class="uitleg">{kind.blurb}</span>
					<span class="hoeveel mono">
						{kind.count === 0 ? 'geen modellen' : `${kind.count} model${kind.count === 1 ? '' : 'len'}`}
					</span>
				</a>
			</li>
		{/each}
	</ul>

	<p class="anders">
		Staat jouw machine er niet tussen?
		<a href="/setup/type">Bekijk de volledige lijst</a>.
	</p>
</section>

<style>
	/* ------------------------------------------------------------- zoekblok */
	.zoeken {
		margin: var(--space-4) 0 var(--space-8);
		padding: var(--space-4);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	.kop {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		flex-wrap: wrap;
	}
	.zoeken h2 {
		flex: 1;
		margin: 0;
		font-size: var(--text-md);
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	/* De belofte uit het besluit staat op het scherm, niet alleen in een
	   document: wie op een knop drukt die een laser kan raken, hoort te weten
	   dat deze dat niet doet. */
	.belofte {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		margin: var(--space-3) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.belofte svg {
		flex: none;
		margin-top: 1px;
	}

	.bezig {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin-top: var(--space-3);
	}
	.bezigkop {
		font-weight: 500;
	}
	.bezig p {
		margin: 2px 0 0;
		font-size: var(--text-xs);
	}
	.bezig .traag {
		color: var(--text-1);
		border-left: 3px solid var(--warn);
		padding-left: var(--space-2);
		margin-top: var(--space-2);
	}
	.bezig > div {
		flex: 1;
		min-width: 0;
	}
	.ring {
		flex: none;
		width: 20px;
		height: 20px;
		border-radius: 999px;
		border: 2px solid var(--line);
		border-top-color: var(--accent);
		animation: draai 900ms linear infinite;
	}
	@keyframes draai {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.ring {
			animation-duration: 3s;
		}
	}

	.uitslag,
	.niets h3 {
		margin: var(--space-4) 0 var(--space-2);
		font-size: var(--text-sm);
		font-weight: 600;
	}

	.vondsten {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: var(--space-2);
	}
	.vondst {
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		/* Randstreep in de kleur van de zekerheid: zichtbaar tijdens scrollen,
		   ook zonder te lezen (DESIGN-SYSTEM v3.1, "zekerheid is een zin"). */
		border-left: 3px solid var(--ok);
		box-shadow: var(--lift-1);
	}
	.vondst.gok {
		border-left-color: var(--warn);
	}
	.regel {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		margin-bottom: var(--space-2);
	}
	.titel {
		font-weight: 600;
	}
	.waar {
		font-size: var(--text-xs);
		color: var(--text-2);
		overflow-wrap: anywhere;
	}
	.transport {
		font-size: var(--text-xs);
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-dot);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.zekerheid {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1h);
		font-size: var(--text-xs);
		color: var(--text-1);
	}
	.zekerheid svg {
		color: var(--ok);
	}
	.gok .zekerheid svg {
		color: var(--warn);
	}
	.waarom {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	.model {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin-top: var(--space-3);
	}
	.modelkop {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.model.enkel {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xs);
	}
	/* Segmented geeft elk vak `flex: 1` — en dat is `1 1 0%`, dus alle vakken
	   worden even breed en het langste label wordt afgekapt ("GRBL (generie").
	   Elders staan er alleen labels van gelijke lengte in, dus dit repareren we
	   hier in plaats van in het gedeelde component. */
	.model :global(.segmented button) {
		flex: 0 1 auto;
	}
	.model select {
		font: inherit;
		font-size: var(--text-xs);
		padding: var(--space-1h) var(--space-2);
		min-height: 40px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.doen {
		margin-top: var(--space-3);
	}
	.geenmodel {
		margin: 0;
		font-size: var(--text-xs);
	}

	.niets {
		margin-top: var(--space-3);
		padding: var(--space-3);
		border: 1px dashed var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
	}
	.niets p {
		margin: 0 0 var(--space-2);
		font-size: var(--text-xs);
	}
	.niets p:last-child {
		margin-bottom: 0;
	}
	.herkomst {
		font-size: var(--text-xs);
	}
	.notities {
		margin: var(--space-2) 0;
		padding-left: 1.1em;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.notities li {
		margin-bottom: 4px;
	}

	/* --------------------------------------------------------- eigen keuze */
	.zelfkop {
		margin: 0 0 var(--space-2);
		font-size: var(--text-md);
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.soorten {
		list-style: none;
		margin: var(--space-4) 0 0;
		padding: 0;
		display: grid;
		/* Vier kaarten in drie kolommen laten een gat van twee kolommen op de
		   tweede rij; op 320 wordt het 2×2 en staat het raster vol. */
		grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
		gap: var(--space-3);
	}
	.soort {
		display: grid;
		gap: var(--space-2);
		/* Gelijke hoogte, wat de tekst ook doet: een rafelig raster van kaarten
		   leest als een lijst met fouten erin. */
		height: 100%;
		align-content: start;
		padding: var(--space-4);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		color: inherit;
		text-decoration: none;
		box-shadow: var(--lift-1);
	}
	.soort:hover { border-color: var(--accent); }
	.soort svg { color: var(--accent); }
	.naam { font-weight: 600; }
	.uitleg { font-size: var(--text-xs); color: var(--text-2); }
	.hoeveel { font-size: var(--text-xs); color: var(--text-2); margin-top: 4px; }
	.soort.leeg { opacity: 0.5; pointer-events: none; }
	.anders { margin-top: var(--space-4); font-size: var(--text-xs); color: var(--text-2); }
	.anders a { color: var(--accent-text); }

	/* Raakdoelen op tablet en telefoon. */
	@media (max-width: 1199px) {
		.model select {
			min-height: 44px;
		}
		.zoeken :global(.btn) {
			min-height: 44px;
		}
	}
	/* Op 390 px brak "Laat OpenKerf zoeken" over drie regels naast de knop, en
	   stond die knop scheef in het overgebleven gat. Dan maar onder elkaar. */
	@media (max-width: 560px) {
		.kop {
			display: grid;
		}
		.zoeken :global(.btn) {
			justify-content: center;
		}
		.bezig {
			display: grid;
			gap: var(--space-2);
			grid-template-columns: auto 1fr;
			/* Naast een blok van vier regels hangt een gecentreerde ring in de
			   lucht; hij hoort bij de kop "Zoeken…". */
			align-items: start;
		}
		.ring {
			margin-top: 2px;
		}
		.bezig > button {
			grid-column: 1 / -1;
			justify-content: center;
		}
	}
</style>
