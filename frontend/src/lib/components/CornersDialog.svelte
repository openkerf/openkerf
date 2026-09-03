<script lang="ts">
	/**
	 * CornersDialog afronden of afschuinen.
	 *
	 * This sat as a collapsed fold in the right-hand panel. It is a verb with two
	 * settings, which puts it between two stools: too much for a menu entry, too little
	 * for a panel section you always scroll past. By the placement rule (DESIGN-SYSTEM v4)
	 * this is an action with parameters, and that belongs in a small dialog the menu opens
	 * — one place, with the preview beside it, and gone as soon as you are done.
	 *
	 * The drawing is not decoration: "5 mm" says nothing about how round that corner
	 * becomes. See DESIGN-SYSTEM, "A form that makes shape shows that shape".
	 */
	import { i18n, t } from '$lib/i18n/index.svelte';
	import Dialog from './Dialog.svelte';
	import NumberField from './NumberField.svelte';

	let {
		open = $bindable(false),
		count = 0,
		busy = false,
		notice = null,
		onToepassen
	}: {
		open?: boolean;
		/** How many shapes it touches — that is on the button. */
		count?: number;
		busy?: boolean;
		/** What the previous attempt had to report (skipped corners). */
		notice?: string | null;
		onToepassen: (stijl: 'round' | 'chamfer', sizeMm: number) => void;
	} = $props();

	let stijl = $state<'round' | 'chamfer'>('round');
	let size = $state('3');

	const preview = $derived.by(() => {
		const side = 30;
		const m = Math.min(Math.max(Number(size) || 0, 0), side / 2);
		const p = 2;
		if (m <= 0) return `M ${p} ${p + side} L ${p} ${p} L ${p + side} ${p}`;
		const start = `M ${p} ${p + side} L ${p} ${p + m}`;
		const end = `L ${p + side} ${p}`;
		if (stijl === 'chamfer') return `${start} L ${p + m} ${p} ${end}`;
		return `${start} A ${m} ${m} 0 0 1 ${p + m} ${p} ${end}`;
	});

	const button = $derived.by(() => {
		const m = Number(size);
		const wat = t(stijl === 'round' ? 'corners.doRound' : 'corners.doChamfer');
		if (!count) return wat;
		const shapes = t('corners.shapes', { n: count });
		if (!Number.isFinite(m) || m <= 0) return t('corners.button', { shapes: shapes, what: wat });
		return t('corners.buttonSize', { shapes: shapes, what: wat, size: i18n.number(m) });
	});
</script>

<Dialog title={t('corners.title')} bind:open width="420px">
	<div class="corners">
		<div class="row">
			<div class="stijl" role="radiogroup" aria-label={t('corners.styleAria')}>
				<button
					class="choice"
					class:on={stijl === 'round'}
					role="radio"
					aria-checked={stijl === 'round'}
					onclick={() => (stijl = 'round')}>{t('corners.round')}</button
				>
				<button
					class="choice"
					class:on={stijl === 'chamfer'}
					role="radio"
					aria-checked={stijl === 'chamfer'}
					onclick={() => (stijl = 'chamfer')}>{t('corners.chamfer')}</button
				>
			</div>
			<svg class="preview" viewBox="0 0 34 34" aria-hidden="true">
				<path d={preview} />
			</svg>
		</div>

		<NumberField label={t('corners.size')} unit="mm" step={0.5} min={0.1} bind:value={size} />

		{#if stijl === 'chamfer'}
			<p class="row let-op">{t('corners.chamferWarning')}</p>
		{:else}
			<p class="row">{t('corners.roundKeeps')}</p>
		{/if}
		{#if notice}
			<p class="row let-op" role="status">{notice}</p>
		{/if}
	</div>

	<div class="ask-actions">
		<button class="btn" onclick={() => (open = false)}>{t('common.cancel')}</button>
		<button
			class="btn primary"
			disabled={busy || !count}
			title={busy ? t('reason.busy') : count ? undefined : t('reason.pickShape')}
			onclick={() => onToepassen(stijl, Number(size))}>{button}</button
		>
	</div>
</Dialog>

<style>
	.corners {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}
	.row {
		display: flex;
		align-items: center;
		gap: var(--space-4);
	}
	.stijl {
		display: flex;
		gap: var(--space-2);
	}
	.choice {
		padding: 7px 16px;
		border: 1px solid var(--line);
		border-radius: var(--radius-field);
		background: var(--surface-1);
		color: var(--text-1);
	}
	.choice.on {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 10%, var(--surface-1));
		color: var(--accent);
	}
	.preview {
		width: 56px;
		height: 56px;
		fill: none;
		stroke: var(--text-2);
		stroke-width: 1.6;
	}
	.row {
		margin: 0;
		font-size: var(--text-xs);
		line-height: 1.5;
		color: var(--text-2);
	}
	.row.let-op {
		color: var(--text-1);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-field);
		background: var(--surface-2);
	}
</style>
