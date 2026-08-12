<script lang="ts">
	/**
	 * Het alarm: wat de engine over de verbinding meldt, luid in beeld.
	 *
	 * Vast bovenaan, boven alles, niet weg te scrollen — dat is het hele punt.
	 * Op de telefoon staat hij tegen de bovenrand; op de desktop onder de
	 * bovenbalk, zodat de knoppen die de machine stoppen bereikbaar blijven. Een
	 * alarm dat de noodrem afdekt is geen alarm maar een obstakel.
	 *
	 * Wat er níet staat: een oordeel dat wij niet kunnen onderbouwen. De tekst
	 * citeert de engine en zegt erbij wat je zélf moet controleren — wij zien de
	 * machine niet (besluit B3).
	 */
	import type { Bewaker } from '$lib/meldingen.svelte';

	let { bewaker, groot = false }: { bewaker: Bewaker; groot?: boolean } = $props();
</script>

{#if bewaker.toon && bewaker.alarm}
	<div class="alarm" class:groot role="alert" aria-live="assertive">
		<svg class="teken" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"
			stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
			<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
			<path d="M12 9v4" />
			<path d="M12 17h.01" />
		</svg>
		<div class="woord">
			<strong>{bewaker.alarm.titel}</strong>
			<p>{bewaker.alarm.tekst}</p>
			<p>{bewaker.alarm.raad}</p>
			{#if bewaker.alarm.bron}
				<!-- Woordelijk wat de engine zei. Wij vertalen, maar verbergen niet
				     waar het vandaan komt — dat is het verschil tussen een melding
				     en een bewering. -->
				<p class="bron mono">{bewaker.alarm.bron.trim()}</p>
			{/if}
		</div>
		<button class="gezien" onclick={() => bewaker.sluit()}>Gezien</button>
	</div>
{/if}

<style>
	.alarm {
		position: fixed;
		/*
		 * Eén kolom met de verbindingskaart, en die staat erboven.
		 *
		 * Dit stond gecentreerd op 50% terwijl `Verbinding.svelte` tegen de rail
		 * aan hangt, op dezelfde hoogte. Op 1440 begon dit alarm daardoor op
		 * x≈360, midden over die kaart, en kapte het twee zinnen af — niet
		 * volledig bedekt maar half, en dat is erger: een afgebroken zin ziet
		 * eruit als een hele zin, dus je weet niet dát je de helft mist.
		 *
		 * Nu dezelfde linkerrand en dezelfde breedte, met `--melding-kolom` als
		 * verschuiving: die zet de verbindingskaart op `:root` met zijn eigen
		 * gemeten hoogte, en is er niet zodra die kaart weg is. Waarom die kaart
		 * bóven dit alarm hoort: zonder onze server is elke melding over de
		 * machine per definitie oud nieuws — het is dezelfde engine die niet meer
		 * antwoordt.
		 *
		 * Het oorspronkelijke bezwaar tegen links uitlijnen was de foutmelding van
		 * de bediening rechtsboven (Melding.svelte, z-index 60). Die staat er nog,
		 * en links uitlijnen helpt daar juist: zo raken die twee elkaar niet.
		 */
		top: calc(var(--topbar-height) + var(--space-3) + var(--melding-kolom, 0px));
		left: calc(var(--rail-width) + var(--space-3));
		width: min(620px, calc(100vw - var(--rail-width) - 2 * var(--space-3)));
		border-radius: var(--radius-card);
		/* Boven alles: vensters zitten op 60, de scrim op 50. Een alarm hoort
		   nergens achter. */
		z-index: 200;
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		background: var(--danger-solid);
		color: var(--on-color);
		box-shadow: var(--lift-2);
	}
	.teken {
		flex: none;
		width: 22px;
		height: 22px;
		margin-top: 1px;
	}
	.woord {
		flex: 1;
		min-width: 0;
	}
	strong {
		display: block;
		font-size: var(--text-md);
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	p {
		margin: var(--space-1) 0 0;
		font-size: var(--text-sm);
		/* Wit op rood mag niet vervagen: dit is de tekst die het feit draagt. */
		color: var(--on-color);
	}
	/*
	 * Geen doorzichtigheid als rangorde op dit vlak.
	 *
	 * Gemeten op 390 px: wit op `--danger-solid` haalt 5,60 in licht en 4,67 in
	 * donker, maar met opacity 0,9 zakt de raadgeving naar 4,05 in donker en met
	 * 0,75 zakt de bronregel naar 3,23 — allebei onder AA, en uitgerekend op de
	 * regel die zegt wat je moet doen. De rangorde komt hier van maat en font
	 * (24 px vet / 15 px / 13 px mono), niet van vervagen.
	 */
	.bron {
		font-size: var(--text-xs);
	}
	.gezien {
		flex: none;
		min-height: 36px;
		padding: 0 var(--space-3);
		border: 1px solid var(--on-color);
		border-radius: var(--radius-field);
		color: var(--on-color);
		font-weight: 600;
	}
	.gezien:hover {
		background: rgb(255 255 255 / 0.15);
	}

	/* Tablet: op 1024 begint het rechterpaneel op x≈700, dus 620 px vanaf de rail
	   zou de tabs "Bewerken" en "Lagen" weer afdekken — precies wat je op dat
	   moment wilde bedienen. 560 houdt de kaart volledig boven het canvas.
	   Dezelfde 560 staat in `Verbinding.svelte`; die twee horen gelijk te blijven,
	   want samen zijn ze één kolom. Zonder wrapper-element (dat zou `+page.svelte`
	   raken, waar deze twee op verschillende plekken gerenderd worden) is dit de
	   prijs: één maat op twee plekken, met deze verwijzing als verband. */
	@media (min-width: 768px) and (max-width: 1199px) {
		.alarm:not(.groot) {
			width: min(560px, calc(100vw - var(--rail-width) - 2 * var(--space-3)));
		}
	}

	/* Telefoon: geen overlay maar een blok bovenin dat de rest omlaag duwt. Het
	   staat buiten het scrolgebied, dus wegscrollen kan niet — en tegelijk snijdt
	   het niets af. Groter, en de knop onder de tekst in plaats van ernaast: met
	   een duim mik je niet op een knop van 36 px in een hoek. */
	.alarm.groot {
		position: static;
		/* De zwevende variant hangt aan de rail en heeft geen transform meer, maar
		   deze regels blijven staan als slot op de deur: `transform` en `left`
		   werken óók op een statisch element, en toen de zwevende variant nog
		   `translateX(-50%)` droeg schoof dit blok daarmee een halve schermbreedte
		   het beeld uit. */
		transform: none;
		left: auto;
		right: auto;
		top: auto;
		flex: none;
		width: 100%;
		border-radius: 0;
		flex-wrap: wrap;
		padding: max(var(--space-3), env(safe-area-inset-top)) var(--space-3) var(--space-3);
	}
	.alarm.groot .teken {
		width: 28px;
		height: 28px;
	}
	.alarm.groot strong {
		font-size: var(--text-lg);
	}
	.alarm.groot .gezien {
		width: 100%;
		min-height: 48px;
		margin-top: var(--space-2);
	}
</style>
