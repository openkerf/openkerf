<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import SettingFieldInput from '$components/SettingField.svelte';
	import { createStore } from '$lib/setup.svelte';

	const store = createStore();

	let machinePath = $derived($page.url.searchParams.get('machine') ?? '');
	let values = $state<Record<string, unknown>>({});
	let essentialOnly = $state(true);

	async function reload() {
		if (!machinePath) return;
		const sheets = await store.loadSettings(machinePath, essentialOnly);
		values = Object.fromEntries(
			sheets.flatMap((sheet) => sheet.fields.map((field) => [field.attr, field.value]))
		);
	}

	onMount(reload);

	async function save() {
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
			Werkgebied en verbinding. Alles wat de engine van dit apparaat kent staat achter
			"Alle instellingen".
		</p>
		<label class="toggle">
			<input
				type="checkbox"
				checked={!essentialOnly}
				onchange={(e) => {
					essentialOnly = !e.currentTarget.checked;
					reload();
				}}
			/>
			<span>Alle instellingen tonen</span>
		</label>
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

<style>
	.kunnen {
		margin: var(--space-3) 0;
		padding: var(--space-3);
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		display: grid;
		gap: var(--space-2);
	}
	.kunnen legend { font-size: var(--text-xs); color: var(--text-2); padding: 0 4px; }

	.toggle {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: var(--space-3) 0;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.toggle input { width: 15px; height: 15px; accent-color: var(--accent); }
</style>
