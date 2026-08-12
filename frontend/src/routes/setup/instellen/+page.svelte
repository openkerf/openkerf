<script lang="ts">
	/**
	 * Stap 4: het werkgebied.
	 *
	 * Dit was een kale doorgifte van de engine: "Width — Width of the laser
	 * bed.", "Force Declared Home — Override native home location", "Flip X",
	 * en twee velden die allebei "Swap XY" heten. Engels, ontwikkelaarstaal, en
	 * de bedmaat — het enige wat op deze pagina echt fout kán gaan — had exact
	 * hetzelfde gewicht als "Flip Y".
	 *
	 * Nu: bedmaat en oorsprong zijn een eigen blok met eigen woorden en een
	 * tekening die meebeweegt. De rest van de engine-velden blijft bestaan,
	 * maar staat onder "Meer van deze machine" en achter "Alle instellingen".
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import SettingFieldInput from '$components/SettingField.svelte';
	import NumberField from '$components/NumberField.svelte';
	import { createStore } from '$lib/setup.svelte';
	import type { SettingField } from '$lib/machines.svelte';

	const store = createStore();

	let machinePath = $derived($page.url.searchParams.get('machine') ?? '');
	let values = $state<Record<string, unknown>>({});
	let essentialOnly = $state(true);

	/** Wat wij zelf in beeld brengen; de engine mag het niet nóg een keer tonen. */
	const EIGEN = ['bedwidth', 'bedheight', 'home_corner'];

	/**
	 * Wat de zoekknop van stap 1 gevonden heeft (besluit B6).
	 *
	 * De poort of het IP-adres komt als parameter mee en wordt hier ingevuld —
	 * zichtbaar, en pas vastgelegd als je op opslaan drukt. Niets van dit alles
	 * legt verbinding; dat gebeurt bij de eerste job.
	 */
	let verbinding = $derived.by(() => {
		const rauw = $page.url.searchParams.get('verbinding');
		if (!rauw) return null;
		try {
			const uit = JSON.parse(rauw);
			return uit && typeof uit === 'object' ? (uit as Record<string, string>) : null;
		} catch {
			return null;
		}
	});

	const VERBINDINGSWOORD: Record<string, string> = {
		interface: 'Verbinding',
		address: 'Adres',
		serial_port: 'Poort'
	};
	/** "udp" is de sleutel van de engine, geen woord voor op het scherm. */
	const VERBINDINGSWAARDE: Record<string, string> = {
		udp: 'netwerk (UDP)',
		usb: 'USB'
	};

	async function reload() {
		if (!machinePath) return;
		const sheets = await store.loadSettings(machinePath, essentialOnly);
		values = Object.fromEntries(
			sheets.flatMap((sheet) => sheet.fields.map((field) => [field.attr, field.value]))
		);
		// Alleen invullen wat deze machine ook echt kent: een `serial_port` op
		// een apparaat dat er geen heeft, wordt door de API afgewezen.
		if (verbinding) {
			for (const [attr, waarde] of Object.entries(verbinding)) {
				if (attr in values) values[attr] = waarde;
			}
		}
	}

	onMount(reload);

	/**
	 * De engine registreert bedwidth als Length en geeft een string met eenheid
	 * terug. De stepper rekent in millimeters, dus de eenheid moet meegerekend
	 * worden — niet weggegooid.
	 *
	 * Ruida staat standaard op "24.0in". Alleen de cijfers pakken maakte daar een
	 * bed van 24 bij 16 millimeter van: een canvas ter grootte van een postzegel,
	 * en niemand die kon zien waarom.
	 */
	const NAAR_MM: Record<string, number> = { mm: 1, cm: 10, in: 25.4, mil: 0.0254 };

	function alsGetal(waarde: unknown): string {
		const tekst = String(waarde ?? '').trim();
		const gevonden = tekst.match(/^\s*(-?\d+(?:\.\d+)?)\s*([a-zA-Z]*)/);
		if (!gevonden) return '0';
		const factor = NAAR_MM[gevonden[2].toLowerCase()] ?? 1;
		const mm = Number(gevonden[1]) * factor;
		// Geen sleep van drijvende-komma-cijfers achter een maat in millimeters.
		return String(Math.round(mm * 100) / 100);
	}

	let breedte = $state('0');
	let hoogte = $state('0');
	let geladen = $state(false);

	$effect(() => {
		if (geladen || !('bedwidth' in values)) return;
		breedte = alsGetal(values.bedwidth);
		hoogte = alsGetal(values.bedheight);
		geladen = true;
	});

	// Waar de kop naartoe gaat als je "home" zegt. De engine noemt dit
	// "Force Declared Home"; in de werkplaats is het gewoon de hoek waar de kop
	// naartoe kruipt als je hem aanzet.
	const HOEKEN = [
		{ id: 'auto', label: 'Zoals de machine zelf zegt' },
		{ id: 'top-left', label: 'Linksboven' },
		{ id: 'top-right', label: 'Rechtsboven' },
		{ id: 'bottom-left', label: 'Linksonder' },
		{ id: 'bottom-right', label: 'Rechtsonder' },
		{ id: 'center', label: 'Midden' }
	];
	let heeftHoek = $derived('home_corner' in values);
	let hoek = $derived(String(values.home_corner ?? 'auto'));

	/** Positie van de oorsprongstip in de tekening, in procenten. */
	let stip = $derived(
		{
			'top-left': { x: 0, y: 0 },
			'top-right': { x: 100, y: 0 },
			'bottom-left': { x: 0, y: 100 },
			'bottom-right': { x: 100, y: 100 },
			center: { x: 50, y: 50 }
		}[hoek] ?? null
	);

	// De tekening is een gewone SVG in pixels, niet in millimeters: de val uit
	// DESIGN-SYSTEM ("elke CSS-lengte is dan een millimeter") wordt zo nooit
	// gezet. Alleen de vórm van het bed volgt de verhouding.
	const TEKENING = { w: 200, h: 130 };
	/** Marge rondom, zodat het bed als vlak ín een werkruimte leest. */
	const RUIMTE = { w: 176, h: 108 };
	let verhouding = $derived(
		Math.max(0.2, Math.min(4, (Number(breedte) || 1) / (Number(hoogte) || 1)))
	);
	let bedDoos = $derived(
		verhouding >= RUIMTE.w / RUIMTE.h
			? { w: RUIMTE.w, h: RUIMTE.w / verhouding }
			: { w: RUIMTE.h * verhouding, h: RUIMTE.h }
	);

	/**
	 * Alles wat de engine kent behalve wat we hierboven zelf tonen.
	 *
	 * Ontdubbelen op attribuut: `swap_xy` staat bij Newly in twee bladen, met
	 * twee verschillende omschrijvingen van hetzelfde vinkje. Dat leverde niet
	 * alleen twee identieke rijen "Swap XY" op, maar met één lijst ook een
	 * dubbele sleutel — waarop Svelte het hele blok liet vallen en er dus
	 * niets meer te zien was.
	 */
	let restVelden = $derived.by(() => {
		const gezien = new Set(EIGEN);
		const velden: SettingField[] = [];
		for (const sheet of store.settings) {
			for (const field of sheet.fields) {
				if (gezien.has(field.attr)) continue;
				gezien.add(field.attr);
				velden.push(field);
			}
		}
		return velden;
	});
	let restOpen = $state(false);

	async function save() {
		if ('bedwidth' in values) {
			values.bedwidth = `${Number(breedte) || 0}mm`;
			values.bedheight = `${Number(hoogte) || 0}mm`;
		}
		if (Object.keys(values).length) {
			if (!(await store.updateSettings(machinePath, values))) return;
		}
		await bewaarProfiel();
		await goto(`/setup/klaar?machine=${encodeURIComponent(machinePath)}`);
	}

	// Het bibliotheekprofiel hoort bij dit apparaat; de vinkjes hieronder leven
	// daar, niet in de engine.
	let heeftZ = $state(false);
	let heeftAutofocus = $state(false);
	let profielId = $state<number | null>(null);

	$effect(() => {
		if (!machinePath) return;
		(async () => {
			const response = await fetch('/api/library/active-machine');
			if (!response.ok) return;
			const profiel = await response.json();
			if (profiel.device_path !== machinePath) return;
			profielId = profiel.id;
			heeftZ = Boolean(profiel.has_z);
			heeftAutofocus = Boolean(profiel.has_autofocus);
		})();
	});

	async function bewaarProfiel() {
		if (profielId === null) return;
		const token = localStorage.getItem('openkerf.token') ?? '';
		await fetch(`/api/library/machines/${profielId}`, {
			method: 'PATCH',
			headers: {
				'Content-Type': 'application/json',
				...(token ? { Authorization: `Bearer ${token}` } : {})
			},
			body: JSON.stringify({ has_z: heeftZ, has_autofocus: heeftAutofocus })
		});
	}
