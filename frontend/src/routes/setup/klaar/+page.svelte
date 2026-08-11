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

	const store = createStore();

	let machinePath = $derived($page.url.searchParams.get('machine') ?? '');
	let machine = $derived(store.machines.find((m) => m.path === machinePath) ?? null);
	let geladen = $state(false);

	onMount(async () => {
		await store.loadMachines();
		geladen = true;
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
</style>
