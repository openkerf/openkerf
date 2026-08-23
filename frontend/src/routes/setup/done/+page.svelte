<script lang="ts">
	/**
	 * Step 5.
	 *
	 * This page only said "the machine has been created" and put you in an empty work
	 * area. That is exactly where the whole task's first "now what?" fell: you have a
	 * machine, and nothing tells you how to get from nothing to a first cut. Now that
	 * route is there, in the order in which you walk it.
	 *
	 * It also claimed success without checking whether there was anything: anybody
	 * arriving here without `machine` in the URL read "The machine has been created".
	 */
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import StarterOffer from '$components/StarterOffer.svelte';
	import { t } from '$lib/i18n/index.svelte';
	import { createStore } from '$lib/setup.svelte';
	import { SheetStore } from '$lib/sheets.svelte';

	const store = createStore();

	let machinePath = $derived($page.url.searchParams.get('machine') ?? '');
	let machine = $derived(store.machines.find((m) => m.path === machinePath) ?? null);
	let loaded = $state(false);

	/**
	 * The sheet does not follow the machine by itself (gap E2).
	 *
	 * A sheet is a piece of material, not a copy of the bed — so scaling along *without*
	 * asking would silently stretch the 200 × 300 offcut you have just set up to bed size.
	 * But the opposite is what happens now: you set up a 610 × 406 bed and start your
	 * first design in a 310 × 210 frame that came from the *previous* machine and means
	 * nothing.
	 *
	 * Hence it is asked here, in the one place where the bed size has just changed: one
	 * line, two buttons, and the answer is final.
	 */
	const sheets = new SheetStore(() =>
		typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '')
	);
	let bed = $state<{ w: number; h: number } | null>(null);
	/** Answered (adjusted or left as it was): then the question is gone. */
	let sheetAnswer = $state<'adjusted' | 'kept' | null>(null);

	let sheetQuestion = $derived.by(() => {
		const sheet = sheets.active;
		if (!bed || !sheet || sheetAnswer) return null;
		// A tenth of a millimetre difference is rounding, not a mismatch.
		const differs =
			Math.abs(sheet.width_mm - bed.w) > 0.5 || Math.abs(sheet.height_mm - bed.h) > 0.5;
		return differs ? { sheet, bed } : null;
	});

	function size(value: number) {
		return String(Math.round(value * 10) / 10).replace('.', ',');
	}

	async function useBedSize() {
		const ask = sheetQuestion;
		if (!ask) return;
		if (await sheets.update(ask.sheet.id, { width_mm: bed!.w, height_mm: bed!.h }))
			sheetAnswer = 'adjusted';
	}

	onMount(async () => {
		await store.loadMachines();
		loaded = true;
		// The bed size in millimetres comes from the status: the engine's settings hand
		// back "24.0in", and that is the wrong unit to compute with here.
		await sheets.load();
		try {
			const response = await fetch('/api/status');
			if (!response.ok) return;
			const state = await response.json();
			const wanted = $page.url.searchParams.get('machine') ?? '';
			const dev =
				(state.devices ?? []).find((d: { path: string }) => d.path === wanted) ??
				(state.devices ?? []).find((d: { active: boolean }) => d.active);
			if (dev?.bed?.width_mm > 0 && dev?.bed?.height_mm > 0)
				bed = { w: dev.bed.width_mm, h: dev.bed.height_mm };
		} catch {
			/* without a bed size we do not ask the question — better nothing than a guess */
		}
	});

	const STEPS = [
		{ head: t('setup.done.draw.title'), hint: t('setup.done.draw.body') },
		{ head: t('setup.done.layer.title'), hint: t('setup.done.layer.body') },
		{ head: t('job.frame'), hint: t('setup.done.frame.body') },
		{ head: t('job.startJob'), hint: t('setup.done.start.body') }
	];
</script>

<svelte:head><title>{t('setup.head.done')}</title></svelte:head>

