<script lang="ts">
	/**
	 * The colour strip under the canvas — decision B2.
	 *
	 * Two things on one row of swatches, exactly as LightBurn does it: with a
	 * selection a click moves it to the layer of that colour (creating it if
	 * needed), without a selection it sets the colour for new work. That is one
	 * action where it took three through the layers panel.
	 *
	 * On the right is what that colour remembers. A memory you cannot see is not a
	 * memory — and it has to be there because it is *not* the same as a preset: the
	 * palette knows what you last did, a preset knows what has been burned. Hence
	 * it says "remembered", never "verified".
	 */
	import { inkOn, LAYER_COLORS, stripColours, type DesignStore } from '$lib/design.svelte';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import type { EditController } from '$lib/edits.svelte';

	let {
		design,
		edits,
		canEdit = false,
		onChanged
	}: {
		design: DesignStore;
		edits: EditController;
		canEdit?: boolean;
		onChanged?: () => void;
	} = $props();

	/** Where the pointer or the keyboard is now; otherwise the active colour. */
	let pointed = $state<string | null>(null);

	// The palette, plus every layer colour it does not know: see `stripColours`. A
	// layer whose colour comes from an imported file had no swatch here, while the
	// swatches beside it were carrying layer numbers and speeds.
	let colours = $derived(
		stripColours(design.palette?.colors.map((c) => c.color) ?? LAYER_COLORS, design.operations)
	);
	let active = $derived((design.palette?.default_color ?? '').toLowerCase());
	let shown = $derived(pointed ?? active ?? null);
	let selection = $derived(design.selectedIds.length);

	/** The layer that carries this colour now, plus its place in the burn order. */
	function layerOf(colour: string) {
		const op = design.layerWithColor(colour);
		if (!op) return null;
		const number = design.operations.filter((o) => !o.grid).findIndex((o) => o.id === op.id);
		return { op, number: number < 0 ? null : number + 1 };
	}

	function values(colour: string): string | null {
		const found = layerOf(colour);
		if (found?.op.speed != null) {
			const power = found.op.power == null ? null : Math.round(found.op.power / 10);
			return `${i18n.number(found.op.speed)} mm/s${power == null ? '' : ` · ${power}%`}`;
		}
		const remembered = design.memoryFor(colour);
		if (!remembered?.speed_mm_s) return null;
		return `${i18n.number(remembered.speed_mm_s)} mm/s${
			remembered.power_percent == null ? '' : ` · ${Math.round(remembered.power_percent)}%`
		}`;
	}

	/** One sentence saying what happens if you click here. */
	function describe(colour: string): string {
		const found = layerOf(colour);
		const figures = values(colour);
		const where = found
			? t('palette.layerNamed', { n: found.number, label: found.op.label })
			: figures
				? t('palette.noLayerYetRemembered')
				: t('palette.noLayerYetBlank');
		const what = selection
			? t('palette.putInColour', { n: selection })
			: t('palette.setForNewWork');
		return `${what} ${where}${figures ? ` · ${figures}` : ''}`;
	}

	// The height of the bottom edge (this strip plus a possible warning) is
	// measured in Canvas.svelte and set there as `--palette-height` — the camera
	// pill reckons with it. One measure for the whole block, because there can be
	// more than one strip under the bed.

	async function pick(colour: string) {
		if (!canEdit || edits.busy) return;
		const ok = await edits.paletteColor(colour, design.selectedIds);
		if (!ok) return;
		await design.load();
		onChanged?.();
	}
</script>

