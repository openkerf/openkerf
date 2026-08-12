<script lang="ts">
	/**
	 * Stap 5.
	 *
	 * Deze pagina zei alleen "de machine is aangemaakt" en zette je in een leeg
	 * werkgebied. Precies daar viel het eerste "wat nu?" van de hele taak: je
	 * hebt een machine, en niets vertelt je hoe je van niets naar een eerste
	 * snede komt. Nu staat die weg er, in de volgorde waarin je hem loopt.
	 *
	 * Bovendien beweerde hij succes zonder te controleren of er iets was: wie
	 * hier binnenkwam zonder `machine` in de URL las "De machine is aangemaakt".
	 */
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { createStore } from '$lib/setup.svelte';
	import { SheetStore } from '$lib/sheets.svelte';

	const store = createStore();

	let machinePath = $derived($page.url.searchParams.get('machine') ?? '');
	let machine = $derived(store.machines.find((m) => m.path === machinePath) ?? null);
	let geladen = $state(false);

	/**
	 * Het vel volgt de machine niet vanzelf (gat E2).
	 *
	 * Een vel is een stuk materiaal, geen kopie van het bed — dus meeschalen
	 * zónder te vragen zou het restje van 200 × 300 dat je net hebt ingesteld
	 * stilletjes oprekken tot bedmaat. Maar het omgekeerde is wat er nu gebeurt:
	 * je stelt een bed van 610 × 406 in en begint je eerste ontwerp in een kader
	 * van 310 × 210 dat van de vórige machine kwam en nergens op slaat.
	 *
	 * Vandaar dat het hier gevraagd wordt, op de enige plek waar de bedmaat net
	 * veranderd is: één regel, twee knoppen, en het antwoord is definitief.
	 */
	const sheets = new SheetStore(() =>
		typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '')
	);
	let bed = $state<{ w: number; h: number } | null>(null);
	/** Beantwoord (aangepast of laten staan): dan is de vraag weg. */
	let velAntwoord = $state<'aangepast' | 'gelaten' | null>(null);

	let velVraag = $derived.by(() => {
		const vel = sheets.active;
		if (!bed || !vel || velAntwoord) return null;
		// Een tiende millimeter verschil is afronding, geen mismatch.
		const afwijkt =
			Math.abs(vel.width_mm - bed.w) > 0.5 || Math.abs(vel.height_mm - bed.h) > 0.5;
		return afwijkt ? { vel, bed } : null;
	});

	function maat(value: number) {
		return String(Math.round(value * 10) / 10).replace('.', ',');
	}

	async function velNaarBed() {
		const vraag = velVraag;
		if (!vraag) return;
		if (await sheets.update(vraag.vel.id, { width_mm: bed!.w, height_mm: bed!.h }))
			velAntwoord = 'aangepast';
	}

	onMount(async () => {
		await store.loadMachines();
		geladen = true;
		// De bedmaat in millimeters komt uit de status: de instellingen van de
		// engine geven "24.0in" terug, en dat is hier de verkeerde eenheid om
		// mee te rekenen.
		await sheets.load();
		try {
			const response = await fetch('/api/status');
			if (!response.ok) return;
			const state = await response.json();
			const pad = $page.url.searchParams.get('machine') ?? '';
			const dev =
				(state.devices ?? []).find((d: { path: string }) => d.path === pad) ??
				(state.devices ?? []).find((d: { active: boolean }) => d.active);
			if (dev?.bed?.width_mm > 0 && dev?.bed?.height_mm > 0)
				bed = { w: dev.bed.width_mm, h: dev.bed.height_mm };
		} catch {
			/* zonder bedmaat stellen we de vraag niet — beter niets dan een gok */
		}
	});

	const STAPPEN = [
		{
			kop: 'Teken of importeer iets',
			uitleg: 'Pak links een vorm en klik op het bed, of open een SVG met Importeren.'
		},
		{
			kop: 'Geef het een laag',
			uitleg: 'De laag bepaalt snelheid en vermogen. Materiaal niet zeker? Brand eerst een testraster.'
		},
		{
			kop: 'Kader tonen',
			uitleg: 'De kop loopt de omtrek af zonder te branden. Zo zie je of je werkstuk goed ligt.'
		},
		{ kop: 'Start job', uitleg: 'Deksel dicht, afzuiging aan, en blijf erbij kijken.' }
	];
</script>

<svelte:head><title>OpenKerf — klaar</title></svelte:head>

