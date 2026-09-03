<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { t } from '$lib/i18n/index.svelte';
	import { createStore } from '$lib/setup.svelte';
	import type { CatalogMachine } from '$lib/machines.svelte';

	const store = createStore();

	let typeKey = $derived($page.url.searchParams.get('type') ?? '');
	let chosen = $state<CatalogMachine | null>(null);
	let label = $state('');
	let touched = $state(false);

	// If this type came from the search button in step 1, the connection details
	// found travel along as a parameter to the settings step. They are only applied
	// *there*, and only when you save there: until then nothing is connected.
	let connection = $derived($page.url.searchParams.get('connection') ?? '');
	let found = $derived($page.url.searchParams.get('found') ?? '');

	onMount(async () => {
		// Fetch the existing machines too: a name that already exists is not a name.
		await Promise.all([store.loadCatalog(), store.loadMachines()]);
		chosen =
			store.catalog
				.flatMap((family) => family.machines)
				.find((machine) => machine.key === typeKey) ?? null;
		// Only prefill as long as the user has typed nothing themselves.
		if (chosen && !touched) label = uniek(String(chosen.defaults.label ?? chosen.friendly_name));
	});

	/**
	 * A name that is not taken yet.
	 *
	 * The same rule as with sheets (`sheets.py`, `add`): two things with the same
	 * name cannot be told apart. On a machine that weighs more heavily than on a
	 * sheet — the top bar shows nothing but the name, and that bar is the only thing
	 * saying where your job is going. Measured before this rule: running the wizard
	 * twice gave two machines both called "Workshop 5030", without a word about
	 * it.
	 */
	function uniek(wens: string): string {
		const taken = new Set(store.machines.map((m) => m.label));
		if (!taken.has(wens)) return wens;
		let n = 2;
		while (taken.has(`${wens} (${n})`)) n += 1;
		return `${wens} (${n})`;
	}

	let botsing = $derived(
		label.trim() !== '' && store.machines.some((m) => m.label === label.trim())
	);

	async function create() {
		const result = await store.create(typeKey, label.trim());
		if (result) {
			const params = new URLSearchParams({ machine: result.path });
			if (connection) params.set('connection', connection);
			await goto(`/setup/settings?${params}`);
		}
	}
</script>

<svelte:head><title>{t('setup.head.name')}</title></svelte:head>

<section class="setup narrow">
	{#if store.error}<p class="error" role="alert">{store.error}</p>{/if}

	{#if !typeKey}
		<h1>{t('setup.noType')}</h1>
		<p class="muted">{t('setup.noType.body')}</p>
		<div class="actions">
			<a class="btn primary" href="/setup/type">{t('setup.toTypeChoice')}</a>
		</div>
	{:else}
		<h1>{t('setup.nameIt')}</h1>
		<p class="muted">
			{chosen ? t('setup.nameIt.bodyModel', { model: chosen.friendly_name }) : t('setup.nameIt.body')}
		</p>
		{#if found}
			<p class="found">{t('setup.found', { what: found })}</p>
		{/if}
		<label class="field">
			<span>{t('panel.name')}</span>
			<input
				type="text"
				bind:value={label}
				oninput={() => (touched = true)}
				placeholder={t('library.machine.placeholder')}
			/>
		</label>
		{#if botsing}
			<!-- Warn, do not block: maybe there really are two of the same in the
			     workshop. But then you have to know, because the top bar shows nothing
			     but this name. -->
			<p class="botsing" role="alert">
				{t('setup.nameClash', { name: label.trim() })}
				<button class="link" type="button" onclick={() => { label = uniek(label.trim()); touched = true; }}>
					{t('setup.nameClash.fix', { name: uniek(label.trim()) })}
				</button>
			</p>
		{/if}
		<div class="actions">
			<!-- Whoever got here via the search button chose no model in step 2; going
			     back to the model list would show a step they never saw. -->
			<a class="btn" href={found ? '/setup/kind' : '/setup/type'}>{t('common.back')}</a>
			<button class="btn primary" onclick={create} disabled={store.busy || !label.trim()} title={store.busy ? t('reason.busy') : t('reason.needsName')}>
				{store.busy ? t('common.busy') : t('setup.create')}
			</button>
		</div>
	{/if}
</section>

<style>
	.field {
		display: grid;
		gap: var(--space-1);
		margin: var(--space-4) 0;
		font-weight: 500;
	}
	.botsing {
		margin: calc(-1 * var(--space-2)) 0 0;
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-xs);
		border-left: 3px solid var(--warn, var(--accent));
		background: var(--surface-2);
		border-radius: var(--radius-field);
	}
	.botsing .link {
		display: block;
		margin-top: 4px;
		padding: 0;
		font: inherit;
		color: var(--accent);
		background: none;
		border: 0;
		text-decoration: underline;
		cursor: pointer;
	}
	.found {
		margin: var(--space-3) 0 0;
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-xs);
		border-left: 3px solid var(--ok);
		background: var(--surface-2);
		border-radius: var(--radius-field);
	}
	.field input {
		font: inherit;
		font-weight: 400;
		padding: 8px 8px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-2);
		color: var(--text-1);
	}
</style>
