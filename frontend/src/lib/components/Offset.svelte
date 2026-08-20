<script lang="ts">
	/**
	 * Offset — een pad naar buiten of naar binnen zetten.
	 *
	 * Dit liep via `window.prompt('Offset in mm (negatief = naar binnen)', '2')`.
	 * Dat is de enige plek in de app waar een browservenster de vraag stelde, en
	 * daar is alles aan mis: het staat buiten het thema, het valideert niets (een
	 * letter komt er als NaN uit en levert stille onzin op), de tekst is niet te
	 * vertalen, en op sommige browsers is hij door de gebruiker uit te zetten —
	 * dan doet de knop niets, zonder één woord.
	 *
	 * Hetzelfde venster als bij Hoeken: klein, met de betekenis erbij, en een
	 * primaire knop die zegt wat er gaat gebeuren.
	 */
	import { i18n, t } from '$lib/i18n/index.svelte';
	import Dialog from './Dialog.svelte';
	import NumberField from './NumberField.svelte';

	let {
		open = $bindable(false),
		aantal = 0,
		bezig = false,
		onToepassen
	}: {
		open?: boolean;
		aantal?: number;
		bezig?: boolean;
		onToepassen: (afstandMm: number) => void;
	} = $props();

	let afstand = $state('2');
	let waarde = $derived(Number(afstand));
	let geldig = $derived(Number.isFinite(waarde) && waarde !== 0);
	let richting = $derived(t(waarde > 0 ? 'offset.outward' : 'offset.inward'));
</script>

<Dialog title={t('offset.title')} bind:open width="400px">
	<div class="offset">
		<div class="paar">
			<NumberField label={t('offset.distance')} unit="mm" step={0.5} bind:value={afstand} />
			<!-- The direction in words beside the number. A minus sign is the input,
			     "inward" is the meaning — and those two are not the same as long as you
			     still have to work out which side is negative. -->
			<p class="richting">
				{#if geldig}
					{t('offset.reading', { mm: i18n.number(Math.abs(waarde)), direction: richting })}
				{:else}
					{t('offset.fillIn')}
				{/if}
			</p>
		</div>
		<p class="regel">{t('offset.explain')}</p>
	</div>

	<div class="ask-actions">
		<button class="btn" onclick={() => (open = false)}>{t('common.cancel')}</button>
		<button
			class="btn primary"
			disabled={bezig || !geldig || !aantal}
			onclick={() => onToepassen(waarde)}
		>
			{#if !aantal}
				{t('offset.make')}
			{:else}
				{t('offset.button', {
					shapes: t('corners.shapes', { n: aantal }),
					mm: Math.abs(waarde) ? i18n.number(Math.abs(waarde)) : '?',
					direction: richting
				})}
			{/if}
		</button>
	</div>
</Dialog>

<style>
	.offset {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}
	.paar {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
		align-items: end;
	}
	.richting {
		margin: 0 0 6px;
		font-size: var(--text-xs);
		color: var(--text-2);
	}
	.regel {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.5;
		color: var(--text-2);
	}
</style>
