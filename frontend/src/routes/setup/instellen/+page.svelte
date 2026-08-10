<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import SettingFieldInput from '$components/SettingField.svelte';
	import { createStore } from '$lib/setup.svelte';

	const store = createStore();

	let machinePath = $derived($page.url.searchParams.get('machine') ?? '');
	let values = $state<Record<string, unknown>>({});

	onMount(async () => {
		if (!machinePath) return;
		const sheets = await store.loadSettings(machinePath, true);
		values = Object.fromEntries(
			sheets.flatMap((sheet) => sheet.fields.map((field) => [field.attr, field.value]))
		);
	});

	async function save() {
		if (Object.keys(values).length) {
			if (!(await store.updateSettings(machinePath, values))) return;
		}
		await goto(`/setup/klaar?machine=${encodeURIComponent(machinePath)}`);
	}
</script>

<svelte:head><title>OpenKerf — instellingen</title></svelte:head>

<section class="setup narrow">
	{#if store.error}<p class="error" role="alert">{store.error}</p>{/if}

	{#if !machinePath}
		<h1>Geen machine gekozen</h1>
		<p class="muted">Begin bij het overzicht en kies of maak een machine.</p>
		<div class="actions"><a class="btn primary" href="/setup">Naar het overzicht</a></div>
	{:else}
		<h1>Basisinstellingen</h1>
		<p class="muted">
			Werkgebied en verbinding. De rest van de instellingen blijft beschikbaar in MeerK40t.
		</p>
		{#each store.settings as sheet (sheet.sheet)}
			{#each sheet.fields as field (field.attr)}
				<SettingFieldInput {field} bind:value={values[field.attr]} />
			{/each}
		{/each}
		<div class="actions">
			<a class="btn" href="/setup">Overslaan</a>
			<button class="btn primary" onclick={save} disabled={store.busy}>
				{store.busy ? 'Opslaan…' : 'Opslaan'}
			</button>
		</div>
	{/if}
</section>
