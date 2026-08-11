<script lang="ts">
	import '$lib/tokens.css';
	import { page } from '$app/stores';
	import Welkom from '$components/Welkom.svelte';

	let { children } = $props();

	/**
	 * De koude start heeft een eigen scherm.
	 *
	 * MeerK40t boot met een verzonnen standaardapparaat, zodat de kernel altijd
	 * iets heeft om tegen te praten. Zonder poort hieronder opende OpenKerf op
	 * een werkgebied dat "lihuiyu-device — Gereed — Verbonden met de laser"
	 * meldde tegen iemand die nog nooit een machine had ingesteld, en er stond
	 * nergens een weg naar /setup. Wie de wizard niet in de adresbalk typt,
	 * vindt hem niet. Daarom: geen ingestelde machine, dan eerst dit scherm.
	 *
	 * De poort staat in de wortel-layout en niet op de werkgebiedpagina, omdat
	 * hij over álle routes gaat behalve de wizard zelf.
	 */
	type Machine = { path: string; label: string; configured?: boolean };

	let stand = $state<'onbekend' | 'nodig' | 'klaar'>('onbekend');
	// Rondkijken is een keuze voor deze sessie, niet voor altijd: een volgende
	// keer opstarten hoort weer bij de vraag te beginnen.
	let rondkijken = $state(false);

	let inWizard = $derived($page.url.pathname.startsWith('/setup'));

	$effect(() => {
		if (inWizard || stand !== 'onbekend') return;
		(async () => {
			try {
				const response = await fetch('/api/machines');
				if (!response.ok) return (stand = 'klaar');
				const machines: Machine[] = await response.json();
				// Een oudere server kent `configured` niet. Dan liever doorlaten
				// dan iedereen op een welkomstscherm vastzetten.
				const kent = machines.some((m) => 'configured' in m);
				stand = kent && !machines.some((m) => m.configured) ? 'nodig' : 'klaar';
			} catch {
				stand = 'klaar';
			}
		})();
	});
</script>

<svelte:head>
	<link rel="preconnect" href="https://fonts.googleapis.com" />
	<link
		href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap"
		rel="stylesheet"
	/>
</svelte:head>

{#if inWizard || rondkijken || stand === 'klaar'}
	{@render children()}
{:else if stand === 'nodig'}
	<Welkom onrondkijken={() => (rondkijken = true)} />
{/if}
<!-- Zolang `stand` onbekend is tekenen we niets: één tel leegte is beter dan
     een werkgebied dat opflitst en meldt dat de laser klaarstaat. -->


<style>
	:global(body) {
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}
</style>
