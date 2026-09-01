<script lang="ts">
	/**
	 * Make a stencil: bridge the parts a cut-out would set loose.
	 *
	 * A verb with two settings, which by the placement rule (DESIGN-SYSTEM v4) is a small
	 * dialog the menu opens — the same shape as Round the corners.
	 *
	 * What makes this one different from the ordinary bridges is that the app has to say
	 * what it *found* before you decide anything: how many islands there are, and how far a
	 * bridge has to reach. Two millimetres means nothing on its own; two millimetres across
	 * a crossing of 2.4 mm means the bridge is nearly the whole thickness of the letter.
	 * So the answer of the preview stands above the fields and not under a button.
	 */
	import { i18n, t } from '$lib/i18n/index.svelte';
	import Dialog from './Dialog.svelte';
	import NumberField from './NumberField.svelte';

	type Report = {
		islands: number;
		bridges: number;
		shortest_mm: number | null;
		skipped: number;
	};

	let {
		open = $bindable(false),
		count = 0,
		busy = false,
		report = null,
		error = null,
		onLook,
		onApply
	}: {
		open?: boolean;
		/** How many shapes it would touch — that is on the button. */
		count?: number;
		busy?: boolean;
		/** What the preview found, or null while it has not answered yet. */
		report?: Report | null;
		/** The refusal the preview came back with, said in full. */
		error?: string | null;
		onLook: (bridgeMm: number, perIsland: number) => void;
		onApply: (bridgeMm: number, perIsland: number) => void;
	} = $props();

	let bridge = $state('3');
	let per = $state('2');

	const numbers = $derived({
		bridge: Number(bridge),
		per: Math.round(Number(per))
	});
	const usable = $derived(
		Number.isFinite(numbers.bridge) && numbers.bridge > 0 && numbers.per >= 1
	);

	// Asked again on every change, with a moment of rest: the answer is a measurement on
	// the real geometry and it changes with both fields — the number of bridges follows
	// "per island", and whether the width fits follows the crossing.
	let timer: ReturnType<typeof setTimeout> | null = null;
	$effect(() => {
		const { bridge: width, per: each } = numbers;
		if (!open || !usable) return;
		if (timer) clearTimeout(timer);
		timer = setTimeout(() => onLook(width, each), 250);
	});

	// The one line that turns the setting into a judgement instead of a number: a bridge
	// that is wider than the gap it spans is not wrong, but it is worth seeing.
	const tight = $derived(
		report?.shortest_mm != null && numbers.bridge > report.shortest_mm
	);
</script>

<Dialog title={t('stencil.title')} bind:open width="440px">
	<p class="why">{t('stencil.why')}</p>

	{#if error}
		<p class="notice failure" role="alert">{error}</p>
	{:else if report}
		<p class="found" role="status">
			{t('stencil.found', { islands: report.islands, bridges: report.bridges })}
		</p>
		{#if report.shortest_mm != null}
			<!-- `mm` and not `n`: `n` is the plural selector and is deliberately the one
			     value that does *not* go through `Intl`, so a crossing named `n` would
			     print 3.594 to a reader whose canvas writes 3,594 everywhere else. -->
			<p class="hint">{t('stencil.crossing', { mm: i18n.mm(report.shortest_mm) })}</p>
		{/if}
		{#if tight}
			<p class="hint warn">{t('stencil.wide')}</p>
		{/if}
	{:else}
		<p class="hint">{t('stencil.looking')}</p>
	{/if}

	<div class="fields">
		<NumberField label={t('stencil.bridge')} unit="mm" step={0.5} min={0.6} bind:value={bridge} />
		<NumberField label={t('stencil.per')} step={1} min={1} max={6} bind:value={per} />
	</div>

	<p class="hint">{t('stencil.untried')}</p>

	<!-- `ask-actions` and not a wrapper of our own: that class is what gives a dialog's
	     buttons their padding, border and radius, and it carries the extra spacing on a
	     touch screen. Written locally the button came out flat and unbordered beside every
	     other dialog in the app. And a way out beside the way on: every other dialog here
	     offers Cancel first, so the primary button is never the only thing to press. -->
	<div class="ask-actions">
		<button class="btn" onclick={() => (open = false)}>{t('common.cancel')}</button>
		<button
			class="btn primary"
			disabled={busy || !usable || !!error || !report?.bridges}
			onclick={() => onApply(numbers.bridge, numbers.per)}
		>
			<!-- The numbers on the button, because it is the last thing read before the
			     shape changes. `bridges` is a plain count and `mm` a measurement, so the
			     measurement goes through `Intl` and the count does not. -->
			{t('stencil.apply', {
				n: count,
				bridges: report?.bridges ?? 0,
				mm: i18n.number(numbers.bridge)
			})}
		</button>
	</div>
</Dialog>

<style>
	.why {
		margin: 0 0 var(--space-3);
		max-width: 46ch;
		font-size: var(--text-sm);
		color: var(--text-1);
	}
	.found {
		margin: 0 0 var(--space-1);
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-1);
	}
	.hint { margin: 0 0 var(--space-2); font-size: var(--text-xs); color: var(--text-2); }
	.warn { color: var(--warn-text, var(--text-1)); }
	.fields {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
		margin: var(--space-3) 0;
	}
</style>
