<script lang="ts">
	import { onMount } from 'svelte';
	import { createStore } from '$lib/setup.svelte';
	import type { Machine } from '$lib/machines.svelte';

	const store = createStore();

	onMount(() => store.loadMachines());

	// De engine maakt bij het opstarten zelf een lhystudios-apparaat aan, zodat
	// de kernel altijd iets heeft om tegen te praten. Dat is geen machine van
	// de gebruiker, en hem in deze lijst zetten als "In gebruik" leest als een
	// apparaat dat je zelf hebt toegevoegd. We zetten hem apart met de reden
	// erbij, in plaats van hem te verbergen: hij is wél actief, en dat moet je
	// kunnen zien.
	let eigen = $derived(store.machines.filter((m) => m.configured !== false));
	let placeholder = $derived(store.machines.find((m) => m.configured === false) ?? null);

	async function useMachine(machine: Machine) {
		if (await store.activate(machine.path)) await store.loadMachines();
	}

	async function removeMachine(machine: Machine) {
		if (await store.remove(machine.path)) await store.loadMachines();
	}
</script>

<svelte:head><title>OpenKerf — machines</title></svelte:head>

<section class="setup">
	{#if store.error}<p class="error" role="alert">{store.error}</p>{/if}

	<h1>Jouw machines</h1>
	{#if eigen.length === 0}
		<p class="leeg">
			<strong>Nog geen machine ingesteld.</strong>
			<span class="muted">
				Voeg de laser toe die in je werkplaats staat. Dat bepaalt het bed op het canvas,
				welke bediening je krijgt en hoe OpenKerf hem aanspreekt.
			</span>
		</p>
	{:else}
		<ul class="machines">
			{#each eigen as machine (machine.path)}
				<li class:active={machine.active}>
					<div>
						<div class="name">{machine.label}</div>
						<div class="muted mono">{machine.path}</div>
					</div>
					{#if machine.active}
						<span class="badge">In gebruik</span>
					{:else}
						<button class="btn" onclick={() => useMachine(machine)}>Gebruiken</button>
					{/if}
					<!-- Instellingen waren alleen tijdens het aanmaken te bereiken. -->
					<a class="btn" href="/setup/instellen?machine={encodeURIComponent(machine.path)}">
						Instellingen
					</a>
					{#if !machine.active}
						<button class="btn subtle" onclick={() => removeMachine(machine)}>Verwijderen</button>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}

	<div class="actions">
		<a class="btn primary" href="/setup/soort">Machine toevoegen</a>
	</div>

	{#if placeholder}
		<aside class="placeholder">
			<h2>Standaardapparaat van de engine</h2>
			<p class="muted">
				MeerK40t maakt bij het opstarten zelf een apparaat aan
				(<span class="mono">{placeholder.label}</span>) zodat er altijd iets actief is.
				Niemand heeft het gekozen, en de bedmaten en verbinding zijn gokwerk — brand er niets
				op zonder ze te controleren.
			</p>
			<p class="muted">
				Heb je toevallig precies zo'n machine? Geef hem dan een naam en zijn echte bedmaat;
				vanaf dan telt hij als jouw machine.
			</p>
			<a class="btn" href="/setup/instellen?machine={encodeURIComponent(placeholder.path)}">
				Nakijken en overnemen
			</a>
		</aside>
	{/if}
</section>

<style>
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.machines li {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 8px 12px;
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		margin-bottom: var(--space-2);
	}
	.machines li.active {
		border-color: var(--accent);
	}
	.machines li > div:first-child {
		flex: 1;
		min-width: 0;
	}
	.machines .mono {
		font-size: var(--text-xs);
	}
	.name {
		font-weight: 500;
	}
	/* Accent op een tint van 14% accent haalt geen AA (gemeten: 4,10 in licht,
	   4,46 in donker). De tint blijft de accentkleur dragen, de tekst niet —
	   dezelfde uitweg als in ToolRail, en zonder de merkkleur te verschuiven. */
	.badge {
		font-size: var(--text-xs);
		padding: 4px 8px;
		border-radius: var(--radius-dot);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		color: var(--text-1);
	}
	.leeg {
		display: grid;
		gap: var(--space-2);
		margin: 0;
		padding: var(--space-4);
		border: 1px dashed var(--line);
		border-radius: var(--radius-card);
	}
	.placeholder {
		margin-top: var(--space-8);
		padding: var(--space-4);
		border-radius: var(--radius-card);
		/* Een waarschuwingsvlak, geen fout: dit apparaat werkt, het is alleen
		   niet het jouwe. Zie DESIGN-SYSTEM, "zekerheid is een zin". */
		border-left: 3px solid var(--warn);
		background: var(--surface-2);
	}
	.placeholder h2 {
		font-size: var(--text-sm);
		font-weight: 600;
		margin: 0 0 var(--space-2);
	}
	.placeholder p {
		margin: 0 0 var(--space-2);
		font-size: var(--text-xs);
	}
</style>
