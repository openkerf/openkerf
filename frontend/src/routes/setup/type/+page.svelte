<script lang="ts">
	import { onMount } from 'svelte';
	import { createStore } from '$lib/setup.svelte';

	const store = createStore();
	let search = $state('');

	onMount(() => store.loadCatalog());

	let families = $derived(
		store.catalog
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

	<h1>Wat voor machine is het?</h1>
	<p class="muted">
		Deze lijst komt uit MeerK40t zelf. Weet je het merk niet? Kies de familie die past bij je
		controller — de instellingen kun je hierna nog aanpassen.
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
		<p class="muted">
			{store.busy ? 'Catalogus laden…' : `Niets gevonden voor “${search}”.`}
		</p>
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
		padding: 8px 10px;
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
	}
	.type {
		display: grid;
		gap: 2px;
		padding: 10px 12px;
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
	}
	.name {
		font-weight: 500;
	}
</style>
