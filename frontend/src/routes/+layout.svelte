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

	/**
	 * De wizard verandert het antwoord, dus na de wizard opnieuw vragen.
	 *
	 * Dit was de bug die Jelle vond: wie op het werkgebied begint krijgt hier
	 * `stand = 'nodig'`, gaat de wizard in, maakt zijn machine aan en klikt op
	 * "Naar het werkgebied" — en belandt weer op de welkomstpoort, want die
	 * `stand` van vóór de wizard stond er nog. Alleen een handmatige verversing
	 * hielp, en dat is precies de handeling die deze poort zou moeten besparen.
	 *
	 * Geen `$state`: deze vlag mag de effect niet zelf opnieuw aan de gang
	 * krijgen. Hij verandert alleen mee met de route, en dáár hangt de effect al
	 * aan via `inWizard`.
	 */
	let opnieuwVragen = false;

	$effect(() => {
		if (inWizard) {
			// Wat hier ook gebeurt — aanmaken, verwijderen, hernoemen — bij
			// terugkomst is het antwoord van daarnet niets meer waard.
			opnieuwVragen = true;
			return;
		}
		if (stand !== 'onbekend' && !opnieuwVragen) return;
		opnieuwVragen = false;
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

<!-- De fonts komen sinds v3.3 uit de build zelf (@font-face in tokens.css, zes
     woff2 van samen 128 KB). De link naar fonts.googleapis.com die hier stond
     voegde daar niets aan toe en was het énige externe verzoek van de app;
     zonder netwerk leverde hij ERR_FAILED in de console op. -->

{#if inWizard || rondkijken || stand === 'klaar'}
	{@render children()}
{:else if stand === 'nodig'}
	<Welkom onrondkijken={() => (rondkijken = true)} />
{:else}
	<!-- Zolang `stand` onbekend is tekenen we het werkgebied niet: dat zou
	     opflitsen met de melding dat de laser klaarstaat. Maar een volstrekt
	     blanco pagina is niet te onderscheiden van een stuk scherm, en op een
	     langzame server duurde "één tel" merkbaar langer dan een tel. Deze regel
	     verschijnt daarom pas ná 400 ms: is de server snel, dan zie je hem
	     nooit; is hij traag, dan staat er waar we op wachten. -->
	<p class="wachten" role="status">Even kijken welke machine er is…</p>
{/if}

<style>
	:global(body) {
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}
	.wachten {
		flex: 1;
		display: grid;
		place-items: center;
		margin: 0;
		color: var(--text-2);
		background: var(--surface-0);
		/* Vertraagd in beeld: een snelle server hoort hier geen tekst te laten
		   opflitsen, een langzame moet zich verantwoorden. */
		opacity: 0;
		/* Duur en timing los uitschrijven: --transition is "150ms ease-out", dus
		   in een animation-shorthand levert het een tweede timingfunctie op en
		   valt de hele regel als ongeldig weg. Gemeten: opacity bleef 0. */
		animation: opdoemen 150ms ease-out 400ms forwards;
	}
	@keyframes opdoemen {
		to {
			opacity: 1;
		}
	}
	/* Wie beweging uitzet, krijgt de regel meteen: hij is een melding, geen
	   versiering, en mag niet helemaal wegvallen. */
	@media (prefers-reduced-motion: reduce) {
		.wachten {
			opacity: 1;
			animation: none;
		}
	}
</style>
