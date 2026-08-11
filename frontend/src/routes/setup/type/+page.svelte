<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { kindOf, KINDS } from '$lib/machines.svelte';
	import { createStore } from '$lib/setup.svelte';

	const store = createStore();
	let search = $state('');

	onMount(() => store.loadCatalog());

	// De gekozen soort staat in de URL: deze stap moet een verversing en de
	// terugknop overleven.
	let soort = $derived($page.url.searchParams.get('soort'));
	let gekozenSoort = $derived(KINDS.find((k) => k.id === soort) ?? null);

	let families = $derived(
		store.catalog
			.filter(
				(family) =>
					!soort || kindOf(family.family, family.machines.map((m) => m.key)) === soort
			)
			.map((family) => ({
				...family,
				machines: family.machines.filter((machine) =>
					`${machine.friendly_name} ${family.family}`
						.toLowerCase()
						.includes(search.trim().toLowerCase())
				)
			}))
			.filter((family) => family.machines.length > 0)
	);
</script>

<svelte:head><title>OpenKerf — machinetype</title></svelte:head>

<section class="setup">
	{#if store.error}<p class="error" role="alert">{store.error}</p>{/if}

	<h1>{gekozenSoort ? `Welke ${gekozenSoort.label}?` : 'Welk model?'}</h1>
	<p class="muted">
		Deze lijst komt uit MeerK40t zelf.
		{#if gekozenSoort}
			Alleen de modellen die bij je keuze horen — <a href="/setup/type">toon alles</a>.
		{:else}
			Weet je het merk niet? Kies de familie die past bij je controller.
		{/if}
		De instellingen kun je hierna nog aanpassen.
	</p>
	<input class="search" type="search" bind:value={search} placeholder="Zoek op merk of type…" />

	{#each families as family (family.family)}
		<h2>{family.family}</h2>
		<ul class="types">
			{#each family.machines as machine (machine.key)}
				<li>
					<!-- De keuze gaat als queryparameter mee: de volgende stap is een
					     eigen pagina en moet een verversing overleven. -->
					<a class="type" href="/setup/naam?type={encodeURIComponent(machine.key)}">
						<span class="name">{machine.friendly_name}</span>
						{#if machine.extended_info}
							<span class="muted">{machine.extended_info}</span>
						{/if}
					</a>
				</li>
			{/each}
		</ul>
	{:else}
		<!-- Het lege geval had één tekst voor drie oorzaken, en die noemde altijd
		     de zoekterm — ook als je niets getypt had en het de soortfilter was
		     die alles wegliet. Dan las je "Niets gevonden voor “”" en was de
		     enige uitweg de terugknop. -->
		<p class="niets muted">
			{#if store.busy}
				Catalogus laden…
			{:else if search.trim()}
				Niets gevonden voor “{search.trim()}”{soort ? ' binnen deze soort' : ''}.
			{:else if soort}
				Deze soort levert geen modellen op. Waarschijnlijk klopt de soort in het adres niet.
			{:else}
				De catalogus is leeg. Draait de engine wel?
			{/if}
		</p>
		{#if !store.busy && (soort || search.trim())}
			<p><a class="btn" href="/setup/type">Toon alle modellen</a></p>
		{/if}
	{/each}

	<div class="actions">
		<a class="btn" href="/setup">Terug</a>
	</div>
</section>

<style>
	h2 {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: var(--space-6) 0 var(--space-2);
	}
	.search {
		font: inherit;
		width: 100%;
		padding: 8px 8px;
		margin-top: var(--space-4);
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.types {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: var(--space-2);
		/* Gelijke hoogte per rij: de teksten komen uit upstream en lopen van
		   twee tot acht regels, en dat leest als een raster met fouten erin. */
		align-items: stretch;
	}
	.type {
		display: grid;
		gap: 2px;
		height: 100%;
		align-content: start;
		padding: 8px 12px;
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
		text-decoration: none;
		color: inherit;
		transition: border-color var(--transition), background var(--transition);
	}
	.type:hover {
		border-color: var(--accent);
		background: var(--surface-2);
	}
	.type .muted {
		font-size: var(--text-xs);
		/* Drie regels is genoeg om te herkennen; de rest is upstream-proza. */
		display: -webkit-box;
		-webkit-line-clamp: 3;
		line-clamp: 3;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.name {
		font-weight: 500;
	}
	.niets {
		margin-top: var(--space-6);
	}
</style>
