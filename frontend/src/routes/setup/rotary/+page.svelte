<script lang="ts">
	/**
	 * The rotary, with the machine it is bolted into.
	 *
	 * A route of its own and not a block on the work-area page: this is a value you set
	 * and read back (the placement rule sends that to a panel), but it is machine-wide and
	 * it carries a calibration you do standing at the laser. It is not one of the five
	 * wizard steps either, so the layout's stepper stays out of it — the same shape as
	 * "Settings" reached from the machine list.
	 *
	 * What this page must never do is scale the drawing. The scale lives only while the
	 * plan is built (see api/openkerf_api/rotary.py); the canvas keeps saying what you
	 * drew, and this page says what will happen to it.
	 */
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import NumberField from '$components/NumberField.svelte';
	import Notice from '$components/Notice.svelte';
	import Why from '$components/Why.svelte';
	import { i18n, t } from '$lib/i18n/index.svelte';
	import { createStore } from '$lib/setup.svelte';
	import { rotary } from '$lib/rotary.svelte';
	import {
		SCALE_MAX,
		SCALE_MIN,
		burnedHeightMm,
		calibrationFactor,
		circumferenceMm,
		scaleIsSane,
		stepsFactor
	} from '$lib/rotary';

	const store = createStore();

	let machinePath = $derived($page.url.searchParams.get('machine') ?? '');
	let machine = $derived(store.machines.find((m) => m.path === machinePath) ?? null);

	// The form is a draft: nothing goes to the machine until Save. A rotary that changed
	// on every keystroke would put a half-typed diameter (a "8" on its way to 80) into the
	// next job.
	let active = $state(false);
	let kind = $state<'chuck' | 'roller'>('chuck');
	let diameter = $state('80');
	let circumference = $state('0');
	let scaleSource = $state<'none' | 'manual' | 'steps'>('none');
	let manualScale = $state('1');
	let flatSteps = $state('0');
	let rotarySteps = $state('0');
	let saved = $state(false);

	// The calibration is its own small form: it computes a factor and writes it, and it
	// does not need the rest of the page to be saved first.
	let commanded = $state('100');
	let measured = $state('');

	onMount(async () => {
		await store.loadMachines();
		await rotary.load(true);
		fill();
	});

	function fill() {
		const state = rotary.state;
		active = state.active;
		kind = state.kind;
		diameter = String(state.diameter_mm || 80);
		circumference = String(state.circumference_mm || 0);
		scaleSource = state.scale_source;
		manualScale = String(state.manual_scale_y || 1);
		flatSteps = String(state.flat_steps_per_mm || 0);
		rotarySteps = String(state.rotary_steps_per_mm || 0);
	}

	let draftCircumference = $derived(
		circumferenceMm({
			kind,
			diameter_mm: Number(diameter) || 0,
			circumference_mm: Number(circumference) || 0
		})
	);

	/** What the draft would send Y into the machine with. Computed here so the sentence
	 *  under the field is about what you typed and not about what was saved. */
	let draftScale = $derived.by(() => {
		if (scaleSource === 'manual') return Number(manualScale) || 1;
		if (scaleSource === 'steps')
			return stepsFactor(Number(flatSteps) || 0, Number(rotarySteps) || 0);
		return 1;
	});

	let previewFactor = $derived(
		calibrationFactor(rotary.state.scale_y || 1, Number(commanded) || 0, Number(measured) || 0)
	);
	let previewUsable = $derived(
		Number(commanded) > 0 && Number(measured) > 0 && scaleIsSane(previewFactor)
	);

	async function save() {
		saved = false;
		const ok = await rotary.save({
			active,
			kind,
			diameter_mm: Number(diameter) || 0,
			circumference_mm: Number(circumference) || 0,
			scale_source: scaleSource,
			manual_scale_y: Number(manualScale) || 1,
			flat_steps_per_mm: Number(flatSteps) || 0,
			rotary_steps_per_mm: Number(rotarySteps) || 0
		});
		if (ok) {
			saved = true;
			fill();
		}
	}

	async function useFactor() {
		saved = false;
		if (await rotary.calibrate(Number(commanded) || 0, Number(measured) || 0)) {
			measured = '';
			fill();
			saved = true;
		}
	}

	const CHECKLIST = [
		'rotary.checklist.1',
		'rotary.checklist.2',
		'rotary.checklist.3',
		'rotary.checklist.4',
		'rotary.checklist.5',
		'rotary.checklist.6',
		'rotary.checklist.7',
		'rotary.checklist.8',
		'rotary.checklist.9',
		'rotary.checklist.10'
	] as const;