<div class="palette" class:empty={!canEdit}>
	<!-- The heading says what a click does, not what the swatches are.
	     Before this it read "Layer colour" here, and at the far right, in small grey
	     letters, what a click would do — and *that* changes with the selection. One
	     strip with two meanings, and the difference sat in the place you look at
	     last. Now it is up front, where the label belongs. -->
	<span class="head">{selection ? t('palette.selectionToLayer') : t('palette.forNewWork')}</span>
	<div class="strip" role="group" aria-label={t('palette.aria')}>
		{#each colours as colour, index (colour)}
			{@const found = layerOf(colour)}
			<button
				class="swatch"
				class:used={!!found}
				class:now={colour === active}
				style="background: {colour}; color: {inkOn(colour)}"
				disabled={!canEdit || edits.busy}
				aria-pressed={colour === active}
				aria-label={t('palette.colourAria', { n: index + 1, description: describe(colour) })}
				title={describe(colour)}
				onpointerenter={() => (pointed = colour)}
				onpointerleave={() => (pointed = null)}
				onfocus={() => (pointed = colour)}
				onblur={() => (pointed = null)}
				onclick={() => pick(colour)}
			>
				<!-- Never colour alone: the layer number sits in the swatch, as on the
				     chips in the layers panel. A colour without a layer gets a dot —
				     then the swatch is empty but not dead. -->
				{#if found?.number}
					<span class="mono">{found.number}</span>
				{:else}
					<span class="dot" aria-hidden="true"></span>
				{/if}
			</button>
		{/each}
	</div>

	<!-- The memory, written out. This is the half of B2 you would otherwise never
	     get to see, and the place where the distinction from a preset falls. -->
	<div class="memory" aria-live="polite">
		{#if shown}
			{@const found = layerOf(shown)}
			{@const figures = values(shown)}
			<span class="dot" style="background: {shown}"></span>
			<span class="who">
				{#if found}
					{t('palette.layerNamed', { n: found.number, label: found.op.label })}
				{:else if shown === active}
					{t('palette.newWork')}
				{:else}
					{t('palette.noLayerYet')}
				{/if}
			</span>
			{#if figures}
				<span class="figures mono">{figures}</span>
				<span
					class="source"
					title={found ? t('palette.layerValues') : t('palette.memory')}
				>{found ? t('palette.inUse') : t('palette.remembered')}</span>
			{:else}
				<span class="none">{t('palette.nothingRemembered')}</span>
			{/if}
		{/if}
	</div>

	<span class="hint">
		{selection
			? selection === 1
				? t('palette.clickHintOne')
				: t('palette.clickHintMany', { n: selection })
			: t('palette.clickHintNew')}
	</span>
</div>

<style>
	.palette {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
		border-top: 1px solid var(--line);
		background: var(--surface-1);
		min-height: 40px;
		flex-wrap: wrap;
		/* At 768px this strip ran 91px off screen, and with `visible` that means
		   clipped rather than scrollable. Since decision B2 the swatches are a
		   control: a swatch you cannot reach is a lost function, not lost
		   decoration. */
		min-width: 0;
	}
	.head {
		font-size: var(--text-xs);
		color: var(--text-2);
		text-transform: none;
		white-space: nowrap;
		flex: 0 0 auto;
	}
	/* Below 800px there is no room for the word beside ten 44px swatches. The
	   swatches win: they are the control, this is the caption. */
	@media (max-width: 800px) {
		.head { display: none; }
	}
	/* The swatches always stay whole — they are the only thing here you touch —
	   but on a tablet they are 44px, and ten of those is 476px. Beside the heading
	   and the state that does not fit in 768. So wrap: two rows of swatches beats
	   one row with the last three off screen. */
	.strip {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		min-width: 0;
		/* `auto` as the basis keeps the ten swatches on one row as long as they fit;
		   only when that is no longer possible does it break. With basis 0 it wrapped
		   into four rows at 1024 as well, and that is worse than the problem. */
		flex: 0 1 auto;
	}
	.swatch {
		width: 26px;
		height: 26px;
		border: 1px solid rgb(0 0 0 / 0.18);
		border-radius: var(--radius-field);
		display: grid;
		place-items: center;
		cursor: pointer;
		padding: 0;
		font-size: var(--text-xs);
		line-height: 1;
		/* A swatch without a layer is present more faintly: that way the strip shows
		   at a glance which colours this design uses. */
		opacity: 0.55;
		transition: opacity 150ms ease-out, border-color 150ms ease-out;
	}
	.swatch.used {
		opacity: 1;
	}
	/* No lift on hover: a 26px target that jumps up a pixel shifts under your
	   cursor while you are aiming. The design system forbids layout shift on hover
	   and focus; the emphasis comes from the opacity and a slightly heavier
	   border. */
	.swatch:hover:not(:disabled) {
		opacity: 1;
		border-color: rgb(0 0 0 / 0.45);
	}
	.swatch:disabled {
		cursor: default;
	}
	.swatch:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	/* The colour for new work: a ring in the app's text colour, not in the accent —
	   the accent means "action" here, and this is a state. */
	.swatch.now {
		box-shadow: 0 0 0 2px var(--surface-1), 0 0 0 3px var(--text-1);
	}
	.dot {
		width: 4px;
		height: 4px;
		border-radius: var(--radius-dot);
		background: currentColor;
		opacity: 0.5;
	}
	.memory {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
		color: var(--text-2);
		min-width: 0;
		flex: 1;
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: var(--radius-dot);
		flex: none;
		border: 1px solid rgb(0 0 0 / 0.2);
	}
	.who {
		color: var(--text-1);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.figures {
		font-variant-numeric: tabular-nums;
		color: var(--text-1);
		white-space: nowrap;
	}
	.source,
	.none {
		border: 1px solid var(--line);
		border-radius: var(--radius-dot);
		padding: 1px var(--space-2);
		white-space: nowrap;
		/* Deliberately not an accent or status colour: this is habit, not evidence.
		   Green or amber are forbidden here — on presets those mean "verified" and
		   "extrapolated", and that is something else entirely. */
		background: var(--surface-2);
	}
	/* The closing text gives way first — it is explanation, not control. */
	.hint {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* The state and the explanation are captions to the swatches; when there is too
	   little room, *they* give way. The swatches are the control and stay whole. */
	.memory { min-width: 0; flex: 0 1 auto; overflow: hidden; }
	@media (max-width: 820px) {
		.memory,
		.hint { display: none; }
	}
	.hint {
		font-size: var(--text-xs);
		color: var(--text-2);
		white-space: nowrap;
		margin-left: auto;
	}
	@media (max-width: 1199px) {
		/* The closing text gives way first — it is explanation, not control. */
	.hint {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	/* The state and the explanation are captions to the swatches; when there is too
	   little room, *they* give way. The swatches are the control and stay whole. */
	.memory { min-width: 0; flex: 0 1 auto; overflow: hidden; }
	@media (max-width: 820px) {
		.memory,
		.hint { display: none; }
	}
	.hint {
			display: none;
		}
	}
	@media (max-width: 720px) {
		.memory {
			/* On the phone the strip is on one line with the memory below it; clipping
			   would remove exactly the part that matters. */
			flex-basis: 100%;
		}
	}
</style>