</script>

<svelte:head><title>OpenKerf — werkgebied</title></svelte:head>

<section class="setup">
	{#if store.error}<p class="error" role="alert">{store.error}</p>{/if}

	{#if !machinePath}
		<h1>Geen machine gekozen</h1>
		<p class="muted">Begin bij het overzicht en kies of maak een machine.</p>
		<div class="actions"><a class="btn primary" href="/setup">Naar het overzicht</a></div>
	{:else}
		{#if verbinding}
			{@const ingevuld = Object.entries(verbinding).filter(([attr]) => attr in values)}
			<p class="verbinding">
				<strong>Verbinding uit het zoeken ingevuld.</strong>
				{#if ingevuld.length}
					<span class="mono">
						{ingevuld
							.map(
								([attr, waarde]) =>
									`${VERBINDINGSWOORD[attr] ?? attr}: ${VERBINDINGSWAARDE[waarde] ?? waarde}`
							)
							.join(' · ')}
					</span>
				{:else}
					<span class="muted">Deze machine kent die instellingen niet; er is niets gewijzigd.</span>
				{/if}
				<span class="muted">
					Je legt hem hiermee nog niet aan: OpenKerf praat pas met de machine als je een job
					start.
				</span>
			</p>
		{/if}

		<h1>Hoe groot is het bed?</h1>
		<p class="muted">
			Meet het werkgebied, niet de buitenkant van de kast. Dit wordt het bed op je canvas —
			klopt het niet, dan denkt OpenKerf dat er ruimte is waar de kop niet komt.
		</p>

		<div class="werkgebied">
			<div class="velden">
				{#if 'bedwidth' in values}
					<NumberField label="Breedte" unit="mm" bind:value={breedte} step={10} min={1} />
					<NumberField label="Hoogte" unit="mm" bind:value={hoogte} step={10} min={1} />
				{:else}
					<p class="muted">Deze machine geeft geen bedmaat op.</p>
				{/if}

				{#if heeftHoek}
					<label class="keuze">
						<span>Waar ligt 0,0?</span>
						<select
							value={hoek}
							onchange={(e) => (values.home_corner = e.currentTarget.value)}
						>
							{#each HOEKEN as optie (optie.id)}
								<option value={optie.id}>{optie.label}</option>
							{/each}
						</select>
						<span class="hint">
							De hoek waar de kop naartoe gaat als je hem naar huis stuurt. Weet je het niet,
							laat dan staan wat de machine zelf zegt.
						</span>
					</label>
				{/if}
			</div>

			<figure class="tekening">
				<svg viewBox="0 0 {TEKENING.w} {TEKENING.h}" role="img"
					aria-label="Het bed is {breedte} bij {hoogte} millimeter">
					<defs>
						<pattern id="bedgrid" width="10" height="10" patternUnits="userSpaceOnUse">
							<path d="M10 0 L0 0 0 10" fill="none" stroke="var(--line)" stroke-width="0.5" />
						</pattern>
					</defs>
					<rect width={TEKENING.w} height={TEKENING.h} class="plaat" />
					<g transform="translate({(TEKENING.w - bedDoos.w) / 2} {(TEKENING.h - bedDoos.h) / 2})">
							<rect width={bedDoos.w} height={bedDoos.h} class="bed" />
							<rect width={bedDoos.w} height={bedDoos.h} fill="url(#bedgrid)" />
							<rect width={bedDoos.w} height={bedDoos.h} class="rand" />
							{#if stip}
								<circle
									cx={(bedDoos.w * stip.x) / 100}
									cy={(bedDoos.h * stip.y) / 100}
									r="3.5"
									class="oorsprong"
								/>
							{/if}
					</g>
				</svg>
				<figcaption>
					<span class="maat mono">{breedte} × {hoogte} mm</span>
					{#if stip}0,0 ligt op de stip.{:else}De machine bepaalt zelf waar 0,0 ligt.{/if}
				</figcaption>
			</figure>
		</div>

		<!-- Wat de machine kán. Dit staat niet in de engine — het is een uitspraak
		     van de gebruiker over zijn eigen apparaat, en het bepaalt wat er in de
		     jog-bediening verschijnt. -->
		<fieldset class="kunnen">
			<legend>Wat heeft deze machine?</legend>
			<label class="toggle">
				<input type="checkbox" bind:checked={heeftZ} />
				<span>Een Z-as (in hoogte verstelbaar bed of kop)</span>
			</label>
			<label class="toggle">
				<input type="checkbox" bind:checked={heeftAutofocus} />
				<span>Autofocus</span>
			</label>
		</fieldset>

		{#if restVelden.length}
			<details class="rest" bind:open={restOpen}>
				<summary>
					Meer van deze machine
					<span class="muted">— spiegelen, verbinding, en wat de engine verder kent</span>
				</summary>
				<p class="muted waarschuwing">
					Deze velden komen rechtstreeks uit MeerK40t en staan daarom in het Engels. Je hebt
					ze alleen nodig als je machine gespiegeld of gedraaid werkt; anders kun je ze
					laten staan.
				</p>
				<label class="toggle">
					<input
						type="checkbox"
						checked={!essentialOnly}
						onchange={(e) => {
							essentialOnly = !e.currentTarget.checked;
							geladen = false;
							reload();
						}}
					/>
					<span>Ook alles tonen wat we normaal verbergen</span>
				</label>
				{#each restVelden as field (field.attr)}
					<SettingFieldInput {field} bind:value={values[field.attr]} />
				{/each}
			</details>
		{/if}

		<div class="actions">
			<a class="btn" href="/setup">Overslaan</a>
			<button class="btn primary" onclick={save} disabled={store.busy}>
				{store.busy ? 'Opslaan…' : 'Opslaan en afronden'}
			</button>
		</div>
	{/if}
</section>

<style>
	.verbinding {
		display: grid;
		gap: 4px;
		margin: 0 0 var(--space-4);
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-xs);
		border-left: 3px solid var(--ok);
		background: var(--surface-2);
		border-radius: var(--radius-field);
	}
	.verbinding .muted {
		color: var(--text-2);
	}
	.werkgebied {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: var(--space-6);
		align-items: start;
		margin: var(--space-4) 0;
	}
	.velden {
		display: grid;
		gap: var(--space-3);
		min-width: 0;
		/* Een stepper van 520px voor een getal van drie cijfers zet − en + zo ver
		   uit elkaar dat je ze niet meer als één bediening leest. */
		max-width: 320px;
	}
	.keuze {
		display: grid;
		gap: 4px;
	}
	.keuze > span:first-child {
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.keuze select {
		font: inherit;
		padding: 8px;
		min-height: 40px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.hint {
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	.tekening {
		margin: 0;
		width: 240px;
	}
	.tekening svg {
		width: 100%;
		height: auto;
		display: block;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
	}
	/* Het bed lag als wit vlak op een witte kaart en las als een lege doos. Nu
	   staat het op dezelfde ondergrond als op het canvas, mét mm-raster: dan
	   herken je waar je naar kijkt zonder onderschrift. */
	.tekening .plaat {
		fill: var(--canvas-bg);
	}
	.tekening .bed {
		fill: var(--bed);
	}
	.tekening .rand {
		fill: none;
		stroke: var(--text-2);
		stroke-width: 1;
	}
	.tekening .oorsprong {
		fill: var(--accent);
	}
	.tekening figcaption {
		display: grid;
		gap: 2px;
		font-size: var(--text-xs);
		color: var(--text-2);
		text-align: center;
		margin-top: var(--space-2);
	}
	.tekening .maat {
		color: var(--text-1);
	}

	.kunnen {
		margin: var(--space-4) 0;
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		display: grid;
		gap: var(--space-2);
	}
	.kunnen legend { font-size: var(--text-xs); color: var(--text-2); padding: 0 4px; }

	.rest {
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		padding: var(--space-3);
	}
	.rest summary {
		cursor: pointer;
		font-weight: 500;
		/* Een samenvouwrij is een raakdoel, ook met een handschoen aan. */
		min-height: 32px;
		display: flex;
		align-items: center;
		gap: var(--space-1h);
		flex-wrap: wrap;
	}
	.rest .waarschuwing {
		font-size: var(--text-xs);
		margin: var(--space-3) 0 0;
	}

	.toggle {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: var(--space-3) 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.toggle input { width: 16px; height: 16px; accent-color: var(--accent); }

	/* Op een tablet en telefoon staat de tekening ónder de velden: naast elkaar
	   wordt de stepper daar zo smal dat de knoppen elkaar raken. */
	/* Raakdoelen gelden op tablet én telefoon; dit stond op 767px en liet de
	   tablet dus op 40px staan (gemeten: select 40, uitklaprij 32). */
	@media (max-width: 1199px) {
		.rest summary,
		.keuze select {
			min-height: 44px;
		}
		.toggle input { width: 22px; height: 22px; }
	}
	@media (max-width: 767px) {
		.werkgebied {
			grid-template-columns: minmax(0, 1fr);
		}
		.tekening {
			width: 100%;
			max-width: 260px;
		}
	}
</style>
