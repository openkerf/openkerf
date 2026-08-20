<script lang="ts">
	/**
	 * De actiebalk boven het canvas.
	 *
	 * Waarom hij bestaat. Uitlijnen, groeperen en spiegelen stonden in het
	 * rechterpaneel, op het tabblad Bewerken. Dat betekende drie dingen die alle
	 * drie tijd kosten: je moest een selectie hebben *en* op het goede tabblad
	 * staan (stond je op Job, dan waren ze onvindbaar), de knoppen zaten
	 * halverwege een kolom die scrolde, en ze aten paneelhoogte op die aan
	 * eigenschappen hoort. Het zijn werkwoorden, geen eigenschappen — zie de
	 * plaatsingsregel in DESIGN-SYSTEM.md.
	 *
	 * Waarom hierboven en niet in de bovenbalk: de bovenbalk gaat over het
	 * document en de machine (openen, opslaan, starten, stoppen). Deze balk gaat
	 * over wat er op het bed geselecteerd is, en staat daarom tegen het bed aan.
	 * Dat is ook waar een LightBurn-gebruiker hem zoekt.
	 *
	 * Waarom pictogrammen zonder woorden, terwijl de rail hetzelfde doet en dat
	 * daar een klacht is: hier zijn ze niet willekeurig maar in één grammatica
	 * getekend (dikke lijn = as, open rechthoek = vorm die schuift), en per groep
	 * gescheiden zodat de rij zelf vertelt wat je leest — eerst geschiedenis, dan
	 * uitlijnen horizontaal, dan verticaal, dan schikken. Elke knop draagt zijn
	 * naam in `aria-label` en zijn naam plus sneltoets in de tooltip.
	 */
	import ArrangeIcon from './ArrangeIcon.svelte';
	import type { Actie } from '$lib/acties';

	let {
		geschiedenis,
		uitlijnen,
		schikken,
		aantal,
		onMeer
	}: {
		geschiedenis: Actie[];
		/** Acht: vier horizontaal, vier verticaal. */
		uitlijnen: Actie[];
		/** Groeperen, opheffen, spiegelen h, spiegelen v. */
		schikken: Actie[];
		/** Aantal geselecteerde vormen — bepaalt de tekst rechts. */
		aantal: number;
		/** Opent het volledige menu, voor alles wat hier niet op past. */
		onMeer: (event: MouseEvent) => void;
	} = $props();

	function tip(actie: Actie) {
		if (actie.uit) return `${actie.label} — ${actie.uit}`;
		const staart = [actie.uitleg, actie.toets].filter(Boolean).join(' · ');
		return staart ? `${actie.label} — ${staart}` : actie.label;
	}
</script>

<div class="actiebalk" role="toolbar" aria-label="Bewerken">
	<div class="groep" role="group" aria-label="Geschiedenis">
		{#each geschiedenis as actie (actie.id)}
			<button
				class="knop"
				disabled={Boolean(actie.uit)}
				title={tip(actie)}
				aria-label={actie.label}
				onclick={actie.doen}
			>
				<ArrangeIcon name={actie.icoon ?? 'undo'} size={18} />
			</button>
		{/each}
	</div>

	<span class="scheiding" aria-hidden="true"></span>

	<!-- Twee groepen van vier: de eerste rij van het oude raster ging over de
	     horizontale as, de tweede over de verticale. Op één regel is die
	     tweedeling weg, dus staat er een scheiding tussen — anders zijn het acht
	     pictogrammen op een rij en moet je ze allemaal aflezen. -->
	<div class="groep" role="group" aria-label="Uitlijnen, horizontaal">
		{#each uitlijnen.slice(0, 4) as actie (actie.id)}
			<button
				class="knop"
				disabled={Boolean(actie.uit)}
				title={tip(actie)}
				aria-label={actie.label}
				onclick={actie.doen}
			>
				<ArrangeIcon name={actie.icoon ?? ''} size={19} />
			</button>
		{/each}
	</div>
	<div class="groep" role="group" aria-label="Uitlijnen, verticaal">
		{#each uitlijnen.slice(4) as actie (actie.id)}
			<button
				class="knop"
				disabled={Boolean(actie.uit)}
				title={tip(actie)}
				aria-label={actie.label}
				onclick={actie.doen}
			>
				<ArrangeIcon name={actie.icoon ?? ''} size={19} />
			</button>
		{/each}
	</div>

	<span class="scheiding" aria-hidden="true"></span>

	<div class="groep" role="group" aria-label="Schikken">
		{#each schikken as actie (actie.id)}
			<button
				class="knop"
				disabled={Boolean(actie.uit)}
				title={tip(actie)}
				aria-label={actie.label}
				onclick={actie.doen}
			>
				<ArrangeIcon name={actie.icoon ?? ''} size={19} />
			</button>
		{/each}
	</div>

	<span class="scheiding" aria-hidden="true"></span>

	<!-- De weg naar de rest. Een balk kan niet alles dragen, maar hij moet wel
	     zeggen dat er meer is — anders is het rechterklikmenu een geheim. -->
	<button class="meer" title="Alle bewerkingen — of rechterklik op een vorm" onclick={onMeer}>
		Meer
		<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
	</button>

	<span class="rek"></span>

	<!-- Wat er geselecteerd is, in woorden. Het paneel zegt het ook, maar dat
	     kan op een ander tabblad staan; deze balk hoort te zeggen waar hij op
	     werkt. Zonder deze regel is een rij grijze knoppen onverklaard. -->
	<p class="stand" aria-live="polite">
		{#if aantal === 0}
			Kies een vorm op het bed
		{:else if aantal === 1}
			1 vorm gekozen
		{:else}
			{aantal} vormen gekozen
		{/if}
	</p>
</div>

<style>
	.actiebalk {
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 3px var(--space-3);
		min-height: 38px;
		background: var(--surface-1);
		border-bottom: 1px solid var(--line);
	}
	.groep {
		display: flex;
		align-items: center;
		gap: 1px;
	}
	.knop {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		border-radius: var(--radius-field);
		color: var(--text-1);
		background: none;
		border: none;
	}
	.knop:hover:not(:disabled) {
		background: var(--surface-2);
	}
	.knop:disabled {
		color: var(--text-2);
		opacity: 0.38;
		cursor: not-allowed;
	}
	.scheiding {
		width: 1px;
		height: 20px;
		background: var(--line);
		margin: 0 2px;
	}
	.meer {
		display: flex;
		align-items: center;
		gap: 3px;
		padding: 5px 8px;
		border-radius: var(--radius-field);
		font-size: var(--text-xs);
		color: var(--text-2);
		background: none;
		border: none;
	}
	.meer:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.rek {
		flex: 1;
	}
	.stand {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
		white-space: nowrap;
	}
	/* Onder 1200px is dit niet de app waar deze ronde over gaat; de balk blijft
	   werken maar krimpt tot wat er past. Polijsten hoort bij de tabletronde. */
	@media (max-width: 1199px) {
		.actiebalk {
			overflow-x: auto;
		}
		.stand {
			display: none;
		}
	}
</style>
