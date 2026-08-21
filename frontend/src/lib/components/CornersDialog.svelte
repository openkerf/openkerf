<script lang="ts">
	/**
	 * CornersDialog afronden of afschuinen.
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
	import { i18n, t } from '$lib/i18n/index.svelte';
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
		const wat = t(stijl === 'round' ? 'corners.doRound' : 'corners.doChamfer');
		if (!aantal) return wat;
		const vormen = t('corners.shapes', { n: aantal });
		if (!Number.isFinite(m) || m <= 0) return t('corners.button', { shapes: vormen, what: wat });
		return t('corners.buttonSize', { shapes: vormen, what: wat, size: i18n.number(m) });
	});
</script>

<Dialog title={t('corners.title')} bind:open width="420px">
	<div class="hoeken">
		<div class="rij">
			<div class="stijl" role="radiogroup" aria-label={t('corners.styleAria')}>
				<button
					class="keuze"
					class:aan={stijl === 'round'}
					role="radio"
					aria-checked={stijl === 'round'}
					onclick={() => (stijl = 'round')}>{t('corners.round')}</button
				>
				<button
					class="keuze"
					class:aan={stijl === 'chamfer'}
					role="radio"
					aria-checked={stijl === 'chamfer'}
					onclick={() => (stijl = 'chamfer')}>{t('corners.chamfer')}</button
				>
			</div>
			<svg class="voorbeeld" viewBox="0 0 34 34" aria-hidden="true">
				<path d={voorbeeld} />
			</svg>
		</div>

		<NumberField label={t('corners.size')} unit="mm" step={0.5} min={0.1} bind:value={maat} />

		{#if stijl === 'chamfer'}
			<p class="regel let-op">{t('corners.chamferWarning')}</p>
		{:else}
			<p class="regel">{t('corners.roundKeeps')}</p>
		{/if}
		{#if melding}
			<p class="regel let-op" role="status">{melding}</p>
		{/if}
	</div>

	<div class="ask-actions">
		<button class="btn" onclick={() => (open = false)}>{t('common.cancel')}</button>
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
