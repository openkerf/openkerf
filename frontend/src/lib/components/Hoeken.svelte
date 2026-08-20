<script lang="ts">
	/**
	 * Hoeken afronden of afschuinen.
	 *
	 * Stond als dichtgeklapte vouw in het rechterpaneel. Het is een werkwoord met
	 * twee instellingen, en daarmee valt het tussen de twee wal: te veel voor een
	 * menuregel, te weinig voor een paneelsectie die je altijd voorbij scrollt.
	 * Volgens de plaatsingsregel (DESIGN-SYSTEM v4) is dit een handeling met
	 * parameters, en die hoort in een klein venster dat het menu opent — één plek,
	 * met het voorbeeld erbij, en weg zodra je klaar bent.
	 *
	 * De tekening is niet decoratie: "5 mm" zegt niets over hoe rond die hoek
	 * wordt. Zie DESIGN-SYSTEM, "Een formulier dat vorm maakt, toont die vorm".
	 */
	import Dialog from './Dialog.svelte';
	import NumberField from './NumberField.svelte';

	let {
		open = $bindable(false),
		aantal = 0,
		bezig = false,
		melding = null,
		onToepassen
	}: {
		open?: boolean;
		/** Hoeveel vormen het raakt — dat staat op de knop. */
		aantal?: number;
		bezig?: boolean;
		/** Wat de vorige poging te melden had (overgeslagen hoeken). */
		melding?: string | null;
		onToepassen: (stijl: 'round' | 'chamfer', maatMm: number) => void;
	} = $props();

	let stijl = $state<'round' | 'chamfer'>('round');
	let maat = $state('3');

	const voorbeeld = $derived.by(() => {
		const zijde = 30;
		const m = Math.min(Math.max(Number(maat) || 0, 0), zijde / 2);
		const p = 2;
		if (m <= 0) return `M ${p} ${p + zijde} L ${p} ${p} L ${p + zijde} ${p}`;
		const start = `M ${p} ${p + zijde} L ${p} ${p + m}`;
		const eind = `L ${p + zijde} ${p}`;
		if (stijl === 'chamfer') return `${start} L ${p + m} ${p} ${eind}`;
		return `${start} A ${m} ${m} 0 0 1 ${p + m} ${p} ${eind}`;
	});

	const knop = $derived.by(() => {
		const m = Number(maat);
		const wat = stijl === 'round' ? 'afronden' : 'afschuinen';
		if (!aantal) return `Hoeken ${wat}`;
		const vormen = aantal === 1 ? '1 vorm' : `${aantal} vormen`;
		if (!Number.isFinite(m) || m <= 0) return `${vormen} ${wat}`;
		return `${vormen} ${wat} — ${m} mm`;
	});
</script>

<Dialog title="Hoeken" bind:open width="420px">
	<div class="hoeken">
		<div class="rij">
			<div class="stijl" role="radiogroup" aria-label="Hoekstijl">
				<button
					class="keuze"
					class:aan={stijl === 'round'}
					role="radio"
					aria-checked={stijl === 'round'}
					onclick={() => (stijl = 'round')}>Rond</button
				>
				<button
					class="keuze"
					class:aan={stijl === 'chamfer'}
					role="radio"
					aria-checked={stijl === 'chamfer'}
					onclick={() => (stijl = 'chamfer')}>Schuin</button
				>
			</div>
			<svg class="voorbeeld" viewBox="0 0 34 34" aria-hidden="true">
				<path d={voorbeeld} />
			</svg>
		</div>

		<NumberField label="Maat" unit="mm" step={0.5} min={0.1} bind:value={maat} />

		{#if stijl === 'chamfer'}
			<p class="regel let-op">
				Hiervan wordt de vorm een pad: breedte en hoogte zijn daarna niet meer los te
				wijzigen. Ongedaan maken brengt hem terug.
			</p>
		{:else}
			<p class="regel">
				Een rechthoek blijft een rechthoek, dus je kunt de radius later bijstellen.
			</p>
		{/if}
		{#if melding}
			<p class="regel let-op" role="status">{melding}</p>
		{/if}
	</div>

	<div class="ask-actions">
		<button class="btn" onclick={() => (open = false)}>Annuleren</button>
		<button
			class="btn primary"
			disabled={bezig || !aantal}
			onclick={() => onToepassen(stijl, Number(maat))}>{knop}</button
		>
	</div>
</Dialog>

<style>
	.hoeken {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}
	.rij {
		display: flex;
		align-items: center;
		gap: var(--space-4);
	}
	.stijl {
		display: flex;
		gap: var(--space-2);
	}
	.keuze {
		padding: 7px 16px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.keuze.aan {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 10%, var(--surface-1));
		color: var(--accent);
	}
	.voorbeeld {
		width: 56px;
		height: 56px;
		fill: none;
		stroke: var(--text-2);
		stroke-width: 1.6;
	}
	.regel {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.5;
		color: var(--text-2);
	}
	.regel.let-op {
		color: var(--text-1);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		background: var(--surface-2);
	}
</style>
