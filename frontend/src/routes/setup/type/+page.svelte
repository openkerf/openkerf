<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { t } from '$lib/i18n/index.svelte';
	import { kindOfMachine, KINDS } from '$lib/machines.svelte';
	import { createStore } from '$lib/setup.svelte';
	import Notice from '$components/Notice.svelte';
	import EmptyState from '$components/EmptyState.svelte';

	const store = createStore();
	let search = $state('');

	onMount(() => store.loadCatalog());

	// The chosen kind is in the URL: this step has to survive a refresh and the
	// back button.
	let kind = $derived($page.url.searchParams.get('kind'));
	let pickedKind = $derived(KINDS.find((k) => k.id === kind) ?? null);

	let families = $derived(
		store.catalog
			// Filter per machine, not per family: one family can hold machines of
			// different kinds (K-Series houses both the Nanos and the only Ruida).
			.map((family) => ({
				...family,
				machines: family.machines.filter(
					(machine) =>
						(!kind || kindOfMachine(machine) === kind) &&
						`${machine.friendly_name} ${family.family}`
							.toLowerCase()
							.includes(search.trim().toLowerCase())
				)
			}))
			.filter((family) => family.machines.length > 0)
	);
</script>

<svelte:head><title>{t('setup.head.type')}</title></svelte:head>

<section class="setup">
	{#if store.error}<Notice tone="danger" live>{store.error}</Notice>{/if}

	<h1 class="title">
		{pickedKind ? t('setup.whichKind', { kind: pickedKind.label }) : t('setup.whichModel')}
	</h1>
	<p>
		{t('setup.catalogue.from')}
		{#if pickedKind}
			{t('setup.catalogue.filtered')}
			<a class="link" href="/setup/type">{t('setup.catalogue.showAllLink')}</a>
		{:else}
			{t('setup.catalogue.unsure')}
		{/if}
		{t('setup.catalogue.later')}
	</p>
	<input
		class="search"
		type="search"
		bind:value={search}
		placeholder={t('setup.searchTypes')}
		aria-label={t('setup.searchTypes')}
	/>

	{#each families as family (family.family)}
		<h2 class="label-section">{family.family}</h2>
		<ul class="types">
			{#each family.machines as machine (machine.key)}
				<li>
					<!-- The choice travels as a query parameter: the next step is a page of
					     its own and has to survive a refresh. -->
					<a class="card inset type" href="/setup/name?type={encodeURIComponent(machine.key)}">
						<span class="name">{machine.friendly_name}</span>
						{#if machine.extended_info}
							<span class="help clamp">{machine.extended_info}</span>
						{/if}
					</a>
				</li>
			{/each}
		</ul>
	{:else}
		<!-- The empty case used to have one text for three causes, and it always named
		     the search term — even when you had typed nothing and it was the kind
		     filter that left everything out. Then it read "Nothing found for “”" and
		     the only way out was the back button. -->
		{#if store.busy}
			<p class="help none">{t('setup.loadingCatalogue')}</p>
		{:else}
			<div class="none">
				<EmptyState
					title={search.trim()
						? t(kind ? 'setup.nothingFound.within' : 'setup.nothingFound', { query: search.trim() })
						: kind
							? t('setup.kindEmpty')
							: t('setup.catalogue.empty')}
				>
					{#snippet action()}
						{#if kind || search.trim()}
							<a class="btn" href="/setup/type">{t('setup.showAllModels')}</a>
						{/if}
					{/snippet}
				</EmptyState>
			</div>
		{/if}
	{/each}

	<div class="ask-actions">
		<a class="btn" href="/setup">{t('common.back')}</a>
	</div>
</section>

<style>
	h2 {
		margin: var(--space-6) 0 var(--space-2);
	}
	.search {
		width: 100%;
		margin-top: var(--space-4);
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.types {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(260px, 100%), 1fr));
		gap: var(--space-2);
		/* Equal height per row: the texts come from upstream and run from two to
		   eight lines, and that reads as a grid with mistakes in it. */
		align-items: stretch;
	}
	.type {
		display: grid;
		gap: var(--space-1);
		height: 100%;
		align-content: start;
		text-decoration: none;
		color: inherit;
		transition: border-color var(--transition), background var(--transition);
	}
	.type:hover {
		border-color: var(--accent-edge);
		background: var(--accent-tint);
	}
	/* Three lines is enough to recognise it; the rest is upstream prose. */
	.clamp {
		display: -webkit-box;
		-webkit-line-clamp: 3;
		line-clamp: 3;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.name {
		font-weight: 500;
	}
	.none {
		margin-top: var(--space-6);
	}
</style>
