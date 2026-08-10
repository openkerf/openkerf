<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { createStore } from '$lib/setup.svelte';

	const store = createStore();

	let machinePath = $derived($page.url.searchParams.get('machine') ?? '');
	let machine = $derived(store.machines.find((m) => m.path === machinePath) ?? null);

	onMount(() => store.loadMachines());
</script>

<svelte:head><title>OpenKerf — klaar</title></svelte:head>

<section class="setup narrow">
	<h1>Klaar</h1>
	<p>
		<strong>{machine?.label ?? 'De machine'}</strong> is aangemaakt en staat klaar voor gebruik.
	</p>
	<p class="muted">
		Verbinding maken met de laser gebeurt bij de eerste job. Test eerst met de deksel open en zonder
		werkstuk.
	</p>
	<div class="actions">
		<a class="btn" href="/setup">Nog een machine</a>
		<a class="btn primary" href="/">Naar het werkgebied</a>
	</div>
</section>
