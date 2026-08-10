<script lang="ts">
	import { onMount } from 'svelte';
	import Logo from '$components/Logo.svelte';
	import SettingFieldInput from '$components/SettingField.svelte';
	import { MachineStore, type CatalogMachine, type Machine } from '$lib/machines.svelte';

	const TOKEN_KEY = 'openkerf.token';
	const store = new MachineStore(() =>
		typeof localStorage === 'undefined' ? '' : (localStorage.getItem(TOKEN_KEY) ?? '')
	);

	type Step = 'machines' | 'type' | 'name' | 'settings' | 'done';

	let step = $state<Step>('machines');
	let search = $state('');
	let chosen = $state<CatalogMachine | null>(null);
	let label = $state('');
	let created = $state<Machine | null>(null);
	let values = $state<Record<string, unknown>>({});

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

	onMount(async () => {
		await store.loadMachines();
		await store.loadCatalog();
	});

	function pick(machine: CatalogMachine) {
		chosen = machine;
		label = String(machine.defaults.label ?? machine.friendly_name);
		step = 'name';
	}

	async function createMachine() {
		if (!chosen) return;
		const result = await store.create(chosen.key, label.trim());
		if (!result) return;
		created = result;
		const sheets = await store.loadSettings(result.path, true);
		values = Object.fromEntries(
			sheets.flatMap((sheet) => sheet.fields.map((field) => [field.attr, field.value]))
		);
		step = 'settings';
	}

	async function saveSettings() {
		if (!created) return;
		if (Object.keys(values).length && !(await store.updateSettings(created.path, values))) return;
		await store.loadMachines();
		step = 'done';
	}

	async function useMachine(machine: Machine) {
		if (await store.activate(machine.path)) await store.loadMachines();
	}

	async function removeMachine(machine: Machine) {
		if (await store.remove(machine.path)) await store.loadMachines();
	}
</script>

<svelte:head><title>OpenKerf — machine instellen</title></svelte:head>

<header class="topbar">
	<div class="brand"><Logo />OpenKerf</div>
	<span class="crumb">Machine instellen</span>
	<div class="spacer"></div>
	<a class="btn" href="/">Terug naar werkgebied</a>
</header>

<main>
	<ol class="steps" aria-label="Voortgang">
		{#each [['machines', 'Machines'], ['type', 'Type'], ['name', 'Naam'], ['settings', 'Instellen'], ['done', 'Klaar']] as [id, title] (id)}
			<li class:current={step === id}>{title}</li>
		{/each}
	</ol>

	{#if store.error}
		<p class="error" role="alert">{store.error}</p>
	{/if}

	{#if step === 'machines'}
		<section>
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
			<button class="btn primary" onclick={() => (step = 'type')}>Machine toevoegen</button>
		</section>
	{:else if step === 'type'}
		<section>
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
							<button class="type" onclick={() => pick(machine)}>
								<span class="name">{machine.friendly_name}</span>
								{#if machine.extended_info}
									<span class="muted">{machine.extended_info}</span>
								{/if}
							</button>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="muted">Niets gevonden voor “{search}”.</p>
			{/each}

			<button class="btn" onclick={() => (step = 'machines')}>Terug</button>
		</section>
	{:else if step === 'name'}
		<section class="narrow">
			<h1>Geef de machine een naam</h1>
			<p class="muted">Zo herken je hem in de bovenbalk: “{chosen?.friendly_name}”.</p>
			<label class="field">
				<span>Naam</span>
				<input type="text" bind:value={label} placeholder="bijv. 5030 CO2" />
			</label>
			<div class="actions">
				<button class="btn" onclick={() => (step = 'type')}>Terug</button>
				<button class="btn primary" onclick={createMachine} disabled={store.busy || !label.trim()}>
					{store.busy ? 'Bezig…' : 'Aanmaken'}
				</button>
			</div>
		</section>
	{:else if step === 'settings'}
		<section class="narrow">
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
				<button class="btn" onclick={() => (step = 'done')}>Overslaan</button>
				<button class="btn primary" onclick={saveSettings} disabled={store.busy}>
					{store.busy ? 'Opslaan…' : 'Opslaan'}
				</button>
			</div>
		</section>
	{:else}
		<section class="narrow">
			<h1>Klaar</h1>
			<p>
				<strong>{created?.label ?? 'De machine'}</strong> is aangemaakt en staat klaar voor gebruik.
			</p>
			<p class="muted">
				Verbinding maken met de laser gebeurt bij de eerste job. Test eerst met de deksel open en
				zonder werkstuk.
			</p>
			<div class="actions">
				<button class="btn" onclick={() => { created = null; chosen = null; step = 'machines'; }}>
					Nog een machine
				</button>
				<a class="btn primary" href="/">Naar het werkgebied</a>
			</div>
		</section>
	{/if}
</main>

<style>
	.topbar {
		height: var(--topbar-height);
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: 0 var(--space-3);
		background: var(--surface-1);
		border-bottom: 1px solid var(--line);
	}
	.brand {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-weight: 600;
		font-size: var(--text-md);
	}
	.crumb {
		color: var(--text-2);
	}
	.spacer {
		flex: 1;
	}
	main {
		flex: 1;
		overflow-y: auto;
		padding: var(--space-6);
		max-width: 900px;
		width: 100%;
		margin: 0 auto;
	}
	.steps {
		display: flex;
		gap: var(--space-2);
		list-style: none;
		margin: 0 0 var(--space-6);
		padding: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
		flex-wrap: wrap;
	}
	.steps li {
		padding: 4px 10px;
		border-radius: var(--radius-dot);
		background: var(--surface-2);
	}
	.steps li.current {
		background: var(--accent);
		color: var(--accent-ink);
	}
	h1 {
		font-size: var(--text-lg);
		font-weight: 600;
		letter-spacing: -0.01em;
		margin: 0 0 var(--space-2);
	}
	h2 {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-2);
		margin: var(--space-6) 0 var(--space-2);
	}
	.narrow {
		max-width: 460px;
	}
	.muted {
		color: var(--text-2);
	}
	.search {
		font: inherit;
		width: 100%;
		padding: 8px 10px;
		margin: var(--space-4) 0 0;
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
		width: 100%;
		text-align: left;
		padding: 10px 12px;
		border: 1px solid var(--line);
		border-radius: var(--radius-card);
		background: var(--surface-1);
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
	.badge {
		font-size: var(--text-xs);
		padding: 3px 9px;
		border-radius: var(--radius-dot);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		color: var(--accent);
	}
	.field {
		display: grid;
		gap: var(--space-1);
		margin: var(--space-4) 0;
		font-weight: 500;
	}
	.field input {
		font: inherit;
		font-weight: 400;
		padding: 8px 10px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
	.actions {
		display: flex;
		gap: var(--space-2);
		margin-top: var(--space-6);
	}
	.btn {
		display: inline-flex;
		align-items: center;
		padding: 8px 14px;
		border-radius: var(--radius-field);
		border: 1px solid var(--line);
		background: var(--surface-1);
		font-weight: 500;
		text-decoration: none;
		color: inherit;
		transition: background var(--transition);
	}
	.btn:hover:not(:disabled) {
		background: var(--surface-2);
	}
	.btn:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.btn.primary {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-ink);
	}
	.btn.subtle {
		color: var(--text-2);
	}
	.error {
		padding: var(--space-3);
		border-radius: var(--radius-field);
		background: color-mix(in srgb, var(--danger) 14%, transparent);
		margin: 0 0 var(--space-4);
	}
</style>
