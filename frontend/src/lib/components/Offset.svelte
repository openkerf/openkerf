<script lang="ts">
	/**
	 * Offset — een pad naar buiten of naar binnen zetten.
	 *
	 * This went through `window.prompt('Offset in mm (negative = inwards)', '2')`. That is
	 * the only place in the app where a browser dialog asked the question, and everything
	 * about it is wrong: it sits outside the theme, it validates nothing (a letter comes
	 * out as NaN and produces silent nonsense), the text cannot be translated, and in some
	 * browsers the user can switch it off — and then the button does nothing, without a
	 * word.
	 *
	 * The same dialog as with CornersDialog: small, with the meaning beside it, and a
	 * primary button that says what is going to happen.
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