</script>

<svelte:head><title>{t('rotary.head')}</title></svelte:head>

<section class="setup">
	{#if rotary.error}<Notice tone="danger" live>{rotary.error}</Notice>{/if}

	<h1 class="title">{t('rotary.title')}</h1>

	{#if !machinePath}
		<p>{t('rotary.needsMachine')}</p>
		<div class="ask-actions"><a class="btn primary" href="/setup">{t('rotary.backToMachines')}</a></div>
	{:else}
		<p>{t('ux.rotary.purpose')}</p>
		{#if machine}
			<p class="help">{t('rotary.forMachine', { machine: machine.label })}</p>
		{/if}

		{#if rotary.state.engine_rotary}
			<!-- grbl, lhystudios and family bring MeerK40t's own rotary. That one has the
			     user's settings in it and ours would fight it, so we say so instead of
			     offering a second scale. -->
			<div class="after"><Notice tone="info">{t('rotary.engineOwn')}</Notice></div>
		{:else}
			<label class="switch">
				<input type="checkbox" bind:checked={active} />
				<span>{t('rotary.use')}</span>
			</label>
			<p class="help">{t('rotary.use.hint')}</p>
			<p class="help warn">{t('ux.rotary.home')}</p>

			<fieldset class="group">
				<legend class="label-section">{t('rotary.kind')}</legend>
				<label class="radio">
					<input type="radio" bind:group={kind} value="chuck" />
					<span>{t('rotary.kind.chuck')}</span>
				</label>
				<label class="radio">
					<input type="radio" bind:group={kind} value="roller" />
					<span>{t('rotary.kind.roller')}</span>
				</label>

				{#if kind === 'chuck'}
					<NumberField
						label={t('rotary.diameter')}
						unit="mm"
						bind:value={diameter}
						step={1}
						min={0}
					/>
					<p class="help">{t('rotary.diameter.hint')}</p>
				{:else}
					<NumberField
						label={t('rotary.circumference')}
						unit="mm"
						bind:value={circumference}
						step={1}
						min={0}
					/>
					<p class="help">{t('rotary.circumference.hint')}</p>
				{/if}
				{#if draftCircumference > 0}
					<p class="fact">{t('rotary.circumference.is', { mm: i18n.number(Math.round(draftCircumference * 100) / 100) })}</p>
				{/if}
			</fieldset>

			<fieldset class="group">
				<legend class="label-section">{t('rotary.scale')}</legend>
				<!-- Why the first choice is the default: reasoning, so behind the fold. -->
				<Why>{t('rotary.scale.explain')}</Why>
				<label class="radio">
					<input type="radio" bind:group={scaleSource} value="none" />
					<span>{t('rotary.scale.source.none')}</span>
				</label>
				<label class="radio">
					<input type="radio" bind:group={scaleSource} value="manual" />
					<span>{t('rotary.scale.source.manual')}</span>
				</label>
				<label class="radio">
					<input type="radio" bind:group={scaleSource} value="steps" />
					<span>{t('rotary.scale.source.steps')}</span>
				</label>

				{#if scaleSource === 'manual'}
					<NumberField
						label={t('rotary.scale.factor')}
						bind:value={manualScale}
						step={0.001}
						min={SCALE_MIN}
						max={SCALE_MAX}
					/>
				{:else if scaleSource === 'steps'}
					<NumberField label={t('rotary.scale.flatSteps')} bind:value={flatSteps} step={1} min={0} />
					<NumberField
						label={t('rotary.scale.rotarySteps')}
						bind:value={rotarySteps}
						step={1}
						min={0}
					/>
				{/if}

				<p class="fact">{t('rotary.scale.now', { factor: i18n.number(Math.round(draftScale * 10000) / 10000) })}</p>
				<!-- The factor in the terms of the thing you drew. 1.0363 says nothing;
				     "100 mm burns 103.6 mm" says everything. -->
				<p class="help">
					{t('rotary.scale.example', {
						drawn: i18n.number(100),
						burned: i18n.number(Math.round(burnedHeightMm(100, draftScale) * 10) / 10)
					})}
				</p>
				{#if !scaleIsSane(draftScale)}
					<!-- A warning, not an error: the setting is possible, it is simply not a
					     calibration any more. -->
					<Notice tone="warn">{t('rotary.scale.range', { min: i18n.number(SCALE_MIN), max: i18n.number(SCALE_MAX) })}</Notice>
				{/if}
			</fieldset>

			<div class="actions">
				<button class="btn primary" disabled={rotary.busy} title={rotary.busy ? t('reason.busy') : undefined} onclick={save}>
					{rotary.busy ? t('common.busy') : t('rotary.save')}
				</button>
			</div>
			{#if saved}<div class="after"><Notice tone="ok" live>{t('rotary.saved')}</Notice></div>{/if}

			<fieldset class="group">
				<legend class="label-section">{t('rotary.calibrate.title')}</legend>
				<p class="help">{t('rotary.calibrate.body')}</p>
				<NumberField
					label={t('rotary.calibrate.commanded')}
					unit="mm"
					bind:value={commanded}
					step={10}
					min={0}
				/>
				<NumberField
					label={t('rotary.calibrate.measured')}
					unit="mm"
					bind:value={measured}
					step={0.5}
					min={0}
				/>
				{#if Number(commanded) > 0 && Number(measured) > 0}
					<p class="fact">
						{t('rotary.calibrate.preview', {
							factor: i18n.number(Math.round(previewFactor * 10000) / 10000)
						})}
					</p>
				{/if}
				<div class="actions">
					<button
						class="btn"
						disabled={!previewUsable || rotary.busy}
						title={rotary.busy ? t('reason.busy') : t('api.rotary.needsMeasurement')}
						onclick={useFactor}
					>
						{t('rotary.calibrate.apply')}
					</button>
				</div>
				{#if rotary.state.last_calibration}
					<p class="help">
						{t('rotary.calibrate.last', {
							commanded: i18n.number(rotary.state.last_calibration.commanded_mm),
							measured: i18n.number(rotary.state.last_calibration.measured_mm),
							factor: i18n.number(Math.round(rotary.state.last_calibration.factor * 10000) / 10000)
						})}
					</p>
				{/if}
			</fieldset>
		{/if}

		<details class="fold rotary-help">
			<summary>{t('ux.rotary.coordinates')}</summary>
			<p>{t('rotary.intro')}</p>
			<ul>
				<li>{t('rotary.safety.frame')}</li>
				<li>{t('rotary.safety.preflight')}</li>
				<li>{t('rotary.safety.position')}</li>
			</ul>
			<p>{t('ux.rotary.scope')}</p>
		</details>
		<details class="fold rotary-help">
			<summary>{t('rotary.checklist.title')}</summary>
			<p>{t('rotary.checklist.intro')}</p>
			<ol>
				{#each CHECKLIST as key (key)}
					<li>{t(key)}</li>
				{/each}
			</ol>
		</details>
	{/if}
</section>

<style>
	/* Groups under a heading, not boxes: they already stand in the step's card. */
	.group {
		display: grid;
		gap: var(--space-2);
		min-width: 0;
		margin: var(--space-6) 0 0;
		padding: 0;
		border: 0;
	}
	/* A stepper as wide as the card puts − and + so far apart that they no longer read
	   as one control; the same width as on the work-area step. */
	.group > :global(.field) {
		max-width: 320px;
	}
	.group legend {
		padding: 0;
		margin-bottom: var(--space-2);
	}
	.switch,
	.radio {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		/* Beside a machine, with gloves on: a row you have to hit with a mouse pointer is
		   not a row you hit. */
		min-height: max(32px, var(--target-min));
	}
	.switch {
		margin-top: var(--space-4);
		font-weight: 500;
	}
	.fact {
		margin: 0;
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
	}
	.after {
		margin-top: var(--space-3);
	}
	.actions {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin-top: var(--space-4);
	}
	.rotary-help { margin-top: var(--space-4); }
	.rotary-help p, .rotary-help li { font-size: var(--text-xs); margin: var(--space-2) 0; max-width: var(--measure); }
	.rotary-help ul, .rotary-help ol { padding-left: var(--space-6); }
</style>
