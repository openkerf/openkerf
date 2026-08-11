<script lang="ts">
	/**
	 * Stap 1: wat voor machine heb je?
	 *
	 * De catalogus van MeerK40t telt veertig bordnamen. Wie net begint kent er
	 * geen, maar weet wél of er een glazen buis met waterkoeling in staat. Deze
	 * stap vertaalt dat naar een handvol modellen in de volgende.
	 */
	import { onMount } from 'svelte';
	import { KINDS, kindOf, type CatalogFamily } from '$lib/machines.svelte';
	import { createStore } from '$lib/setup.svelte';

	const store = createStore();
	onMount(() => store.loadCatalog());

	// Hoeveel modellen er achter elke soort zitten; een soort zonder modellen
	// hoort niet klikbaar te zijn.
	let aantallen = $derived(
		KINDS.map((kind) => ({
			...kind,
			count: store.catalog
				.filter(
					(f: CatalogFamily) =>
						kindOf(f.family, f.machines.map((m) => m.key)) === kind.id
				)
				.reduce((n: number, f: CatalogFamily) => n + f.machines.length, 0)
		}))
	);
</script>

<svelte:head><title>OpenKerf — wat voor machine</title></svelte:head>

<section class="setup">
	{#if store.error}<p class="error" role="alert">{store.error}</p>{/if}

	<h1>Wat voor machine is het?</h1>
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
	.soorten {
		list-style: none;
		margin: var(--space-4) 0 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
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
	.anders a { color: var(--accent); }
</style>