<section class="setup narrow">
	{#if geladen && !machine}
		<h1>Deze machine bestaat niet (meer)</h1>
		<p class="muted">
			{machinePath
				? `Er is geen machine met het pad “${machinePath}”.`
				: 'Er stond geen machine in het adres.'}
			Waarschijnlijk ben je hier via een oude bladwijzer beland.
		</p>
		<div class="actions"><a class="btn primary" href="/setup">Naar je machines</a></div>
	{:else}
		<h1>{machine ? `${machine.label} staat klaar.` : 'Klaar.'}</h1>
		<p class="muted">
			Verbinding met de laser wordt pas gelegd bij de eerste job. Doe die eerste keer met de
			deksel open en zonder werkstuk — dan zie je of de kop beweegt zoals je verwacht zonder
			dat er iets kan branden.
		</p>

		{#if velVraag}
			<div class="velvraag">
				<h2 class="kop">Gaat je vel mee naar dit bed?</h2>
				<p>
					<strong>{velVraag.vel.name}</strong> staat op
					<span class="mono">{maat(velVraag.vel.width_mm)} × {maat(velVraag.vel.height_mm)} mm</span>,
					het bed van {machine?.label ?? 'deze machine'} is
					<span class="mono">{maat(velVraag.bed.w)} × {maat(velVraag.bed.h)} mm</span>.
				</p>
				<p class="muted">
					Een vel is het stuk materiaal dat je erin legt, niet het bed zelf — dus als dit
					een restje van {maat(velVraag.vel.width_mm)} mm breed is, klopt het zo.
				</p>
				<div class="velknoppen">
					<button class="btn primary" disabled={sheets.busy} onclick={velNaarBed}>
						Vel op bedmaat zetten
					</button>
					<button class="btn subtle" onclick={() => (velAntwoord = 'gelaten')}>
						Laten staan
					</button>
				</div>
				{#if sheets.error}<p class="fout" role="alert">{sheets.error}</p>{/if}
			</div>
		{:else if velAntwoord === 'aangepast' && sheets.active}
			<p class="velgoed" role="status">
				{sheets.active.name} staat nu op
				<span class="mono"
					>{maat(sheets.active.width_mm)} × {maat(sheets.active.height_mm)} mm</span
				>.
			</p>
		{/if}

		<h2>Van hier naar je eerste snede</h2>
		<ol class="weg">
			{#each STAPPEN as stap, index (stap.kop)}
				<li>
					<span class="nummer mono">{index + 1}</span>
					<span class="tekst">
						<strong>{stap.kop}</strong>
						<span class="muted">{stap.uitleg}</span>
					</span>
				</li>
			{/each}
		</ol>

		<div class="actions">
			<a class="btn" href="/setup">Nog een machine</a>
			<a class="btn primary" href="/">Naar het werkgebied</a>
		</div>
	{/if}
</section>

<style>
	h2 {
		font-size: var(--text-sm);
		font-weight: 600;
		margin: var(--space-6) 0 var(--space-3);
	}
	.weg {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: var(--space-3);
	}
	.weg li {
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
	}
	.nummer {
		flex: none;
		width: 22px;
		height: 22px;
		display: grid;
		place-items: center;
		border-radius: var(--radius-dot);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		/* Gelijk aan de stapbolletjes op het welkomstscherm: accent op een
		   accenttint haalt geen AA. */
		color: var(--text-1);
		font-size: var(--text-xs);
	}
	.tekst {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.tekst .muted {
		font-size: var(--text-xs);
	}

	/* Een vraag, geen waarschuwing: er is niets stuk, er valt iets te kiezen.
	   Daarom het accent in de rand en niet amber. */
	.velvraag {
		margin-top: var(--space-6);
		padding: var(--space-4);
		border: 1px solid var(--line);
		border-left: 3px solid var(--accent);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	.velvraag .kop {
		margin: 0 0 var(--space-2);
	}
	.velvraag p {
		margin: 0 0 var(--space-2);
		font-size: var(--text-xs);
	}
	.velknoppen {
		display: flex;
		flex-wrap: wrap;
		/* Twee uitkomsten die elkaar uitsluiten: ver genoeg uit elkaar om er met
		   een duim niet naast te mikken. */
		gap: var(--space-6);
		margin-top: var(--space-3);
	}
	/* Met een handschoen aan is 37px te weinig; de knoppen in de setup zijn
	   verder muisknoppen, dus dit staat hier en niet in de layout. */
	@media (max-width: 1199px), (pointer: coarse) {
		.velknoppen :global(.btn) {
			min-height: 44px;
		}
	}
	.velgoed {
		margin-top: var(--space-6);
		font-size: var(--text-xs);
		color: var(--ok);
	}
	.fout {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xs);
		color: var(--danger);
	}
</style>
