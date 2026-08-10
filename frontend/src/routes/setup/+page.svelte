<script lang="ts">
	import { onMount } from 'svelte';
	import { createStore } from '$lib/setup.svelte';
	import type { Machine } from '$lib/machines.svelte';

	const store = createStore();

	onMount(() => store.loadMachines());

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
	{#if store.machines.length === 0}
		<p class="muted">Nog geen machine ingesteld.</p>
	{:else}
		<ul class="machines">
			{#each store.machines as machine (machine.path)}
				<li class:active={machine.active}>
					<div>
						<div class="name">{machine.label}</div>
						<div class="muted mono">{machine.path}</div>
					</div>
					{#if machine.active}
						<span class="badge">In gebruik</span>
					{:else}
						<button class="btn" onclick={() => useMachine(machine)}>Gebruiken</button>
						<button class="btn subtle" onclick={() => removeMachine(machine)}>Verwijderen</button>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}

	<div class="actions">
		<a class="btn primary" href="/setup/type">Machine toevoegen</a>
	</div>
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
		padding: 10px 12px;
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
	.badge {
		font-size: var(--text-xs);
		padding: 3px 9px;
		border-radius: var(--radius-dot);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		color: var(--accent);
	}
</style>
