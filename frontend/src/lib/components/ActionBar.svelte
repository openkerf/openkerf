<script lang="ts">
	/**
	 * The action bar above the canvas.
	 *
	 * Why it exists. Aligning, grouping and mirroring lived in the right-hand
	 * panel, on the Edit tab. That cost three things that all cost time: you needed
	 * a selection *and* the right tab (on the Job tab they were unfindable), the
	 * buttons sat halfway down a column that scrolled, and they ate panel height
	 * that belongs to properties. They are verbs, not properties — see the
	 * placement rule in DESIGN-SYSTEM.md.
	 *
	 * Why here and not in the top bar: the top bar is about the document and the
	 * machine (open, save, start, stop). This bar is about what is selected on the
	 * bed, and so it sits against the bed. That is also where a LightBurn user
	 * looks for it.
	 *
	 * Why icons without words, when the tool rail does the same and that is a
	 * complaint there: here they are not arbitrary but drawn in one grammar (thick
	 * line = axis, open rectangle = shape that moves), and separated per group so
	 * the row itself tells you what you are reading — history first, then aligning
	 * horizontally, then vertically, then arranging. Every button carries its name
	 * in `aria-label` and its name plus shortcut in the tooltip.
	 */
	import ArrangeIcon from './ArrangeIcon.svelte';
	import { t } from '$lib/i18n/index.svelte';
	import type { Action } from '$lib/actions';

	let {
		history,
		align,
		arrange,
		count,
		note = null,
		onMore
	}: {
		history: Action[];
		/** Eight: four horizontal, four vertical. */
		align: Action[];
		/** Group, ungroup, mirror h, mirror v. */
		arrange: Action[];
		/** How many shapes are selected — decides the text on the right. */
		count: number;
		/** Something more specific to say on that same line, for as long as it holds. */
		note?: string | null;
		/** Opens the full menu, for everything that does not fit here. */
		onMore: (event: MouseEvent) => void;
	} = $props();

	function tip(action: Action) {
		if (action.off) return `${action.label} — ${action.off}`;
		const tail = [action.explain, action.key].filter(Boolean).join(' · ');
		return tail ? `${action.label} — ${tail}` : action.label;
	}
</script>

<div class="actionbar" role="toolbar" aria-label={t('bar.aria')}>
	<div class="group" role="group" aria-label={t('bar.history')}>
		{#each history as action (action.id)}
			<button
				class="button"
				disabled={Boolean(action.off)}
				title={tip(action)}
				aria-label={action.label}
				onclick={action.run}
			>
				<ArrangeIcon name={action.icon ?? 'undo'} size={18} />
			</button>
		{/each}
	</div>

	<span class="divider" aria-hidden="true"></span>

	<!-- Two groups of four: the first row of the old grid was about the horizontal
	     axis, the second about the vertical. On one line that split disappears, so
	     there is a divider between them — otherwise it is eight icons in a row and
	     you have to read them all. -->
	<div class="group" role="group" aria-label={t('bar.alignH')}>
		{#each align.slice(0, 4) as action (action.id)}
			<button
				class="button"
				disabled={Boolean(action.off)}
				title={tip(action)}
				aria-label={action.label}
				onclick={action.run}
			>
				<ArrangeIcon name={action.icon ?? ''} size={19} />
			</button>
		{/each}
	</div>
	<div class="group" role="group" aria-label={t('bar.alignV')}>
		{#each align.slice(4) as action (action.id)}
			<button
				class="button"
				disabled={Boolean(action.off)}
				title={tip(action)}
				aria-label={action.label}
				onclick={action.run}
			>
				<ArrangeIcon name={action.icon ?? ''} size={19} />
			</button>
		{/each}
	</div>

	<span class="divider" aria-hidden="true"></span>

	<div class="group" role="group" aria-label={t('bar.arrange')}>
		{#each arrange as action (action.id)}
			<button
				class="button"
				disabled={Boolean(action.off)}
				title={tip(action)}
				aria-label={action.label}
				onclick={action.run}
			>
				<ArrangeIcon name={action.icon ?? ''} size={19} />
			</button>
		{/each}
	</div>

	<span class="divider" aria-hidden="true"></span>

	<!-- The way to the rest. A bar cannot carry everything, but it must say that
	     there is more — otherwise the context menu is a secret. -->
	<button class="more" title={t('bar.more.title')} onclick={onMore}>
		{t('bar.more')}
		<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
	</button>

	<span class="stretch"></span>

	<!-- What is selected, in words. The panel says it too, but that can be on
	     another tab; this bar should say what it works on. Without this line a row
	     of grey buttons is unexplained. -->
	<!-- A note takes this line over for as long as it lasts: "shape 2 of 3 under the
	     pointer" is about the selection you have just made, so it belongs where the
	     selection is reported and not in a strip of its own — a strip below the bed
	     shortens the canvas and moves the drawing under your pointer. -->
	<p class="state" aria-live="polite">
		{note ?? (count === 0 ? t('bar.selection.none') : t('bar.selection.count', { n: count }))}
	</p>
</div>

<style>
	.actionbar {
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: 3px var(--space-3);
		min-height: 38px;
		background: var(--surface-1);
		border-bottom: 1px solid var(--line);
	}
	.group {
		display: flex;
		align-items: center;
		gap: 1px;
	}
	.button {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		border-radius: var(--radius-field);
		color: var(--text-1);
		background: none;
		border: none;
	}
	.button:hover:not(:disabled) {
		background: var(--surface-2);
	}
	.button:disabled {
		color: var(--text-2);
		opacity: 0.38;
		cursor: not-allowed;
	}
	.divider {
		width: 1px;
		height: 20px;
		background: var(--line);
		margin: 0 2px;
	}
	.more {
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
	.more:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.stretch {
		flex: 1;
	}
	.state {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--text-2);
		white-space: nowrap;
	}
	/* Below 1200px this is not the app this round is about; the bar keeps working
	   but shrinks to what fits. Polishing belongs to the tablet round. */
	@media (max-width: 1199px) {
		.actionbar {
			overflow-x: auto;
		}
		.state {
			display: none;
		}
	}
</style>
