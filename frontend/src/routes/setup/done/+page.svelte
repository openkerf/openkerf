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
	import Notice from '$components/Notice.svelte';
	import Why from '$components/Why.svelte';
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

<section class="setup">
	{#if loaded && !machine}
		<h1 class="title">{t('setup.gone')}</h1>
		<p>
			{machinePath ? t('setup.gone.path', { path: machinePath }) : t('setup.gone.noPath')}
			{t('setup.gone.bookmark')}
		</p>
		<div class="ask-actions">
			<a class="btn primary" href="/setup">{t('setup.toYourMachines')}</a>
		</div>
	{:else}
		<h1 class="title">{machine ? t('setup.ready', { machine: machine.label }) : t('setup.ready.plain')}</h1>
		<p>{t('setup.firstJob')}</p>

		{#if sheetQuestion}
			<!-- A question, not a warning: nothing is broken, there is something to choose.
			     So a block of its own with two equal answers, and the step's one primary
			     stays "To the work area". -->
			<div class="card inset sheetask">
				<h2 class="title">{t('setup.sheetFits')}</h2>
				<p>
					{t('setup.sheetFits.body', {
						sheet: `${sheetQuestion.sheet.name} — ${size(sheetQuestion.sheet.width_mm)} × ${size(
							sheetQuestion.sheet.height_mm
						)} mm`,
						machine: machine?.label ?? t('setup.sheetFits.thisMachine'),
						bed: `${size(sheetQuestion.bed.w)} × ${size(sheetQuestion.bed.h)} mm`
					})}
				</p>
				<Why>{t('setup.sheetFits.offcut', { width: size(sheetQuestion.sheet.width_mm) })}</Why>
				<!-- Two outcomes that exclude each other: the one that leaves things as they
				     are first, the change last. -->
				<div class="ask-actions">
					<button class="btn" onclick={() => (sheetAnswer = 'kept')}>
						{t('setup.sheetLeave')}
					</button>
					<button class="btn" disabled={sheets.busy} title={sheets.busy ? t('reason.busy') : undefined} onclick={useBedSize}>
						{t('setup.sheetToBed')}
					</button>
				</div>
				{#if sheets.error}<Notice tone="danger" live>{sheets.error}</Notice>{/if}
			</div>
		{:else if sheetAnswer === 'adjusted' && sheets.active}
			<div class="after">
				<Notice tone="ok" live>
					{t('setup.sheetNow', {
						sheet: sheets.active.name,
						size: `${size(sheets.active.width_mm)} × ${size(sheets.active.height_mm)} mm`
					})}
				</Notice>
			</div>
		{/if}

		<!-- The moment the whole preset story exists for: a machine has just been
		     defined and there is not one setting for it. This is the same card the
		     material library carries at its top, fed by the same function, so the offer
		     is made once and reads the same in both places. It sits above the four
		     steps because step two of them is choosing a layer's settings, and this is
		     where those come from. -->
		<StarterOffer framed={false} />

		<h2 class="label-section firstcut">{t('setup.firstCut')}</h2>
		<ol class="gone">
			{#each STEPS as step, index (step.head)}
				<li>
					<span class="number">{index + 1}</span>
					<span class="text">
						<strong>{step.head}</strong>
						<span class="help">{step.hint}</span>
					</span>
				</li>
			{/each}
		</ol>

		<div class="ask-actions">
			<a class="btn" href="/setup">{t('setup.anotherMachine')}</a>
			<a class="btn primary" href="/">{t('setup.toWorkArea')}</a>
		</div>
	{/if}
</section>

<style>
	.firstcut {
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
	/* An order, not a selection: a quiet ring in ink, and the accent stays for the one
	   step pill above that says where you are. */
	.number {
		flex: none;
		width: 22px;
		height: 22px;
		display: grid;
		place-items: center;
		border: 1px solid var(--line);
		border-radius: var(--radius-dot);
		background: var(--surface-2);
		color: var(--text-1);
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
	}
	.text {
		display: grid;
		gap: var(--space-1);
		min-width: 0;
	}

	.sheetask {
		display: grid;
		gap: var(--space-2);
		margin-top: var(--space-6);
	}
	.sheetask p {
		margin: 0;
	}
	.sheetask .ask-actions {
		margin-top: var(--space-2);
	}
	.after {
		margin-top: var(--space-6);
	}
</style>