<section class="setup narrow">
	{#if loaded && !machine}
		<h1>{t('setup.gone')}</h1>
		<p class="muted">
			{machinePath ? t('setup.gone.path', { path: machinePath }) : t('setup.gone.noPath')}
			{t('setup.gone.bookmark')}
		</p>
		<div class="actions">
			<a class="btn primary" href="/setup">{t('setup.toYourMachines')}</a>
		</div>
	{:else}
		<h1>{machine ? t('setup.ready', { machine: machine.label }) : t('setup.ready.plain')}</h1>
		<p class="muted">{t('setup.firstJob')}</p>

		{#if sheetQuestion}
			<div class="sheetask">
				<h2 class="head">{t('setup.sheetFits')}</h2>
				<p>
					{t('setup.sheetFits.body', {
						sheet: `${sheetQuestion.sheet.name} — ${size(sheetQuestion.sheet.width_mm)} × ${size(
							sheetQuestion.sheet.height_mm
						)} mm`,
						machine: machine?.label ?? t('setup.sheetFits.thisMachine'),
						bed: `${size(sheetQuestion.bed.w)} × ${size(sheetQuestion.bed.h)} mm`
					})}
				</p>
				<p class="muted">
					{t('setup.sheetFits.offcut', { width: size(sheetQuestion.sheet.width_mm) })}
				</p>
				<div class="sheetbuttons">
					<button class="btn primary" disabled={sheets.busy} onclick={useBedSize}>
						{t('setup.sheetToBed')}
					</button>
					<button class="btn subtle" onclick={() => (sheetAnswer = 'kept')}>
						{t('setup.sheetLeave')}
					</button>
				</div>
				{#if sheets.error}<p class="failure" role="alert">{sheets.error}</p>{/if}
			</div>
		{:else if sheetAnswer === 'adjusted' && sheets.active}
			<p class="sheetdone" role="status">
				{t('setup.sheetNow', {
					sheet: sheets.active.name,
					size: `${size(sheets.active.width_mm)} × ${size(sheets.active.height_mm)} mm`
				})}
			</p>
		{/if}

		<!-- The moment the whole preset story exists for: a machine has just been
		     defined and there is not one setting for it. This is the same card the
		     material library carries at its top, fed by the same function, so the offer
		     is made once and reads the same in both places. It sits above the four
		     steps because step two of them is choosing a layer's settings, and this is
		     where those come from. -->
		<StarterOffer />

		<h2>{t('setup.firstCut')}</h2>
		<ol class="gone">
			{#each STEPS as step, index (step.head)}
				<li>
					<span class="number mono">{index + 1}</span>
					<span class="text">
						<strong>{step.head}</strong>
						<span class="muted">{step.hint}</span>
					</span>
				</li>
			{/each}
		</ol>

		<div class="actions">
			<a class="btn" href="/setup">{t('setup.anotherMachine')}</a>
			<a class="btn primary" href="/">{t('setup.toWorkArea')}</a>
		</div>
	{/if}
</section>

<style>
	h2 {
		font-size: var(--text-sm);
		font-weight: 600;
		margin: var(--space-6) 0 var(--space-3);
	}
	.gone {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: var(--space-3);
	}
	.gone li {
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
	}
	.number {
		flex: none;
		width: 22px;
		height: 22px;
		display: grid;
		place-items: center;
		border-radius: var(--radius-dot);
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		/* The same as the step dots on the welcome screen: accent on an accent tint does
		   not make AA. */
		color: var(--text-1);
		font-size: var(--text-xs);
	}
	.text {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.text .muted {
		font-size: var(--text-xs);
	}

	/* A question, not a warning: nothing is broken, there is something to choose. Hence
	   the accent in the border and not amber. */
	.sheetask {
		margin-top: var(--space-6);
		padding: var(--space-4);
		border: 1px solid var(--line);
		border-left: 3px solid var(--accent);
		border-radius: var(--radius-card);
		background: var(--surface-2);
	}
	.sheetask .head {
		margin: 0 0 var(--space-2);
	}
	.sheetask p {
		margin: 0 0 var(--space-2);
		font-size: var(--text-xs);
	}
	.sheetbuttons {
		display: flex;
		flex-wrap: wrap;
		/* Two outcomes that exclude each other: far enough apart not to bad-aim with a
		   thumb. */
		gap: var(--space-6);
		margin-top: var(--space-3);
	}
	/* With a glove on, 37px is too little; the buttons in the setup are otherwise mouse
	   buttons, so this lives here and not in the layout. */
	@media (max-width: 1199px), (pointer: coarse) {
		.sheetbuttons :global(.btn) {
			min-height: 44px;
		}
	}
	.sheetdone {
		margin-top: var(--space-6);
		font-size: var(--text-xs);
		color: var(--ok);
	}
	.failure {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xs);
		color: var(--danger);
	}
</style>
